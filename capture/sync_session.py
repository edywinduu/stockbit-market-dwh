import argparse
import base64
from datetime import datetime, timezone
import json
import os
import sys
import time


def _resolve_db_host() -> str:
    db_host = os.getenv("DB_HOST", "localhost")
    if not os.path.exists("/.dockerenv") and db_host == "db":
        return "127.0.0.1"
    return db_host


def get_db_connection():
    try:
        import psycopg2
        from dotenv import load_dotenv
    except ImportError as exc:
        print(
            f"[ERROR] Missing dependency ({exc.name}). Install host dependencies first:\n"
            "  .\\.venv\\Scripts\\python -m pip install playwright psycopg2-binary python-dotenv\n"
            "  .\\.venv\\Scripts\\playwright install chromium"
        )
        sys.exit(1)

    load_dotenv(override=True)
    return psycopg2.connect(
        host=_resolve_db_host(),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "dwh_saham"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASS", "postgres"),
    )


def parse_jwt(token: str) -> dict | None:
    try:
        clean = token.replace("Bearer ", "").replace("bearer ", "").strip()
        clean = clean.strip('"').strip("'")
        parts = clean.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(payload.encode("utf-8")))
    except Exception:
        return None


def is_jwt_active(token: str, buffer_sec: int = 120) -> tuple[bool, str]:
    """
    Checks if token is a valid, unexpired ACCESS token.
    Returns (is_active, reason_or_status).
    """
    payload = parse_jwt(token)
    if not payload:
        return False, "Bukan format JWT valid"

    data = payload.get("data", {})
    if isinstance(data, dict) and data.get("typ") == "refresh":
        return False, "Ini Refresh Token (bukan Access Token)"

    exp = payload.get("exp")
    if not exp or not isinstance(exp, (int, float)):
        return False, "Tidak memiliki waktu kedaluwarsa (exp)"

    now_ts = datetime.now(timezone.utc).timestamp()
    if now_ts >= (exp - buffer_sec):
        exp_str = datetime.fromtimestamp(exp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return False, f"Token sudah kedaluwarsa pada {exp_str}"

    exp_str = datetime.fromtimestamp(exp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return True, f"Valid s/d {exp_str}"


def upsert_auth_header(provider: str, auth_header: str) -> None:
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO staging.cfg_auth (provider, auth_header, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (provider) DO UPDATE
              SET auth_header = EXCLUDED.auth_header,
                  updated_at = NOW();
            """,
            (provider, auth_header),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def sync_stockbit_session(interactive: bool = False, profile_dir: str | None = None, ticker: str = "BBCA") -> str | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "[ERROR] Playwright is not installed. Run on host inside .venv:\n"
            "  .\\.venv\\Scripts\\python -m pip install playwright psycopg2-binary python-dotenv\n"
            "  .\\.venv\\Scripts\\playwright install chromium"
        )
        sys.exit(1)

    session_dir = os.path.expanduser(
        profile_dir or os.getenv("STOCKBIT_SESSION_DIR", "~/.stockbit_session")
    )
    os.makedirs(session_dir, exist_ok=True)

    captured_auth: dict[str, str | None] = {"header": None}

    def check_candidate(candidate: str | None, source: str = "") -> bool:
        if not candidate or captured_auth["header"]:
            return False
        clean = candidate.strip()
        bearer = clean if clean.lower().startswith("bearer ") else f"Bearer {clean}"

        valid, reason = is_jwt_active(bearer)
        if valid:
            payload = parse_jwt(bearer)
            username = (payload.get("data") or {}).get("use", "user")
            print(f"[SYNC] -> Berhasil menemukan Access Token dari {source}! ({reason}, User: {username})")
            captured_auth["header"] = bearer
            return True
        return False

    def on_request(request) -> None:
        if captured_auth["header"]:
            return
        # Hanya tangkap dari request API ke exodus.stockbit.com
        if "exodus.stockbit.com" in request.url:
            headers = request.headers
            auth_val = headers.get("authorization") or headers.get("Authorization")
            if auth_val and "bearer " in auth_val.lower():
                check_candidate(auth_val, source=f"Request ke {request.url[:50]}")

    target_url = "https://stockbit.com/login" if interactive else f"https://stockbit.com/symbol/{ticker}"
    wait_timeout_sec = 300 if interactive else 20

    print(f"[SYNC] Membuka Playwright browser ({'GUI Interaktif' if interactive else 'Headless'})...")
    print(f"[SYNC] Direktori Sesi: {session_dir}")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=session_dir,
            headless=not interactive,
            viewport={"width": 1280, "height": 800},
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            context.on("request", on_request)
            page.on("request", on_request)

            page.goto(target_url, wait_until="domcontentloaded", timeout=30000)

            if interactive:
                print("=" * 70)
                print("PANDUAN LOGIN INTERAKTIF:")
                print("1. Jendela browser Stockbit sekarang terbuka di layar Anda.")
                print("2. Silakan ketik username & password (dan OTP/2FA jika ada).")
                print("3. Klik Login sampai Anda MASUK ke halaman Stockbit.")
                print("4. Jendela browser TIDAK AKAN MENUTUP sampai Anda berhasil login.")
                print("=" * 70)

            deadline = time.time() + wait_timeout_sec
            while time.time() < deadline and not captured_auth["header"]:
                page.wait_for_timeout(1000)

                current_url = page.url.lower()

                # Di mode interaktif, selama masih di halaman login/register, JANGAN keluar
                if interactive and ("login" in current_url or "register" in current_url) and not captured_auth["header"]:
                    continue

                # Jika pengguna sudah melewati halaman login, periksa localStorage untuk access token
                if not captured_auth["header"]:
                    try:
                        tokens = page.evaluate(r"""() => {
                            const res = [];
                            for (let i = 0; i < localStorage.length; i++) {
                                const val = localStorage.getItem(localStorage.key(i));
                                if (val && typeof val === 'string' && val.includes('eyJ')) {
                                    const matches = val.match(/eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g);
                                    if (matches) res.push(...matches);
                                }
                            }
                            return res;
                        }""")
                        if isinstance(tokens, list):
                            for t in tokens:
                                if check_candidate(t, source="localStorage"):
                                    break
                    except Exception:
                        pass

                # Jika sudah login dan bukan di halaman login, kunjungi halaman saham agar API call terpicu
                if not captured_auth["header"] and ("login" not in current_url and "register" not in current_url):
                    if f"/symbol/{ticker}".lower() not in current_url:
                        try:
                            page.goto(f"https://stockbit.com/symbol/{ticker}", wait_until="domcontentloaded", timeout=30000)
                        except Exception:
                            pass
        finally:
            context.close()

    auth_header = captured_auth["header"]
    if not auth_header:
        if not interactive:
            print(
                "[SYNC] Sesi browser di host belum memiliki Access Token aktif.\n"
                "[SYNC] Jalankan mode interaktif untuk login di browser:\n"
                "  .\\.venv\\Scripts\\python -m capture.sync_session --interactive"
            )
        else:
            print("[SYNC] Waktu tunggu habis (300 detik) atau jendela ditutup sebelum login berhasil.")
        return None

    upsert_auth_header("stockbit", auth_header)
    print(f"[SYNC] BERHASIL! Access Token baru telah disinkronkan ke staging.cfg_auth.")
    return auth_header


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync persistent Stockbit browser session JWT into staging.cfg_auth"
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Open visible browser GUI to log in manually (supports 2FA/OTP/CAPTCHA)",
    )
    parser.add_argument(
        "--profile-dir",
        default=None,
        help="Persistent browser user data directory (default: ~/.stockbit_session)",
    )
    parser.add_argument(
        "--ticker",
        default="BBCA",
        help="Target stock ticker page used to trigger exodus.stockbit.com requests",
    )
    args = parser.parse_args()

    token = sync_stockbit_session(
        interactive=args.interactive,
        profile_dir=args.profile_dir,
        ticker=args.ticker,
    )
    if not token:
        sys.exit(1)


if __name__ == "__main__":
    main()
