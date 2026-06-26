from __future__ import annotations

from abc import ABC, abstractmethod

from src.day_trading.models import IntradayBar


class IntradayProvider(ABC):
    @abstractmethod
    def get_intraday_bars(self, symbol: str, interval: str = "5m", lookback: str = "1d") -> list[IntradayBar]:
        """Return normalized intraday bars for the requested symbol."""
