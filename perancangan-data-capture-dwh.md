# Perancangan Data Capture Order Book & Broksum → Data Warehouse

**Mata kuliah:** Data Warehouse  
**Tugas:** Data Capture dari 1 sumber yang belum memiliki akses langsung (Order Book & Broker Summary saham), dilakukan 1x sehari pada sore hari saat/sebelum market tutup, lalu dibawa ke Data Warehouse.  
**Keluaran:** Mini aplikasi web untuk memantau data mentah hasil capture di staging, memicu pipeline ETL, dan memverifikasi data di Data Warehouse.

---

## 1. Gambaran Umum

Sistem dirancang dengan arsitektur dua lapis (*two-layer architecture*): **Staging Schema** dan **Data Warehouse Star Schema**, dipadukan dengan pola **Persistent Session & Token Synchronization** di host dan **Direct HTTP Ingestion** di container.

```
[Host Machine (.venv Python 3.12 + Playwright)]
   └─ sync_session.py (--interactive sekali / headless harian)
         │  intercept Authorization Bearer JWT dari exodus.stockbit.com
         ▼
[PostgreSQL: staging.cfg_auth]  ← menyimpan auth_header aktif provider 'stockbit'

[Scheduler Container (python -m capture.scheduler)]
   ├─ 15:45 WIB → Capture Order Book (Direct HTTP Request cepat)
   └─ 16:15 WIB → Capture Broker Summary (Direct HTTP Request cepat)
         │  baca token dinamis dari staging.cfg_auth (fallback: .env STOCKBIT_TOKEN)
         ▼
[PostgreSQL: Schema staging]    ← data mentah apa adanya (*_raw) + capture_log & etl_log
         │
         ▼
[Web App Node.js / Express]     ← pemantauan data mentah, audit log, tombol "Kirim ke DWH"
         │
         ▼
[Pipeline ETL SQL]              ← membersihkan angka, standarisasi tipe data, upsert dimensi & fakta
         │
         ▼
[PostgreSQL: Schema dwh]        ← Star schema analitik (dim_date, dim_stock, dim_broker, fact_*)
```

**Prinsip Utama:**
1. **Raw in Staging:** Data mentah disimpan apa adanya sebagai teks (`VARCHAR`) di schema `staging` tanpa transformasi mendalam agar data otentik dan proses dapat diaudit ulang.
2. **Persistent Session & Token Sync (Host) + Direct HTTP (Container):** Login interaktif (yang sering memerlukan CAPTCHA/2FA/OTP) ditangani sekali di host melalui Playwright `launch_persistent_context` (`~/.stockbit_session`) dan disinkronkan ke `staging.cfg_auth`. Worker di dalam container tetap ringan tanpa browser automation dan menarik data puluhan saham secepat kilat menggunakan `requests`.
3. **Auditability & Idempotency:** Seluruh batch penarikan dicatat di `staging.capture_log` dan eksekusi ETL dicatat di `staging.etl_log`. Query menggunakan `ON CONFLICT` sehingga aman dijalankan berulang (*idempotent*).

---

## 2. Keputusan Stack

| Bagian | Teknologi | Alasan Pemilihan |
|---|---|---|
| **Data Capture (Container)** | Python 3.11 (`requests`) | Direct HTTP request ke endpoint JSON internal, jauh lebih cepat dan ringan dibanding browser automation di dalam container. |
| **Session Sync (Host)** | Python 3.12 (`.venv` native) + Playwright | Menangani login/2FA/OTP secara interaktif sekali (`--interactive`) pada profil persisten `~/.stockbit_session` dan menyinkronkan JWT baru ke `staging.cfg_auth` tanpa bentrok MSYS2. |
| **Database** | PostgreSQL 16 (Schema `staging` & `dwh`) | Standar industri enterprise, mendukung multi-schema terisolasi, penyimpanan token terpusat (`staging.cfg_auth`), dan upsert `ON CONFLICT`. |
| **ETL Engine** | Skrip SQL Prosedural (`database/etl/*.sql`) | Transformasi transparan, berperforma tinggi di dalam database engine, mudah diuji dan diaudit. |
| **Web Dashboard** | Node.js + Express.js + EJS + DataTables | Antarmuka interaktif server-rendered yang ringan untuk memantau data mentah, status job, dan memicu ETL. |
| **Scheduler** | Python `schedule` (`python -m capture.scheduler`) | Menjamin ketepatan waktu eksekusi otomatis sesuai jam bursa Indonesia (WIB). |
| **Orchestration** | Docker & Docker Compose | Seluruh komponen (`db`, `capture`, `web`) terisolasi dan terhubung di jaringan `dwh_network`. |

