from datetime import date, datetime
import os
import random
import time

import psycopg2
from psycopg2.extras import execute_values
import requests
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "dwh_saham")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "postgres")

BACKOFF_DELAYS_SEC = (5, 15, 30)
JITTER_MIN_SEC = float(os.getenv("JITTER_MIN_SEC", "0.5"))
JITTER_MAX_SEC = float(os.getenv("JITTER_MAX_SEC", "1.5"))

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def _normalize_bearer(raw_token: str) -> str:
    token = (raw_token or "").strip().strip('"').strip("'")
    if not token:
        return ""
    return token if token.lower().startswith("bearer ") else f"Bearer {token}"


def get_db():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASS
    )


def get_auth_header(verbose: bool = True) -> str:
    """Resolve active Stockbit Authorization header from staging.cfg_auth, with .env fallback."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT auth_header FROM staging.cfg_auth WHERE provider = 'stockbit';")
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and row[0] and row[0].strip():
            if verbose:
                print("[AUTH] Loaded active token for 'stockbit' from staging.cfg_auth.")
            return _normalize_bearer(row[0])
    except Exception as e:
        if verbose:
            print(f"[AUTH] Failed reading staging.cfg_auth ({e}); falling back to STOCKBIT_TOKEN env.")

    if verbose:
        print("[AUTH] No token in staging.cfg_auth for 'stockbit'; falling back to STOCKBIT_TOKEN env.")
    load_dotenv(override=True)
    return _normalize_bearer(os.getenv("STOCKBIT_TOKEN", ""))


def build_headers(auth_header: str) -> dict:
    return {
        "User-Agent": USER_AGENT,
        "Authorization": _normalize_bearer(auth_header),
        "Accept": "application/json",
        "Origin": "https://stockbit.com",
        "Referer": "https://stockbit.com/",
    }


def sleep_with_jitter(min_sec: float = JITTER_MIN_SEC, max_sec: float = JITTER_MAX_SEC) -> float:
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)
    return delay


def is_checkpoint_done(conn, job_type: str, ticker: str, trade_date: date) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM staging.capture_log
            WHERE job_type = %s AND ticker = %s AND trade_date = %s AND status = 'SUCCESS';
            """,
            (job_type, ticker, trade_date),
        )
        return cur.fetchone() is not None


