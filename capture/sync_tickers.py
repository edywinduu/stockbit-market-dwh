import argparse
import csv
import io
import os
import sys

import psycopg2
from psycopg2.extras import execute_values
import requests
from dotenv import load_dotenv

DEFAULT_REMOTE_CSV_URL = (
    "https://raw.githubusercontent.com/wildangunawan/Dataset-Saham-IDX/master/List%20Emiten/all.csv"
)
DEFAULT_LOCAL_CSV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "database",
    "data",
    "idx_tickers.csv",
)


def _resolve_db_host() -> str:
    db_host = os.getenv("DB_HOST", "localhost")
    if not os.path.exists("/.dockerenv") and db_host == "db":
        return "127.0.0.1"
    return db_host


def get_db_connection():
    load_dotenv(override=True)
    return psycopg2.connect(
        host=_resolve_db_host(),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "dwh_saham"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASS", "postgres"),
    )


def _parse_csv_rows(text: str) -> list[tuple[str, str]]:
    reader = csv.DictReader(io.StringIO(text))
    tickers: dict[str, str] = {}
    for row in reader:
        norm_row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        code = (
            norm_row.get("code")
            or norm_row.get("ticker")
            or norm_row.get("symbol")
            or norm_row.get("emiten")
            or ""
        ).upper()
        name = (
            norm_row.get("name")
            or norm_row.get("company_name")
            or norm_row.get("nama")
            or ""
        )
        if code and len(code) <= 10 and code.isalnum():
            tickers[code] = name or code
    return sorted(tickers.items(), key=lambda x: x[0])


def fetch_remote_tickers(url: str = DEFAULT_REMOTE_CSV_URL, cache_path: str = DEFAULT_LOCAL_CSV) -> list[tuple[str, str]]:
    print(f"[TICKERS] Fetching IDX ticker list from {url} ...")
    res = requests.get(url, timeout=20)
    res.raise_for_status()
    rows = _parse_csv_rows(res.text)
    if not rows:
        raise ValueError("Remote CSV returned 0 valid tickers.")

    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ticker", "company_name"])
        writer.writerows(rows)
    print(f"[TICKERS] Cached {len(rows)} tickers locally to {cache_path}.")
    return rows


def load_local_csv_tickers(csv_path: str = DEFAULT_LOCAL_CSV) -> list[tuple[str, str]]:
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Local ticker CSV not found: {csv_path}")
    print(f"[TICKERS] Loading tickers from local CSV: {csv_path}")
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        rows = _parse_csv_rows(f.read())
    if not rows:
        raise ValueError(f"No valid tickers parsed from {csv_path}")
    return rows


def upsert_ref_tickers(rows: list[tuple[str, str]]) -> int:
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        execute_values(
            cur,
            """
            INSERT INTO staging.ref_ticker (ticker, company_name, is_active, updated_at)
            VALUES %s
            ON CONFLICT (ticker) DO UPDATE
              SET company_name = EXCLUDED.company_name,
                  is_active = TRUE,
                  updated_at = NOW();
            """,
            rows,
            template="(%s, %s, TRUE, NOW())",
            page_size=500,
        )
        conn.commit()
        return len(rows)
    finally:
        cur.close()
        conn.close()


def sync_tickers(source: str = "auto", csv_path: str | None = None, url: str = DEFAULT_REMOTE_CSV_URL) -> int:
    target_csv = csv_path or DEFAULT_LOCAL_CSV
    rows: list[tuple[str, str]] = []

    if source == "csv":
        rows = load_local_csv_tickers(target_csv)
    elif source == "remote":
        rows = fetch_remote_tickers(url=url, cache_path=target_csv)
    else:
        try:
            rows = fetch_remote_tickers(url=url, cache_path=target_csv)
        except Exception as e:
            print(f"[TICKERS] Remote fetch failed ({e}); falling back to local CSV...")
            rows = load_local_csv_tickers(target_csv)

    count = upsert_ref_tickers(rows)
    print(f"[TICKERS] Synced {count} active IDX tickers into staging.ref_ticker.")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync master IDX ticker list into staging.ref_ticker")
    parser.add_argument(
        "--source",
        choices=["auto", "remote", "csv"],
        default="auto",
        help="Ticker source: auto (remote with CSV fallback), remote, or csv",
    )
    parser.add_argument("--csv", default=None, help="Path to local CSV fallback file")
    parser.add_argument("--url", default=DEFAULT_REMOTE_CSV_URL, help="Remote CSV endpoint URL")
    args = parser.parse_args()

    try:
        sync_tickers(source=args.source, csv_path=args.csv, url=args.url)
    except Exception as e:
        print(f"[ERROR] Failed to sync tickers: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