---

## 3. Data yang Di-capture

### A. Order Book (Snapshot Pasar Mendekati Tutup)
- **Karakteristik:** Snapshot kedalaman antrean permintaan beli (*Bid*) dan penawaran jual (*Offer/Ask*).
- **Atribut:** `ticker`, `captured_at`, `side` ('B'/'O'), `level` (1 s/d 10), `price_raw`, `lot_raw`, `freq_raw`.
- **Tujuan Analisis:** Mengukur likuiditas saham, ketebalan antrean pasar, dan spread harga saat menjelang penutupan pasar.

### B. Broker Summary / Broksum (Kumulatif Perdagangan Harian)
- **Karakteristik:** Ringkasan akumulasi dan distribusi per broker untuk setiap saham per tanggal bursa.
- **Atribut:** `ticker`, `trade_date`, `broker_code`, `buy_lot_raw`, `buy_val_raw`, `buy_avg_raw`, `sell_lot_raw`, `sell_val_raw`, `sell_avg_raw`.
- **Tujuan Analisis:** Analisis *Bandarmologi* (mendeteksi akumulasi/distribusi dana asing vs lokal, sekuritas ritel vs institusi).

### C. Konfigurasi Saham Target (`staging.cfg_stock`)
Daftar saham yang di-capture tidak di-hardcode dalam program, melainkan dikonfigurasi lewat tabel `staging.cfg_stock` (contoh saham blue-chip utama: `BBCA`, `BBRI`, `BMRI`, `TLKM`, `ASII`). Flag `is_active` memudahkan penambahan atau penonaktifan emiten tanpa mengubah kode.

---

## 4. Pemilihan Sumber Data & Autentikasi

- **Sumber Terpilih:** **Stockbit Web API** (`exodus.stockbit.com`).
  - Endpoint Orderbook: `https://exodus.stockbit.com/company-price-feed/v2/orderbook/companies/{ticker}`
  - Endpoint Broker Summary: `https://exodus.stockbit.com/marketdetectors/{ticker}`
- **Tantangan Keamanan:** Endpoint diproteksi oleh Authorization Bearer Token JWT dengan masa berlaku **24 jam**, serta gerbang login dapat memicu CAPTCHA/OTP/2FA bila dilakukan via container headless murni.
- **Solusi Arsitektur (Persistent Session & Token Sync):**
  - Skrip `capture/sync_session.py` dijalankan di host menggunakan Playwright `launch_persistent_context` pada direktori `~/.stockbit_session`.
  - Pengguna login sekali melalui GUI (`.\.venv\Scripts\python -m capture.sync_session --interactive`), menyelesaikan OTP/2FA/CAPTCHA secara normal, lalu sesi persisten tersimpan di host.
  - Pada sinkronisasi otomatis berikutnya (`.\.venv\Scripts\python -m capture.sync_session`), Playwright membuka `https://stockbit.com/symbol/BBCA` secara headless memakai sesi persisten tersebut, mencegat header `Authorization: Bearer ...` ke `exodus.stockbit.com`, dan melakukan `UPSERT` ke `staging.cfg_auth`.
  - Di sisi container, `capture/main.py` membaca `auth_header` aktif secara dinamis dari `staging.cfg_auth` (dengan fallback ke `os.getenv("STOCKBIT_TOKEN")` bila kosong).

---

## 5. Jadwal Capture

