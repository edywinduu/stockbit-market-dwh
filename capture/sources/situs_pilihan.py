from capture.sources.base import BaseSource


class SitusPilihanSource(BaseSource):
    """Adapter sumber data; isi selector/endpoint hasil analisis DevTools di sini."""

    def login(self):
        # TODO: Implementasikan login bila sumber membutuhkan autentikasi
        return None

    def get_orderbook(self, ticker: str) -> list[dict]:
        raise NotImplementedError(f"get_orderbook belum diimplementasikan untuk {ticker}")

    def get_broksum(self, ticker: str, trade_date) -> list[dict]:
        raise NotImplementedError(f"get_broksum belum diimplementasikan untuk {ticker}")
