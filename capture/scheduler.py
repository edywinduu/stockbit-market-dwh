from datetime import datetime
import os
import sys
import time
from zoneinfo import ZoneInfo

import schedule

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from capture.main import capture_orderbook, get_active_tickers, get_auth_header, run_broksum_daily

WIB_TZ = ZoneInfo("Asia/Jakarta")


# Parked: Order Book capture (kept intact, intentionally unscheduled)
def job_orderbook():
    if datetime.now(WIB_TZ).weekday() < 5:
        print(f"[{datetime.now(WIB_TZ)}] Starting parked Order Book capture...")
        for ticker in get_active_tickers():
            capture_orderbook(ticker, trigger="SCHEDULER")


def job_broksum_daily():
    now_wib = datetime.now(WIB_TZ)
    if now_wib.weekday() < 5:
        print(f"[{now_wib}] Starting scheduled Daily EOD Broker Summary capture...")
        run_broksum_daily(trigger="SCHEDULER")


# Schedule ONLY Daily EOD Broksum Monday-Friday at 16:15 WIB (Asia/Jakarta)
schedule.every().monday.at("16:15").do(job_broksum_daily)
schedule.every().tuesday.at("16:15").do(job_broksum_daily)
schedule.every().wednesday.at("16:15").do(job_broksum_daily)
schedule.every().thursday.at("16:15").do(job_broksum_daily)
schedule.every().friday.at("16:15").do(job_broksum_daily)

if __name__ == "__main__":
    now_wib = datetime.now(WIB_TZ)
    token = get_auth_header()
    try:
        active_count = len(get_active_tickers())
    except Exception as e:
        active_count = 0
        print(f"[{now_wib}] Warning: failed reading staging.ref_ticker ({e})")

    print(
        f"[{now_wib}] Scheduler active (Asia/Jakarta). "
        f"Scheduled ONLY Daily EOD Broksum Mon-Fri at 16:15 WIB | "
        f"Active tickers: {active_count} | Auth: {'OK' if token else 'MISSING'}"
    )
    while True:
        schedule.run_pending()
        time.sleep(1)