| Job | Waktu (WIB) | Frekuensi | Deskripsi & Alasan |
|---|---|---|---|
| **Host Session Sync** | Sebelum 15:45 *(opsional Task Scheduler host)* | Senin – Jumat | Menyinkronkan token sesi aktif dari `~/.stockbit_session` ke `staging.cfg_auth`. |
| **Order Book** | 15:45 | Senin – Jumat | Menangkap snapshot kedalaman antrean orderbook menjelang penutupan sesi reguler bursa. |
| **Broker Summary** | 16:15 | Senin – Jumat | Menarik rekapan broker summary harian setelah seluruh transaksi pasar BEI selesai dicatat. |

> **Catatan Kalender:** Hari Sabtu, Minggu, serta hari libur nasional bursa (dikonfigurasi pada `staging.ref_holiday`) secara otomatis dilewati (*SKIPPED*) oleh modul pengecekan hari bursa di `capture/main.py` & `capture/utils/calendar.py`.

---

## 6. Struktur Direktori Proyek

```text
UAS_SAHAM/
├── .env                         # Konfigurasi database & fallback STOCKBIT_TOKEN
├── .gitignore                   # Mengabaikan .env, .venv/, venv/, __pycache__/
├── .venv/                       # Virtual environment Python 3.12 native (Playwright host)
├── docker-compose.yml           # Definisi service db, capture, dan web
├── README.md                    # Dokumentasi panduan operasional proyek
│
├── database/                    # Skema Database & Pipeline Data
│   ├── schema/
│   │   └── 01_cfg_auth.sql      # DDL persisten staging.cfg_auth (di-mount ke initdb)
│   ├── 01_staging.sql           # DDL schema staging, cfg_auth, tabel raw, audit log, & parse_numeric
│   ├── 02_dwh.sql               # DDL schema dwh (Star Schema) & view v_orderbook_summary
│   ├── 03_seed.sql              # Inisialisasi saham, kalender 2026, libur bursa, & broker
│   └── etl/                     # Pipeline SQL transformasi data
│       ├── 10_load_dim_saham.sql
│       ├── 11_load_dim_broker.sql
│       ├── 20_load_fact_broksum.sql
│       └── 21_load_fact_orderbook.sql
│
├── capture/                     # Data Ingestion Engine & Session Sync
│   ├── Dockerfile               # Image ringan capture (Python 3.11 + requests/psycopg2/schedule)
│   ├── requirements.txt         # Dependensi runtime container (+ catatan playwright untuk host)
│   ├── main.py                  # CLI engine: direct HTTP orderbook & broksum via staging.cfg_auth
│   ├── scheduler.py             # Penjadwal otomatis (15:45 & 16:15 WIB)
│   ├── sync_session.py          # Host Playwright persistent context sync ke staging.cfg_auth
│   ├── db.py                    # Helper koneksi & query PostgreSQL
│   └── utils/
│       ├── calendar.py          # Logika pengecekan hari kerja bursa
│       └── logger.py            # Logger audit capture
│
├── web/                         # Mini Web App (Node.js 20 + Express)
│   ├── Dockerfile
│   ├── package.json
│   └── src/
│       ├── app.js               # Entrypoint Express server
│       ├── config/db.js         # PostgreSQL connection pool
│       ├── routes/index.js      # Endpoint routing halaman & trigger ETL
│       ├── services/
│       │   ├── stagingService.js# Service baca data mentah staging & DWH
│       │   └── etlService.js    # Runner transaksi eksekusi file database/etl/*.sql
│       └── views/               # Tampilan EJS (dashboard, orderbook, broksum, log, dwh)
│
└── scripts/                     # Script pembantu CLI
    ├── sync_auth.py             # Wrapper host untuk capture.sync_session
    ├── run_orderbook.sh
    └── run_broksum.sh
```

---

## 7. Skema Staging (`database/01_staging.sql` & `database/schema/01_cfg_auth.sql`)

Seluruh tabel dan atribut pada skema staging telah distandarkan menggunakan bahasa Inggris (*snake_case*):

