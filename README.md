# Stockbit Market Data Capture & Data Warehouse (`UAS_SAHAM`)

Sistem pipeline data otomatis untuk menarik data *Order Book* dan *Broker Summary* saham Bursa Efek Indonesia (BEI) ke lapisan *Staging*, memprosesnya melalui ETL menjadi skema bintang *Data Warehouse*, serta memantaunya lewat dashboard web. Proyek ini menggabungkan **Persistent Session & Token Synchronization** di host dengan **Direct HTTP Ingestion** berkecepatan tinggi di container sehingga bebas dari kegagalan CAPTCHA/2FA headless dan kedaluwarsa token JWT 24 jam.

---

## Fitur Utama

- **Automated Data Capture & Scheduler:** Penjadwalan otomatis di hari kerja bursa untuk menangkap snapshot *Order Book* (15:45 WIB) dan *Broker Summary* (16:15 WIB) melalui Direct HTTP Request yang cepat.
- **Persistent Session & Token Synchronization:** Menggunakan skrip Playwright di mesin host (`capture/sync_session.py`) dengan profil persisten (`~/.stockbit_session`) untuk menangani login/2FA sekali lewat GUI (`--interactive`) dan menyinkronkan token sesi JWT terbaru secara otomatis ke tabel `staging.cfg_auth`.
- **Two-Layer Architecture (Staging & Star Schema DWH):** Memisahkan data mentah (*raw*) di schema `staging` dari data analitik bersih yang terstruktur (`dim_date`, `dim_stock`, `dim_broker`, `fact_broker_summary`, `fact_orderbook`, `v_orderbook_summary`) di schema `dwh`.
- **SQL-Based ETL Pipeline:** Transformasi data mentah menjadi fakta dan dimensi yang dapat dijalankan sekali klik dari antarmuka web maupun secara manual.
- **Web Monitoring Dashboard:** Dashboard berbasis Express.js untuk memantau log eksekusi capture, memeriksa data mentah di staging, memicu ETL, dan meninjau ringkasan Data Warehouse.

---

## Tech Stack

- **Data Capture & Scheduler (Container):** Python 3.11 (`requests`, `psycopg2-binary`, `schedule`, `python-dotenv`)
- **Host Session Sync:** Python 3.12 (`.venv` Windows native, terisolasi dari MSYS2) + Playwright (`launch_persistent_context`)
- **Database & DWH:** PostgreSQL 16 (`staging` & `dwh` schemas, termasuk `staging.cfg_auth`)
- **Web Dashboard:** Node.js, Express.js, EJS
- **Infrastructure:** Docker & Docker Compose

---

## Cara Menjalankan Proyek

### Prasyarat (Prerequisites)

- **Docker** & **Docker Compose** (pastikan Docker Desktop berjalan)
- **Git**
- **Python 3.12 native Windows** (melalui `py -3.12`) untuk menjalankan host session sync di `.venv` tanpa bentrok dengan MSYS2.

### Instalasi

1. Clone repositori dan masuk ke direktori proyek:
   ```bash
   git clone <url-repositori-anda>
   cd UAS_SAHAM
   ```

2. Buat atau sesuaikan file `.env` di root proyek:
   ```env
   DB_HOST=db
   DB_PORT=5432
   DB_NAME=dwh_saham
   DB_USER=postgres
   DB_PASS=postgres

   # Fallback token opsional jika staging.cfg_auth belum terisi
   STOCKBIT_TOKEN=
   ```

3. Buat virtual environment `.venv` dengan Python 3.12 native (menghindari bentrok MSYS2) dan instal dependensi host:
   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\python -m pip install --upgrade pip
   .\.venv\Scripts\python -m pip install requests==2.31.0 psycopg2-binary==2.9.9 python-dotenv==1.0.1 schedule==1.2.1 playwright
   .\.venv\Scripts\playwright install chromium
   ```

### Menjalankan Aplikasi

1. Build dan nyalakan seluruh container (`db`, `capture`, dan `web`):
   ```bash
   docker compose up -d --build
   ```

2. Lakukan login interaktif sekali di host (mendukung 2FA/OTP/CAPTCHA) agar sesi browser tersimpan dan token aktif tersinkronisasi ke `staging.cfg_auth`:
   ```powershell
   .\.venv\Scripts\python -m capture.sync_session --interactive
   ```

3. Akses Web Dashboard di browser melalui:
   ```text
   http://localhost:3000
   ```

---

## Penggunaan & Struktur Direktori

### Cara Penggunaan (CLI)

```powershell
# Sinkronisasi ulang token JWT secara headless di host menggunakan sesi tersimpan
.\.venv\Scripts\python -m capture.sync_session
# (atau via wrapper)
.\.venv\Scripts\python scripts\sync_auth.py

# Tarik Order Book untuk satu emiten (menggunakan token dari staging.cfg_auth)
docker compose exec capture python -m capture.main orderbook --ticker BBCA --trigger MANUAL

# Tarik Broker Summary untuk semua emiten aktif
docker compose exec capture python -m capture.main broksum --trigger MANUAL
```

### Struktur Direktori

```text
UAS_SAHAM/
├── .venv/                    # Virtual environment Python 3.12 native di host (diabaikan git)
├── capture/                  # Worker Python, scheduler, & session sync
│   ├── main.py               # Direct HTTP capture engine (baca token dari staging.cfg_auth)
│   ├── scheduler.py          # Penjadwal harian (15:45 Orderbook & 16:15 Broksum)
│   ├── sync_session.py       # Playwright persistent session sync (--interactive / headless)
│   └── db.py                 # Helper koneksi & query PostgreSQL
├── database/                 # Skrip inisialisasi DDL, seed, & pipeline ETL
│   ├── schema/
│   │   └── 01_cfg_auth.sql   # DDL persisten untuk staging.cfg_auth
│   ├── 01_staging.sql        # Skema staging (cfg_stock, cfg_auth, ref_holiday, *_raw, logs)
│   ├── 02_dwh.sql            # Skema Star Schema DWH & view v_orderbook_summary
│   ├── 03_seed.sql           # Data awal saham, kalender 2026, libur bursa, & broker
│   └── etl/                  # Skrip SQL transformasi Staging -> DWH
├── web/                      # Aplikasi Web Dashboard (Node.js + Express + EJS)
├── scripts/                  # Skrip pembantu eksekusi worker & wrapper sync_auth.py
└── docker-compose.yml        # Orkestrasi container db, capture, & web
```

---

## Tim Pengembang / Kontributor

| Nama | NIM | Kelas |
| :--- | :--- | :--- |
| I Kadek Edy Windu Saputra | 2505551017 | Pangkalan Data (D) |
