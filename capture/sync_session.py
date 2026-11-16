import argparse
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
            "  pip install playwright psycopg2-binary python-dotenv\n"
            "  playwright install chromium"
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

    def on_request(request) -> None:
        if captured_auth["header"]:
            return
        if "exodus.stockbit.com" in request.url:
            headers = request.headers
            auth_val = headers.get("authorization") or headers.get("Authorization")
            if auth_val and auth_val.lower().startswith("bearer eyj"):
                captured_auth["header"] = auth_val.strip()

    target_url = "https://stockbit.com/login" if interactive else f"https://stockbit.com/symbol/{ticker}"
    wait_timeout_sec = 300 if interactive else 15

    print(f"[SYNC] Launching Playwright persistent context ({'GUI interactive' if interactive else 'headless'})...")
    print(f"[SYNC] Session directory: {session_dir}")

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
                print(
                    "[SYNC] Please complete Stockbit login (including 2FA/OTP if prompted) in the browser window.\n"
                    "[SYNC] Waiting up to 300s to intercept active Authorization Bearer token..."
                )

            deadline = time.time() + wait_timeout_sec
            while time.time() < deadline and not captured_auth["header"]:
                page.wait_for_timeout(500)
                if interactive and "login" not in page.url.lower() and not captured_auth["header"]:
                    # After interactive login redirects away from /login, ensure symbol API requests fire
                    if f"/symbol/{ticker}" not in page.url:
                        page.goto(f"https://stockbit.com/symbol/{ticker}", wait_until="domcontentloaded", timeout=30000)
        finally:
            context.close()

    auth_header = captured_auth["header"]
    if not auth_header:
        if not interactive:
            print(
                "[SYNC] No active Stockbit Authorization header intercepted in headless mode.\n"
                "[SYNC] Your session may have expired. Run with --interactive inside .venv to log in once:\n"
                "  .\\.venv\\Scripts\\python -m capture.sync_session --interactive"
            )
        else:
            print("[SYNC] Timed out waiting for Stockbit Authorization token.")
        return None

    upsert_auth_header("stockbit", auth_header)
    print(f"[SYNC] Successfully synced 'stockbit' auth_header to staging.cfg_auth (len={len(auth_header)}).")
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