```sql
CREATE SCHEMA IF NOT EXISTS staging;

-- 1. Tabel konfigurasi saham target
CREATE TABLE staging.cfg_stock (
  ticker        VARCHAR(10) PRIMARY KEY,
  name          VARCHAR(100),
  sector        VARCHAR(60),
  is_active     BOOLEAN DEFAULT TRUE
);

-- 1b. Tabel penyimpanan token autentikasi persisten
CREATE TABLE IF NOT EXISTS staging.cfg_auth (
  provider      VARCHAR(50) PRIMARY KEY,
  auth_header   TEXT NOT NULL,
  updated_at    TIMESTAMP DEFAULT NOW()
);

-- 2. Tabel referensi hari libur bursa
CREATE TABLE staging.ref_holiday (
  holiday_date  DATE PRIMARY KEY,
  description   VARCHAR(100)
);

-- 3. Log audit sesi penarikan data
CREATE TABLE staging.capture_log (
  capture_id    BIGSERIAL PRIMARY KEY,
  capture_type  VARCHAR(20) NOT NULL,           -- orderbook | broksum
  ticker        VARCHAR(10),
  started_at    TIMESTAMP NOT NULL,
  finished_at   TIMESTAMP,
  status        VARCHAR(10) NOT NULL,           -- RUNNING | SUCCESS | FAILED | SKIPPED
  row_count     INT DEFAULT 0,
  error_message TEXT,
  triggered_by  VARCHAR(10) DEFAULT 'SCHEDULER' -- SCHEDULER | MANUAL
);

-- 4. Log audit pipeline ETL
CREATE TABLE staging.etl_log (
  etl_id        BIGSERIAL PRIMARY KEY,
  executed_at   TIMESTAMP NOT NULL DEFAULT NOW(),
  status        VARCHAR(10) NOT NULL,           -- SUCCESS | FAILED
  description   TEXT
);

-- 5. Helper function pembersih teks numerik mentah
CREATE OR REPLACE FUNCTION staging.parse_numeric(val TEXT)
RETURNS NUMERIC AS $$
BEGIN
  IF val IS NULL OR TRIM(val) = '' THEN RETURN NULL; END IF;
  RETURN REPLACE(REPLACE(TRIM(val), ',', ''), ' ', '')::NUMERIC;
EXCEPTION WHEN OTHERS THEN
  RETURN NULL;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- 6. Tabel data mentah orderbook
CREATE TABLE staging.orderbook_raw (
  id            BIGSERIAL PRIMARY KEY,
  capture_id    BIGINT REFERENCES staging.capture_log(capture_id),
  ticker        VARCHAR(10) NOT NULL,
  captured_at   TIMESTAMP NOT NULL,
  side          CHAR(1) NOT NULL,                 -- B (bid) | O (offer)
  level         SMALLINT NOT NULL,
  price_raw     VARCHAR(30),
  lot_raw       VARCHAR(30),
  freq_raw      VARCHAR(30),
  is_processed  BOOLEAN DEFAULT FALSE
);

-- 7. Tabel data mentah broker summary
CREATE TABLE staging.broksum_raw (
  id            BIGSERIAL PRIMARY KEY,
  capture_id    BIGINT REFERENCES staging.capture_log(capture_id),
  ticker        VARCHAR(10) NOT NULL,
  trade_date    DATE NOT NULL,
  broker_code   VARCHAR(5) NOT NULL,
  buy_lot_raw   VARCHAR(30), buy_val_raw   VARCHAR(30), buy_avg_raw   VARCHAR(30),
  sell_lot_raw  VARCHAR(30), sell_val_raw  VARCHAR(30), sell_avg_raw  VARCHAR(30),
  is_processed  BOOLEAN DEFAULT FALSE,
  UNIQUE (ticker, trade_date, broker_code)
);
```

---

## 8. Skema Data Warehouse (`database/02_dwh.sql`)

Model **Star Schema** dengan tabel dimensi yang kaya konteks analitik dan tabel fakta granular:

```sql
CREATE SCHEMA IF NOT EXISTS dwh;

-- 1. Dimensi Tanggal (di-generate otomatis untuk seluruh tahun)
CREATE TABLE dwh.dim_date (
  date_key        INT PRIMARY KEY,                 -- YYYYMMDD (contoh: 20261116)
  calendar_date   DATE UNIQUE NOT NULL,
  day_name        VARCHAR(10),
  month_number    SMALLINT,
  month_name      VARCHAR(15),
  quarter         SMALLINT,
  year            SMALLINT,
  is_trading_day  BOOLEAN
);

-- 2. Dimensi Emiten Saham
CREATE TABLE dwh.dim_stock (
  stock_key       SERIAL PRIMARY KEY,
  ticker          VARCHAR(10) UNIQUE NOT NULL,
  name            VARCHAR(100),
  sector          VARCHAR(60)
);

-- 3. Dimensi Perusahaan Sekuritas / Broker
CREATE TABLE dwh.dim_broker (
  broker_key      SERIAL PRIMARY KEY,
  broker_code     VARCHAR(5) UNIQUE NOT NULL,
  broker_name     VARCHAR(100),
  broker_type     VARCHAR(20)                      -- FOREIGN | DOMESTIC | STATE_OWNED | UNKNOWN
);

-- 4. Tabel Fakta Broker Summary Harian
CREATE TABLE dwh.fact_broker_summary (
  date_key        INT REFERENCES dwh.dim_date(date_key),
  stock_key       INT REFERENCES dwh.dim_stock(stock_key),
  broker_key      INT REFERENCES dwh.dim_broker(broker_key),
  buy_lot         BIGINT,
  buy_value       NUMERIC(20,2),
  buy_avg_price   NUMERIC(14,2),
  sell_lot        BIGINT,
  sell_value      NUMERIC(20,2),
  sell_avg_price  NUMERIC(14,2),
  net_lot         BIGINT,                          -- buy_lot - sell_lot
  net_value       NUMERIC(20,2),                   -- buy_value - sell_value
  PRIMARY KEY (date_key, stock_key, broker_key)
);

-- 5. Tabel Fakta Orderbook Snapshot
CREATE TABLE dwh.fact_orderbook (
  date_key        INT REFERENCES dwh.dim_date(date_key),
  stock_key       INT REFERENCES dwh.dim_stock(stock_key),
  capture_time    TIME,
  side            CHAR(1),                         -- B (bid) | O (offer)
  level           SMALLINT,
  price           NUMERIC(14,2),
  lot             BIGINT,
  frequency       INT,
  PRIMARY KEY (date_key, stock_key, side, level)
);

-- 6. View Analisis Likuiditas & Spread Orderbook Siap Pakai
CREATE VIEW dwh.v_orderbook_summary AS
SELECT 
  date_key, 
  stock_key,
  SUM(lot) FILTER (WHERE side = 'B') AS total_bid_lot,
  SUM(lot) FILTER (WHERE side = 'O') AS total_offer_lot,
  MIN(price) FILTER (WHERE side = 'O' AND level = 1)
    - MAX(price) FILTER (WHERE side = 'B' AND level = 1) AS spread
FROM dwh.fact_orderbook 
GROUP BY date_key, stock_key;
```

---

## 9. Pipeline ETL (`database/etl/`)

Pipeline ETL dieksekusi secara transaksional (`BEGIN ... COMMIT`) oleh modul `web/src/services/etlService.js` dengan urutan file:

1. **`10_load_dim_saham.sql`:** Sinkronisasi profil emiten dari `staging.cfg_stock` ke `dwh.dim_stock`.
2. **`11_load_dim_broker.sql`:** Deteksi otomatis dan pendaftaran kode broker baru yang muncul di transaksi hari berjalan ke `dwh.dim_broker`.
3. **`20_load_fact_broksum.sql`:** Konversi tipe data mentah menggunakan `staging.parse_numeric()`, kalkulasi `net_lot` dan `net_value`, insert ke `dwh.fact_broker_summary`, dan update flag staging `is_processed = TRUE`.
4. **`21_load_fact_orderbook.sql`:** Ekstraksi level antrean valid, deduplikasi snapshot terbaru per level, insert ke `dwh.fact_orderbook`, dan update flag `is_processed = TRUE`.

Hasil akhir seluruh batch otomatis dicatat ke dalam tabel `staging.etl_log`.

