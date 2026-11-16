from abc import ABC, abstractmethod


class BaseSource(ABC):
    @abstractmethod
    def login(self):
        """Autentikasi ke situs sumber jika diperlukan."""

    @abstractmethod
    def get_orderbook(self, ticker: str) -> list[dict]:
        """Mengembalikan list dict: side, level, price_raw, lot_raw, freq_raw."""

    @abstractmethod
    def get_broksum(self, ticker: str, trade_date) -> list[dict]:
        """Mengembalikan list dict: broker_code, buy_*_raw, sell_*_raw."""
