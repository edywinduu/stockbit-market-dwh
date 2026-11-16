import os
import sys
import time
import schedule
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from capture.main import get_auth_header, run_capture


def job_orderbook():
    if datetime.now().weekday() < 5:
        print(f"[{datetime.now()}] Starting scheduled Order Book capture...")
        run_capture("orderbook", trigger="SCHEDULER")


def job_broksum():
    if datetime.now().weekday() < 5:
        print(f"[{datetime.now()}] Starting scheduled Broker Summary capture...")
        run_capture("broksum", trigger="SCHEDULER")


schedule.every().day.at("15:45").do(job_orderbook)
schedule.every().day.at("16:15").do(job_broksum)

if __name__ == "__main__":
    print(f"[{datetime.now()}] Scheduler active (WIB). Waiting for 15:45 (Orderbook) & 16:15 (Broksum)...")
    token = get_auth_header()
    print(f"[{datetime.now()}] Initial auth readiness check: {'OK' if token else 'MISSING'}")
    while True:
        schedule.run_pending()
        time.sleep(1)
