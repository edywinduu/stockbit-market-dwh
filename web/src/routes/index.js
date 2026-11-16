const express = require('express');
const stagingService = require('../services/stagingService');
const etlService = require('../services/etlService');

const router = express.Router();

router.get('/', async (req, res, next) => {
  try {
    const stats = await stagingService.getDashboardStats();
    res.render('dashboard', {
      title: 'Dashboard',
      stats,
      flash: req.query.msg || null,
    });
  } catch (err) {
    next(err);
  }
});

router.get('/orderbook', async (req, res, next) => {
  try {
    const filter = {
      ticker: req.query.ticker || '',
      date: req.query.date || '',
    };
    const rows = await stagingService.getOrderbook(filter);
    res.render('orderbook', { title: 'Order Book (Staging)', rows, filter });
  } catch (err) {
    next(err);
  }
});

router.get('/broksum', async (req, res, next) => {
  try {
    const filter = {
      ticker: req.query.ticker || '',
      date: req.query.date || '',
    };
    const rows = await stagingService.getBroksum(filter);
    res.render('broksum', { title: 'Broker Summary (Staging)', rows, filter });
  } catch (err) {
    next(err);
  }
});

router.get('/log', async (req, res, next) => {
  try {
    const logs = await stagingService.getCaptureLogs();
    res.render('log', { title: 'Log Capture', logs });
  } catch (err) {
    next(err);
  }
});

router.get('/dwh', async (req, res, next) => {
  try {
    const dwh = await stagingService.getDwhSummary();
    res.render('dwh', { title: 'Data Warehouse', dwh });
  } catch (err) {
    next(err);
  }
});

router.post('/etl/run', async (req, res) => {
  try {
    const result = await etlService.runEtlPipeline();
    res.redirect(`/?msg=${encodeURIComponent(result.message)}`);
  } catch (err) {
    res.redirect(`/?msg=${encodeURIComponent('ETL Gagal: ' + err.message)}`);
  }
});

module.exports = router;
