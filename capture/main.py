import argparse
from datetime import date, datetime, timedelta
import time
from zoneinfo import ZoneInfo

import requests

from capture.broksum_worker import (
    build_headers,
    fetch_and_store_broksum,
    get_auth_header,
    get_db,
    sleep_with_jitter,
)

WIB_TZ = ZoneInfo("Asia/Jakarta")


def get_headers(auth_header: str | None = None) -> dict:
    return build_headers(auth_header if auth_header is not None else get_auth_header())


def today_wib() -> date:
    return datetime.now(WIB_TZ).date()


def get_holidays() -> set[date]:
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT holiday_date FROM staging.ref_holiday;")
        return {row[0] for row in cur.fetchall()}
    finally:
        cur.close()
        conn.close()


def is_trading_day(target_date: date, holidays: set[date] | None = None) -> bool:
    if target_date.weekday() >= 5:
        return False
    holiday_set = holidays if holidays is not None else get_holidays()
    return target_date not in holiday_set


def get_active_tickers() -> list[str]:
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT ticker FROM staging.ref_ticker WHERE is_active = TRUE ORDER BY ticker ASC;")
        return [row[0] for row in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


def get_backfill_trading_dates(
    days: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    holidays: set[date] | None = None,
) -> list[date]:
    holiday_set = holidays if holidays is not None else get_holidays()

    if start_date or end_date:
        end = end_date or today_wib()
        start = start_date or end
        if start > end:
            raise ValueError("start_date cannot be after end_date.")
        dates: list[date] = []
        cursor = start
        while cursor <= end:
            if is_trading_day(cursor, holiday_set):
                dates.append(cursor)
            cursor += timedelta(days=1)
        return dates

    target_days = days if days and days > 0 else 1
    collected: list[date] = []
    cursor = today_wib()
    while len(collected) < target_days:
        if is_trading_day(cursor, holiday_set):
            collected.append(cursor)
        cursor -= timedelta(days=1)
    collected.reverse()
    return collected


def _execute_broksum_batch(
    trading_dates: list[date],
    tickers: list[str],
    *,
    force: bool = False,
    trigger: str = "MANUAL",
    mode_label: str = "daily",
) -> dict[str, int]:
    summary = {"SUCCESS": 0, "SKIPPED": 0, "FAILED": 0}
    if not trading_dates or not tickers:
        print(f"[INFO] Nothing to process (dates={len(trading_dates)}, tickers={len(tickers)}).")
        return summary

    auth_header = get_auth_header()
    total_units = len(trading_dates) * len(tickers)
    print(
        f"[JOB] Starting Broksum ({mode_label}): {len(trading_dates)} trading date(s) x "
        f"{len(tickers)} active ticker(s) = {total_units} unit(s) | force={force}"
    )

    with requests.Session() as session:
        for trade_date in trading_dates:
            for idx, ticker in enumerate(tickers, start=1):
                result = fetch_and_store_broksum(
                    ticker=ticker,
                    trade_date=trade_date,
                    auth_header=auth_header,
                    force=force,
                    trigger=trigger,
                    job_type="broksum",
                    session=session,
                )
                auth_header = result.get("auth_header") or auth_header
                status = result["status"]
                summary[status] = summary.get(status, 0) + 1

                # Apply jitter throttling only after live HTTP calls
                if status != "SKIPPED" and idx < len(tickers):
                    sleep_with_jitter()

    print(
        f"[SUMMARY] Broksum ({mode_label}) finished: "
        f"SUCCESS={summary['SUCCESS']}, SKIPPED={summary['SKIPPED']}, FAILED={summary['FAILED']}"
    )
    return summary


def run_broksum_backfill(
    days: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    ticker: str | None = None,
    force: bool = False,
    trigger: str = "MANUAL",
) -> dict[str, int]:
    trading_dates = get_backfill_trading_dates(days=days, start_date=start_date, end_date=end_date)
    tickers = [ticker.strip().upper()] if ticker else get_active_tickers()
    return _execute_broksum_batch(
        trading_dates,
        tickers,
        force=force,
        trigger=trigger,
        mode_label="backfill",
    )


def run_broksum_daily(
    ticker: str | None = None,
    force: bool = False,
    trigger: str = "SCHEDULER",
) -> dict[str, int]:
    target_date = today_wib()
    holidays = get_holidays()

    if not force and not is_trading_day(target_date, holidays):
        reason = "Weekend" if target_date.weekday() >= 5 else "Market Holiday"
        print(f"[SKIP] {target_date} is non-trading day ({reason}). Exiting daily broksum cleanly.")
        return {"SUCCESS": 0, "SKIPPED": 1, "FAILED": 0}

    tickers = [ticker.strip().upper()] if ticker else get_active_tickers()
    return _execute_broksum_batch(
        [target_date],
        tickers,
        force=force,
        trigger=trigger,
        mode_label="daily",
    )


# Parked Order Book routine (kept intact, unscheduled)
def capture_orderbook(ticker: str, trigger: str = "MANUAL"):
    url = f"https://exodus.stockbit.com/company-price-feed/v2/orderbook/companies/{ticker}"
    started_at = datetime.now()
    conn = get_db()
    cur = conn.cursor()
    capture_id = None

    try:
        cur.execute(
            """
            INSERT INTO staging.capture_log (capture_type, job_type, ticker, started_at, status, triggered_by)
            VALUES ('orderbook', 'orderbook', %s, %s, 'RUNNING', %s)
            RETURNING capture_id;
            """,
            (ticker, started_at, trigger),
        )
        capture_id = cur.fetchone()[0]
        conn.commit()

        res = requests.get(url, headers=get_headers(), timeout=15)
        res.raise_for_status()
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
            cur.execute(
                query,
                (
                    capture_id,
                    ticker,
                    captured_at,
                    "B",
                    level,
                    str(item.get("price", "0")),
                    str(item.get("volume", "0")),
                    str(item.get("que_num", "0")),
                ),
            )
        for level, item in enumerate(offers, start=1):
            cur.execute(
                query,
                (
                    capture_id,
                    ticker,
                    captured_at,
                    "O",
                    level,
                    str(item.get("price", "0")),
                    str(item.get("volume", "0")),
                    str(item.get("que_num", "0")),
                ),
            )

        total_rows = len(bids) + len(offers)
        cur.execute(
            """
            UPDATE staging.capture_log
            SET finished_at = %s, status = 'SUCCESS', row_count = %s, updated_at = NOW()
            WHERE capture_id = %s;
            """,
            (datetime.now(), total_rows, capture_id),
        )
        conn.commit()
        print(f"[SUCCESS] Orderbook {ticker}: {total_rows} rows saved.")

    except Exception as e:
        conn.rollback()
        if capture_id:
            cur.execute(
                """
                UPDATE staging.capture_log
                SET finished_at = %s, status = 'FAILED', error_message = %s, updated_at = NOW()
                WHERE capture_id = %s;
                """,
                (datetime.now(), str(e), capture_id),
            )
            conn.commit()
        print(f"[FAILED] Orderbook {ticker}: {e}")
    finally:
        cur.close()
        conn.close()


def _parse_iso_date(val: str | None) -> date | None:
    if not val:
        return None
    return datetime.strptime(val, "%Y-%m-%d").date()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stockbit Broksum Data Capture CLI")
    parser.add_argument("job", choices=["broksum", "orderbook"])
    parser.add_argument("--mode", default="daily", choices=["daily", "backfill"], help="Broksum execution mode")
    parser.add_argument("--days", type=int, default=None, help="Number of past IDX trading days for backfill")
    parser.add_argument("--start-date", default=None, help="Backfill start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", default=None, help="Backfill end date (YYYY-MM-DD)")
    parser.add_argument("--ticker", default=None, help="Optional single ticker override")
    parser.add_argument("--force", action="store_true", help="Force re-fetch ignoring SUCCESS checkpoints & holidays")
    parser.add_argument("--trigger", default="MANUAL", choices=["MANUAL", "SCHEDULER"])
    args = parser.parse_args()

    if args.job == "broksum":
        if args.mode == "backfill":
            if not args.days and not args.start_date and not args.end_date:
                parser.error("--mode backfill requires --days <X> or --start-date/--end-date.")
            run_broksum_backfill(
                days=args.days,
                start_date=_parse_iso_date(args.start_date),
                end_date=_parse_iso_date(args.end_date),
                ticker=args.ticker,
                force=args.force,
                trigger=args.trigger,
            )
        else:
            run_broksum_daily(
                ticker=args.ticker,
                force=args.force,
                trigger=args.trigger,
            )
    elif args.job == "orderbook":
        print("[INFO] Orderbook capture is currently parked from the active pipeline.")
        targets = [args.ticker.strip().upper()] if args.ticker else get_active_tickers()
        for t in targets:
            capture_orderbook(t, args.trigger)
            time.sleep(2)
