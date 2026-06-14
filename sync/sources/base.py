from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import pandas as pd


class FundFlowSource(ABC):
    name: str

    @abstractmethod
    def fetch_market(self, trade_date: date | None = None) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def fetch_sectors(self, sector_type: str, trade_date: date | None = None) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def fetch_stocks(self, trade_date: date | None = None) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def fetch_etfs(self, trade_date: date | None = None) -> pd.DataFrame:
        raise NotImplementedError

    def fetch_sector_stocks(
        self, sector_name: str, trade_date: date | None = None
    ) -> pd.DataFrame:
        return pd.DataFrame()