def upsert_capture_log(
    conn,
    *,
    job_type: str,
    ticker: str,
    trade_date: date,
    started_at: datetime,
    finished_at: datetime | None,
    status: str,
    row_count: int = 0,
    error_message: str | None = None,
    trigger: str = "MANUAL",
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO staging.capture_log (
              capture_type, job_type, ticker, trade_date,
              started_at, finished_at, status, row_count,
              error_message, triggered_by, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (job_type, ticker, trade_date) DO UPDATE
              SET capture_type = EXCLUDED.capture_type,
                  started_at = EXCLUDED.started_at,
                  finished_at = EXCLUDED.finished_at,
                  status = EXCLUDED.status,
                  row_count = EXCLUDED.row_count,
                  error_message = EXCLUDED.error_message,
                  triggered_by = EXCLUDED.triggered_by,
                  updated_at = NOW()
            RETURNING capture_id;
            """,
            (
                job_type,
                job_type,
                ticker,
                trade_date,
                started_at,
                finished_at,
                status,
                row_count,
                error_message,
                trigger,
            ),
        )
        capture_id = cur.fetchone()[0]
    conn.commit()
    return capture_id


def _request_broksum_with_resilience(
    ticker: str,
    trade_date: date,
    auth_header: str,
    session: requests.Session | None = None,
) -> tuple[requests.Response, str]:
    """
    Request Stockbit Broker Summary for an explicit trade_date with:
      - Single 401 re-fetch from staging.cfg_auth
      - Exponential backoff (5s -> 15s -> 30s, max 3 retries) for 429 / 5xx / network errors
    """
    date_str = trade_date.strftime("%Y-%m-%d")
    url = f"https://exodus.stockbit.com/marketdetectors/{ticker}"
    params = {
        "from": date_str,
        "to": date_str,
        "transaction_type": "TRANSACTION_TYPE_NET",
        "market_board": "MARKET_BOARD_REGULER",
        "investor_type": "INVESTOR_TYPE_ALL",
        "limit": 25,
    }

    http = session or requests
    active_auth = _normalize_bearer(auth_header)
    refreshed_on_401 = False
    last_exc: Exception | None = None

    for attempt in range(len(BACKOFF_DELAYS_SEC) + 1):
        try:
            res = http.get(url, params=params, headers=build_headers(active_auth), timeout=15)

            if res.status_code == 401 and not refreshed_on_401:
                print(f"[AUTH] 401 for {ticker} ({date_str}). Re-fetching latest token from staging.cfg_auth...")
                refreshed_on_401 = True
                active_auth = get_auth_header(verbose=True)
                res = http.get(url, params=params, headers=build_headers(active_auth), timeout=15)

            if res.status_code == 429 or 500 <= res.status_code < 600:
                if attempt < len(BACKOFF_DELAYS_SEC):
                    delay = BACKOFF_DELAYS_SEC[attempt]
                    retry_after = res.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        delay = max(delay, int(retry_after))
                    print(
                        f"[BACKOFF] HTTP {res.status_code} for {ticker} ({date_str}). "
                        f"Retry {attempt + 1}/{len(BACKOFF_DELAYS_SEC)} in {delay}s..."
                    )
                    time.sleep(delay)
                    continue

            res.raise_for_status()
            return res, active_auth

        except requests.HTTPError as e:
            last_exc = e
            status_code = e.response.status_code if e.response is not None else 0
            if status_code not in (429,) and not (500 <= status_code < 600):
                raise
        except requests.RequestException as e:
            last_exc = e
            if attempt < len(BACKOFF_DELAYS_SEC):
                delay = BACKOFF_DELAYS_SEC[attempt]
                print(
                    f"[BACKOFF] Network error for {ticker} ({date_str}): {e}. "
                    f"Retry {attempt + 1}/{len(BACKOFF_DELAYS_SEC)} in {delay}s..."
                )
                time.sleep(delay)
                continue
            raise

    raise last_exc if last_exc else RuntimeError(f"Failed fetching broksum for {ticker} ({date_str})")


def _parse_broksum_records(raw_json: dict) -> dict[str, dict[str, str]]:
    data_obj = raw_json.get("data") or {}
    bs_data = data_obj.get("broker_summary") or {}
    brokers_buy = bs_data.get("brokers_buy") or []
    brokers_sell = bs_data.get("brokers_sell") or []

    records: dict[str, dict[str, str]] = {}
    for b in brokers_buy:
        code = (b.get("netbs_broker_code") or "").strip()
        if not code:
            continue
        records[code] = {
            "buy_lot": str(b.get("blot", "0")),
            "buy_val": str(b.get("bval", "0")),
            "buy_avg": str(b.get("netbs_buy_avg_price", "0")),
            "sell_lot": "0",
            "sell_val": "0",
            "sell_avg": "0",
        }

    for s in brokers_sell:
        code = (s.get("netbs_broker_code") or "").strip()
        if not code:
            continue
        slot_clean = str(abs(float(s.get("slot") or 0)))
        sval_clean = str(abs(float(s.get("sval") or 0)))
        savg_clean = str(s.get("netbs_sell_avg_price", "0"))

        if code not in records:
            records[code] = {
                "buy_lot": "0",
                "buy_val": "0",
                "buy_avg": "0",
                "sell_lot": slot_clean,
                "sell_val": sval_clean,
                "sell_avg": savg_clean,
            }
        else:
            records[code]["sell_lot"] = slot_clean
            records[code]["sell_val"] = sval_clean
            records[code]["sell_avg"] = savg_clean

    return records


def fetch_and_store_broksum(
    ticker: str,
    trade_date: date,
    auth_header: str,
    *,
    force: bool = False,
    trigger: str = "MANUAL",
    job_type: str = "broksum",
    session: requests.Session | None = None,
) -> dict:
    """
    Stateless single-unit Broksum fetcher for (ticker, trade_date).
    Safe to wrap in ThreadPoolExecutor / asyncio / Celery workers.
    """
    ticker = ticker.strip().upper()
    date_str = trade_date.strftime("%Y-%m-%d")
    started_at = datetime.now()
    active_auth = _normalize_bearer(auth_header)

    conn = get_db()
    capture_id: int | None = None
    try:
        if not force and is_checkpoint_done(conn, job_type, ticker, trade_date):
            return {
                "ticker": ticker,
                "trade_date": date_str,
                "status": "SKIPPED",
                "row_count": 0,
                "auth_header": active_auth,
                "error": None,
            }

        capture_id = upsert_capture_log(
            conn,
            job_type=job_type,
            ticker=ticker,
            trade_date=trade_date,
            started_at=started_at,
            finished_at=None,
            status="RUNNING",
            row_count=0,
            error_message=None,
            trigger=trigger,
        )

        res, active_auth = _request_broksum_with_resilience(
            ticker=ticker,
            trade_date=trade_date,
            auth_header=active_auth,
            session=session,
        )
        raw_json = res.json()
        records = _parse_broksum_records(raw_json)

        if records:
            rows = [
                (
                    capture_id,
                    ticker,
                    trade_date,
                    broker_code,
                    item["buy_lot"],
                    item["buy_val"],
                    item["buy_avg"],
                    item["sell_lot"],
                    item["sell_val"],
                    item["sell_avg"],
                )
                for broker_code, item in records.items()
            ]
            with conn.cursor() as cur:
                execute_values(
                    cur,
                    """
                    INSERT INTO staging.broksum_raw (
                      capture_id, ticker, trade_date, broker_code,
                      buy_lot_raw, buy_val_raw, buy_avg_raw,
                      sell_lot_raw, sell_val_raw, sell_avg_raw,
                      is_processed, updated_at
                    )
                    VALUES %s
                    ON CONFLICT (ticker, trade_date, broker_code) DO UPDATE
                      SET capture_id = EXCLUDED.capture_id,
                          buy_lot_raw = EXCLUDED.buy_lot_raw,
                          buy_val_raw = EXCLUDED.buy_val_raw,
                          buy_avg_raw = EXCLUDED.buy_avg_raw,
                          sell_lot_raw = EXCLUDED.sell_lot_raw,
                          sell_val_raw = EXCLUDED.sell_val_raw,
                          sell_avg_raw = EXCLUDED.sell_avg_raw,
                          is_processed = FALSE,
                          updated_at = NOW();
                    """,
                    rows,
                    template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, NOW())",
                    page_size=200,
                )
            conn.commit()

        total_rows = len(records)
        upsert_capture_log(
            conn,
            job_type=job_type,
            ticker=ticker,
            trade_date=trade_date,
            started_at=started_at,
            finished_at=datetime.now(),
            status="SUCCESS",
            row_count=total_rows,
            error_message=None,
            trigger=trigger,
        )
        print(f"[SUCCESS] Broksum {ticker} ({date_str}): {total_rows} brokers saved.")
        return {
            "ticker": ticker,
            "trade_date": date_str,
            "status": "SUCCESS",
            "row_count": total_rows,
            "auth_header": active_auth,
            "error": None,
        }

    except Exception as e:
        conn.rollback()
        upsert_capture_log(
            conn,
            job_type=job_type,
            ticker=ticker,
            trade_date=trade_date,
            started_at=started_at,
            finished_at=datetime.now(),
            status="FAILED",
            row_count=0,
            error_message=str(e),
            trigger=trigger,
        )
        print(f"[FAILED] Broksum {ticker} ({date_str}): {e}")
        return {
            "ticker": ticker,
            "trade_date": date_str,
            "status": "FAILED",
            "row_count": 0,
            "auth_header": active_auth,
            "error": str(e),
        }
    finally:
        conn.close()