---

## 10. Desain Aplikasi Web Pemantau (Node.js)

Aplikasi web berfungsi sebagai konsol visual pemantauan dan kontrol:

- **Dashboard (`GET /`):** Kartu status capture terakhir, metrik baris staging yang belum diproses (*pending*), jumlah error 7 hari terakhir, dan tombol pemicu ETL manual (**"Kirim ke DWH"**).
- **Order Book Viewer (`GET /orderbook`):** Penampil data snapshot staging dengan filter kode ticker dan tanggal kalender.
- **Broker Summary Viewer (`GET /broksum`):** Penampil detail transaksi broker mentah dengan fitur filtering dan penanda status pemrosesan.
- **Log Monitor (`GET /log`):** Tabel audit penarikan data yang menampilkan waktu mulai, waktu selesai, status (`SUCCESS`/`FAILED`), jumlah baris, dan pesan error jika ada.
- **Data Warehouse Viewer (`GET /dwh`):** Tampilan verifikasi data bersih yang telah dimuat ke `fact_broker_summary` dan metrik likuiditas/spread dari `v_orderbook_summary`.
- **ETL Trigger (`POST /etl/run`):** Menjalankan file SQL ETL secara terurut dalam satu koneksi transaksi dan mencatat lognya.

---

## 11. Pengujian dan Validasi

| Skenario Pengujian | Metode Verifikasi | Ekspektasi Hasil |
|---|---|---|
| **Login Interaktif & Sync Token** | Eksekusi `.\.venv\Scripts\python -m capture.sync_session --interactive` | Browser menyimpan sesi di `~/.stockbit_session` dan token `stockbit` tersimpan di `staging.cfg_auth`. |
| **Headless Token Sync** | Eksekusi `.\.venv\Scripts\python -m capture.sync_session` | Token sesi aktif terbaru otomatis ter-upsert ke `staging.cfg_auth` tanpa GUI. |
| **Penarikan Orderbook** | Eksekusi `docker compose exec capture python -m capture.main orderbook --ticker BBCA` | Log `[AUTH] Loaded active token...`, 20 baris antrean (10 bid & 10 offer) tersimpan di `orderbook_raw`, status `SUCCESS` di `capture_log`. |
| **Penarikan Broker Summary** | Eksekusi `docker compose exec capture python -m capture.main broksum --ticker BBCA` | Seluruh transaksi broker tersimpan di `broksum_raw` tanpa duplikasi (`ON CONFLICT`). |
| **Idempotensi Capture Ulang** | Menjalankan capture broksum emiten yang sama dua kali pada hari yang sama | Baris tidak bertambah ganda, melainkan melakukan update data terbaru. |
| **Filter Hari Libur** | Menjalankan capture saat hari libur yang terdaftar di `ref_holiday` | Status tercatat `SKIPPED` dengan alasan `'Market Holiday'` tanpa mengirim request ke bursa. |
| **Eksekusi ETL ke DWH** | Klik tombol *Kirim ke DWH* di Web UI | Seluruh baris pending berubah menjadi `is_processed = TRUE`, fakta DWH terisi, dan `etl_log` berstatus `SUCCESS`. |

---

## 12. Deliverable Akhir Proyek

1. **Dokumen Perancangan Arsitektur (File ini):** Spesifikasi teknis menyeluruh, arsitektur data, kamus data, dan alur integrasi.
2. **Database DDL & ETL Scripts:** File `database/schema/01_cfg_auth.sql`, `01_staging.sql`, `02_dwh.sql`, `03_seed.sql`, dan rangkaian script di folder `database/etl/`.
3. **Automated Ingestion & Session Sync Engine:** Modul Python capture (`main.py`, `scheduler.py`) dan Playwright persistent session sync (`sync_session.py`, `scripts/sync_auth.py`).
4. **Web Monitoring Application:** Aplikasi web Express.js untuk inspeksi staging dan trigger ETL.
5. **Konfigurasi Lingkungan:** `docker-compose.yml`, `Dockerfile`, `.venv` host setup, dan `README.md` siap pakai.
