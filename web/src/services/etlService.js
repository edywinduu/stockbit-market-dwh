const fs = require('fs');
const path = require('path');
const pool = require('../config/db');

const ETL_DIR = path.resolve(__dirname, '../../database/etl');

async function runEtlPipeline() {
  const files = fs.existsSync(ETL_DIR)
    ? fs.readdirSync(ETL_DIR).filter((f) => f.endsWith('.sql')).sort()
    : [];

  if (files.length === 0) {
    return { status: 'SKIP', message: 'Tidak ada file SQL di database/etl/', files: [] };
  }

  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    for (const file of files) {
      const sql = fs.readFileSync(path.join(ETL_DIR, file), 'utf8');
      await client.query(sql);
    }
    await client.query(
      `INSERT INTO staging.etl_log (status, description) VALUES ('SUCCESS', $1)`,
      [`Successfully executed: ${files.join(', ')}`]
    );
    await client.query('COMMIT');
    return { status: 'SUCCESS', message: `ETL selesai (${files.length} file).`, files };
  } catch (err) {
    await client.query('ROLLBACK');
    try {
      await pool.query(
        `INSERT INTO staging.etl_log (status, description) VALUES ('FAILED', $1)`,
        [err.message]
      );
    } catch (_) {
      // Abaikan jika gagal mencatat log error ETL
    }
    throw err;
  } finally {
    client.release();
  }
}

module.exports = { runEtlPipeline };
