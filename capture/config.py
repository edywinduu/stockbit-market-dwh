import os
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "dwh_saham")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "postgres")

STOCKBIT_TOKEN = os.getenv("STOCKBIT_TOKEN", "").strip().strip('"').strip("'")
RETRY_MAX = int(os.getenv("RETRY_MAX", "3"))
RETRY_DELAY_SEC = int(os.getenv("RETRY_DELAY_SEC", "5"))
