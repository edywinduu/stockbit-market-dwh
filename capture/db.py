import psycopg2
from capture import config


def get_connection():
    return psycopg2.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        dbname=config.DB_NAME,
        user=config.DB_USER,
        password=config.DB_PASS,
    )


def get_active_tickers(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT ticker FROM staging.cfg_stock WHERE is_active = TRUE ORDER BY ticker")
        return [row[0] for row in cur.fetchall()]


def is_holiday(conn, target_date):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM staging.ref_holiday WHERE holiday_date = %s",
            (target_date,),
        )
        return cur.fetchone() is not None


def create_capture_log(conn, jenis, ticker, waktu_mulai, status, jumlah_baris=0, pesan_error=None, pemicu="SCHEDULER"):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO staging.capture_log
              (capture_type, ticker, started_at, finished_at, status, row_count, error_message, triggered_by)
            VALUES (%s, %s, %s, NOW(), %s, %s, %s, %s)
            RETURNING capture_id
            """,
            (jenis, ticker, waktu_mulai, status, jumlah_baris, pesan_error, pemicu),
        )
        capture_id = cur.fetchone()[0]
    conn.commit()
    return capture_id


def insert_orderbook_rows(conn, capture_id, ticker, captured_at, rows):
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO staging.orderbook_raw
              (capture_id, ticker, captured_at, side, level, price_raw, lot_raw, freq_raw)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    capture_id,
                    ticker,
                    captured_at,
                    r["side"],
                    r["level"],
                    r.get("price_raw"),
                    r.get("lot_raw"),
                    r.get("freq_raw"),
                )
                for r in rows
            ],
        )
    conn.commit()
    return len(rows)


def insert_broksum_rows(conn, capture_id, ticker, trade_date, rows):
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO staging.broksum_raw (
              capture_id, ticker, trade_date, broker_code,
              buy_lot_raw, buy_val_raw, buy_avg_raw,
              sell_lot_raw, sell_val_raw, sell_avg_raw
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (ticker, trade_date, broker_code) DO UPDATE SET
              capture_id = EXCLUDED.capture_id,
              buy_lot_raw = EXCLUDED.buy_lot_raw,
              buy_val_raw = EXCLUDED.buy_val_raw,
              buy_avg_raw = EXCLUDED.buy_avg_raw,
              sell_lot_raw = EXCLUDED.sell_lot_raw,
              sell_val_raw = EXCLUDED.sell_val_raw,
              sell_avg_raw = EXCLUDED.sell_avg_raw,
              is_processed = FALSE
            """,
            [
                (
                    capture_id,
                    ticker,
                    trade_date,
                    r["broker_code"],
                    r.get("buy_lot_raw"),
                    r.get("buy_val_raw"),
                    r.get("buy_avg_raw"),
                    r.get("sell_lot_raw"),
                    r.get("sell_val_raw"),
                    r.get("sell_avg_raw"),
                )
                for r in rows
            ],
        )
    conn.commit()
    return len(rows)
