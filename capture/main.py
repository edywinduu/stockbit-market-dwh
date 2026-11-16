import os
import time
import argparse
import requests
import psycopg2
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "dwh_saham")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "postgres")
RETRY_MAX = int(os.getenv("RETRY_MAX", "3"))
RETRY_DELAY_SEC = int(os.getenv("RETRY_DELAY_SEC", "5"))


def _normalize_bearer(raw_token: str) -> str:
    token = (raw_token or "").strip().strip('"').strip("'")
    if not token:
        return ""
    return token if token.lower().startswith("bearer ") else f"Bearer {token}"


def get_db():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASS
    )


def get_auth_header() -> str:
    """Resolve active Stockbit Authorization header from staging.cfg_auth, with .env fallback."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT auth_header FROM staging.cfg_auth WHERE provider = 'stockbit';")
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and row[0] and row[0].strip():
            print("[AUTH] Loaded active token for 'stockbit' from staging.cfg_auth.")
            return _normalize_bearer(row[0])
    except Exception as e:
        print(f"[AUTH] Failed reading staging.cfg_auth ({e}); falling back to STOCKBIT_TOKEN env.")

    print("[AUTH] No token in staging.cfg_auth for 'stockbit'; falling back to STOCKBIT_TOKEN env.")
    load_dotenv(override=True)
    return _normalize_bearer(os.getenv("STOCKBIT_TOKEN", ""))


def get_headers(auth_header: str | None = None) -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Authorization": auth_header if auth_header is not None else get_auth_header(),
        "Accept": "application/json",
        "Origin": "https://stockbit.com",
        "Referer": "https://stockbit.com/",
    }


def _get_with_retry(url: str, params: dict | None = None) -> requests.Response:
    """Perform HTTP GET with retry on transient failures and auth re-fetch on 401."""
    headers = get_headers()
    last_exc = None
    for attempt in range(1, RETRY_MAX + 1):
        try:
            res = requests.get(url, params=params, headers=headers, timeout=15)
            if res.status_code == 401:
                print("[AUTH] 401 Unauthorized. Re-checking staging.cfg_auth for refreshed token...")
                headers = get_headers()
                res = requests.get(url, params=params, headers=headers, timeout=15)
                if res.status_code == 401:
                    print("[AUTH] Still 401 Unauthorized. Run `.\\.venv\\Scripts\\python -m capture.sync_session --interactive` on host to sync a fresh token.")
            res.raise_for_status()
            return res
        except requests.HTTPError as e:
            last_exc = e
            if e.response is not None and 400 <= e.response.status_code < 500 and e.response.status_code != 429:
                raise
        except requests.RequestException as e:
            last_exc = e

        if attempt < RETRY_MAX:
            print(f"[RETRY] Attempt {attempt}/{RETRY_MAX} failed ({last_exc}). Retrying in {RETRY_DELAY_SEC}s...")
            time.sleep(RETRY_DELAY_SEC)
    raise last_exc

def is_holiday():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM staging.ref_holiday WHERE holiday_date = CURRENT_DATE;")
    res = cur.fetchone()
    cur.close()
    conn.close()
    return res is not None

def get_active_tickers():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT ticker FROM staging.cfg_stock WHERE is_active = TRUE ORDER BY ticker ASC;")
    tickers = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return tickers

def capture_orderbook(ticker: str, trigger="MANUAL"):
    url = f"https://exodus.stockbit.com/company-price-feed/v2/orderbook/companies/{ticker}"
    started_at = datetime.now()
    conn = get_db()
    cur = conn.cursor()
    capture_id = None

    try:
        cur.execute("""
            INSERT INTO staging.capture_log (capture_type, ticker, started_at, status, triggered_by)
            VALUES ('orderbook', %s, %s, 'RUNNING', %s)
            RETURNING capture_id;
        """, (ticker, started_at, trigger))
        capture_id = cur.fetchone()[0]
        conn.commit()

        res = _get_with_retry(url)
        data = res.json().get("data", {})

        captured_at = datetime.now()
        bids = data.get("bid", [])[:10]
        offers = data.get("offer", [])[:10]

        query = """
            INSERT INTO staging.orderbook_raw 
            (capture_id, ticker, captured_at, side, level, price_raw, lot_raw, freq_raw)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
        """

        for level, item in enumerate(bids, start=1):
            cur.execute(query, (
                capture_id, ticker, captured_at, 'B', level,
                str(item.get("price", "0")), str(item.get("volume", "0")), str(item.get("que_num", "0"))
            ))

        for level, item in enumerate(offers, start=1):
            cur.execute(query, (
                capture_id, ticker, captured_at, 'O', level,
                str(item.get("price", "0")), str(item.get("volume", "0")), str(item.get("que_num", "0"))
            ))

        total_rows = len(bids) + len(offers)
        cur.execute("""
            UPDATE staging.capture_log 
            SET finished_at = %s, status = 'SUCCESS', row_count = %s
            WHERE capture_id = %s;
        """, (datetime.now(), total_rows, capture_id))
        conn.commit()
        print(f"[SUCCESS] Orderbook {ticker}: {total_rows} rows saved.")

    except Exception as e:
        conn.rollback()
        if capture_id:
            cur.execute("""
                UPDATE staging.capture_log 
                SET finished_at = %s, status = 'FAILED', error_message = %s
                WHERE capture_id = %s;
            """, (datetime.now(), str(e), capture_id))
            conn.commit()
        print(f"[FAILED] Orderbook {ticker}: {e}")
    finally:
        cur.close()
        conn.close()

def capture_broksum(ticker: str, trigger="MANUAL"):
    url = f"https://exodus.stockbit.com/marketdetectors/{ticker}"
    params = {
        "transaction_type": "TRANSACTION_TYPE_NET",
        "market_board": "MARKET_BOARD_REGULER",
        "investor_type": "INVESTOR_TYPE_ALL",
        "limit": 25,
        "period": "BROKER_SUMMARY_PERIOD_LATEST"
    }
    started_at = datetime.now()
    conn = get_db()
    cur = conn.cursor()
    capture_id = None

    try:
        cur.execute("""
            INSERT INTO staging.capture_log (capture_type, ticker, started_at, status, triggered_by)
            VALUES ('broksum', %s, %s, 'RUNNING', %s)
            RETURNING capture_id;
        """, (ticker, started_at, trigger))
        capture_id = cur.fetchone()[0]
        conn.commit()

        res = _get_with_retry(url, params=params)
        raw_json = res.json()

        data_obj = raw_json.get("data", {})
        trade_date = data_obj.get("from", str(datetime.now().date()))
        bs_data = data_obj.get("broker_summary", {})
        brokers_buy = bs_data.get("brokers_buy", [])
        brokers_sell = bs_data.get("brokers_sell", [])

        records = {}
        for b in brokers_buy:
            code = b.get("netbs_broker_code")
            if not code:
                continue
            records[code] = {
                "buy_lot": str(b.get("blot", "0")),
                "buy_val": str(b.get("bval", "0")),
                "buy_avg": str(b.get("netbs_buy_avg_price", "0")),
                "sell_lot": "0", "sell_val": "0", "sell_avg": "0"
            }

        for s in brokers_sell:
            code = s.get("netbs_broker_code")
            if not code:
                continue
            slot_clean = str(abs(float(s.get("slot", 0))))
            sval_clean = str(abs(float(s.get("sval", 0))))
            savg_clean = str(s.get("netbs_sell_avg_price", "0"))

            if code not in records:
                records[code] = {
                    "buy_lot": "0", "buy_val": "0", "buy_avg": "0",
                    "sell_lot": slot_clean, "sell_val": sval_clean, "sell_avg": savg_clean
                }
            else:
                records[code]["sell_lot"] = slot_clean
                records[code]["sell_val"] = sval_clean
                records[code]["sell_avg"] = savg_clean

        insert_query = """
            INSERT INTO staging.broksum_raw 
            (capture_id, ticker, trade_date, broker_code, buy_lot_raw, buy_val_raw, buy_avg_raw, sell_lot_raw, sell_val_raw, sell_avg_raw)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (ticker, trade_date, broker_code) DO UPDATE
            SET capture_id = EXCLUDED.capture_id,
                buy_lot_raw = EXCLUDED.buy_lot_raw,
                buy_val_raw = EXCLUDED.buy_val_raw,
                buy_avg_raw = EXCLUDED.buy_avg_raw,
                sell_lot_raw = EXCLUDED.sell_lot_raw,
                sell_val_raw = EXCLUDED.sell_val_raw,
                sell_avg_raw = EXCLUDED.sell_avg_raw,
                is_processed = FALSE;
        """

        for broker_code, item in records.items():
            cur.execute(insert_query, (
                capture_id, ticker, trade_date, broker_code,
                item["buy_lot"], item["buy_val"], item["buy_avg"],
                item["sell_lot"], item["sell_val"], item["sell_avg"]
            ))

        total_rows = len(records)
        cur.execute("""
            UPDATE staging.capture_log 
            SET finished_at = %s, status = 'SUCCESS', row_count = %s
            WHERE capture_id = %s;
        """, (datetime.now(), total_rows, capture_id))
        conn.commit()
        print(f"[SUCCESS] Broksum {ticker} ({trade_date}): {total_rows} brokers saved.")

    except Exception as e:
        conn.rollback()
        if capture_id:
            cur.execute("""
                UPDATE staging.capture_log 
                SET finished_at = %s, status = 'FAILED', error_message = %s
                WHERE capture_id = %s;
            """, (datetime.now(), str(e), capture_id))
            conn.commit()
        print(f"[FAILED] Broksum {ticker}: {e}")
    finally:
        cur.close()
        conn.close()

def run_capture(job_type: str, ticker: str = None, trigger: str = "SCHEDULER"):
    if trigger == "SCHEDULER" and is_holiday():
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO staging.capture_log (capture_type, started_at, finished_at, status, error_message, triggered_by)
            VALUES (%s, NOW(), NOW(), 'SKIPPED', 'Market Holiday', 'SCHEDULER');
        """, (job_type,))
        conn.commit()
        cur.close()
        conn.close()
        print(f"[SKIP] Market holiday today ({job_type}).")
        return

    target_tickers = [ticker] if ticker else get_active_tickers()
    for t in target_tickers:
        if job_type == "orderbook":
            capture_orderbook(t, trigger)
        elif job_type == "broksum":
            capture_broksum(t, trigger)
        time.sleep(2)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stockbit Data Capture CLI")
    parser.add_argument("job", choices=["orderbook", "broksum"])
    parser.add_argument("--ticker", help="Ticker tunggal (opsional)")
    parser.add_argument("--trigger", default="MANUAL", choices=["MANUAL", "SCHEDULER"])
    args = parser.parse_args()

    run_capture(args.job, args.ticker, args.trigger)