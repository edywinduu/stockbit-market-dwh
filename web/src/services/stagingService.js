const pool = require('../config/db');

async function getDashboardStats() {
  const [lastCapture, pendingOb, pendingBs, errors7d] = await Promise.all([
    pool.query(`
      SELECT capture_id, 
             capture_type AS jenis, 
             ticker, 
             started_at AS waktu_mulai, 
             finished_at AS waktu_selesai, 
             status, 
             row_count AS jumlah_baris
      FROM staging.capture_log
      ORDER BY started_at DESC
      LIMIT 1
    `),
    pool.query(`SELECT COUNT(*)::INT AS total FROM staging.orderbook_raw WHERE is_processed = FALSE`),
    pool.query(`SELECT COUNT(*)::INT AS total FROM staging.broksum_raw WHERE is_processed = FALSE`),
    pool.query(`
      SELECT COUNT(*)::INT AS total
      FROM staging.capture_log
      WHERE status IN ('FAILED', 'GAGAL') AND started_at >= NOW() - INTERVAL '7 days'
    `),
  ]);

  return {
    lastCapture: lastCapture.rows[0] || null,
    pendingOrderbook: pendingOb.rows[0].total,
    pendingBroksum: pendingBs.rows[0].total,
    errors7d: errors7d.rows[0].total,
  };
}

async function getOrderbook({ ticker, date }) {
  const params = [];
  const where = [];

  if (ticker) {
    params.push(ticker.toUpperCase());
    where.push(`ticker = $${params.length}`);
  }
  if (date) {
    params.push(date);
    where.push(`captured_at::DATE = $${params.length}::DATE`);
  }

  const sql = `
    SELECT id, ticker, captured_at, side, level, price_raw, lot_raw, freq_raw, is_processed AS processed
    FROM staging.orderbook_raw
    ${where.length ? 'WHERE ' + where.join(' AND ') : ''}
    ORDER BY captured_at DESC, ticker ASC, side ASC, level ASC
    LIMIT 200
  `;
  const { rows } = await pool.query(sql, params);
  return rows;
}

async function getBroksum({ ticker, date }) {
  const params = [];
  const where = [];

  if (ticker) {
    params.push(ticker.toUpperCase());
    where.push(`ticker = $${params.length}`);
  }
  if (date) {
    params.push(date);
    where.push(`trade_date = $${params.length}::DATE`);
  }

  const sql = `
    SELECT id, ticker, trade_date, broker_code,
           buy_lot_raw, buy_val_raw, buy_avg_raw,
           sell_lot_raw, sell_val_raw, sell_avg_raw, is_processed AS processed
    FROM staging.broksum_raw
    ${where.length ? 'WHERE ' + where.join(' AND ') : ''}
    ORDER BY trade_date DESC, ticker ASC, broker_code ASC
    LIMIT 300
  `;
  const { rows } = await pool.query(sql, params);
  return rows;
}

async function getCaptureLogs() {
  const { rows } = await pool.query(`
    SELECT capture_id, 
           capture_type AS jenis, 
           ticker, 
           started_at AS waktu_mulai, 
           finished_at AS waktu_selesai, 
           status, 
           row_count AS jumlah_baris, 
           error_message AS pesan_error, 
           triggered_by AS pemicu
    FROM staging.capture_log
    ORDER BY started_at DESC
    LIMIT 200
  `);
  return rows;
}

async function getDwhSummary() {
  const [broksum, orderbook] = await Promise.all([
    pool.query(`
      SELECT t.calendar_date AS tanggal, s.ticker, b.broker_code,
             f.buy_lot, f.buy_value, f.sell_lot, f.sell_value, f.net_lot, f.net_value
      FROM dwh.fact_broker_summary f
      JOIN dwh.dim_date t ON t.date_key = f.date_key
      JOIN dwh.dim_stock s ON s.stock_key = f.stock_key
      JOIN dwh.dim_broker b ON b.broker_key = f.broker_key
      ORDER BY t.calendar_date DESC, s.ticker ASC, f.net_value DESC
      LIMIT 200
    `),
    pool.query(`
      SELECT t.calendar_date AS tanggal, s.ticker, v.total_bid_lot, v.total_offer_lot, v.spread
      FROM dwh.v_orderbook_summary v
      JOIN dwh.dim_date t ON t.date_key = v.date_key
      JOIN dwh.dim_stock s ON s.stock_key = v.stock_key
      ORDER BY t.calendar_date DESC, s.ticker ASC
      LIMIT 100
    `),
  ]);

  return {
    factBroksum: broksum.rows,
    orderbookRingkas: orderbook.rows,
  };
}

module.exports = {
  getDashboardStats,
  getOrderbook,
  getBroksum,
  getCaptureLogs,
  getDwhSummary,
};
