from datetime import date
from capture import db


def is_trading_day(conn, target_date: date) -> bool:
    if target_date.weekday() >= 5:
        return False
    return not db.is_holiday(conn, target_date)
