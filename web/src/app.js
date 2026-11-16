require('dotenv').config();
const path = require('path');
const express = require('express');
const expressLayouts = require('express-ejs-layouts');
const routes = require('./routes');

const app = express();
const PORT = Number(process.env.PORT || 3000);

app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));
app.set('layout', 'layout');

app.use(expressLayouts);
app.use(express.urlencoded({ extended: true }));
app.use(express.json());
app.use('/', routes);

app.use((err, req, res, _next) => {
  console.error(err);
  res.status(500).send(`Terjadi kesalahan: ${err.message}`);
});

app.listen(PORT, () => {
  console.log(`Web app berjalan di http://localhost:${PORT}`);
});
