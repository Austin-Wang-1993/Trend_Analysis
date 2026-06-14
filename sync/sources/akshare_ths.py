from __future__ import annotations

from datetime import date

import akshare as ak
import pandas as pd

from core.utils import normalize_stock_code, parse_money_yuan, parse_percent, safe_float
from sync.sources.base import FundFlowSource
from sync.sources.retry import call_with_retry


class TongHuaShunSource(FundFlowSource):
    name = "tonghuashun"

    def fetch_market(self, trade_date: date | None = None) -> pd.DataFrame:
        stocks = self.fetch_stocks(trade_date)
        if stocks.empty:
            return pd.DataFrame()
        inflow = stocks["inflow_amount"].sum()
        outflow = stocks["outflow_amount"].sum()
        net = stocks["net_inflow"].sum()
        return pd.DataFrame(
            [
                {
                    "trade_date": trade_date,
                    "index_sh_close": None,
                    "index_sh_pct_chg": None,
                    "index_sz_close": None,
                    "index_sz_pct_chg": None,
                    "inflow_amount": inflow,
                    "outflow_amount": outflow,
                    "net_inflow": net,
                    "main_net_inflow": net,
                    "main_net_inflow_ratio": None,
                    "super_large_net_inflow": None,
                    "super_large_net_inflow_ratio": None,
                    "large_net_inflow": None,
                    "large_net_inflow_ratio": None,
                    "medium_net_inflow": None,
                    "medium_net_inflow_ratio": None,
                    "small_net_inflow": None,
                    "small_net_inflow_ratio": None,
                    "data_source": self.name,
                }
            ]
        )

    def fetch_sectors(self, sector_type: str, trade_date: date | None = None) -> pd.DataFrame:
        if sector_type == "industry":
            raw = call_with_retry(ak.stock_fund_flow_industry, symbol="即时")
            name_col = "行业"
        elif sector_type == "concept":
            raw = call_with_retry(ak.stock_fund_flow_concept, symbol="即时")
            name_col = "行业"
        else:
            return pd.DataFrame()

        rows = []
        for _, row in raw.iterrows():
            inflow = parse_money_yuan(row.get("流入资金"))
            outflow = parse_money_yuan(row.get("流出资金"))
            net = parse_money_yuan(row.get("净额"))
            rows.append(
                {
                    "trade_date": trade_date,
                    "sector_type": sector_type,
                    "sector_name": str(row[name_col]),
                    "stock_count": int(row["公司家数"]) if pd.notna(row.get("公司家数")) else None,
                    "pct_chg": parse_percent(row.get("行业-涨跌幅")),
                    "inflow_amount": inflow,
                    "outflow_amount": outflow,
                    "net_inflow": net,
                    "main_net_inflow": net,
                    "main_net_inflow_ratio": None,
                    "super_large_net_inflow": None,
                    "super_large_net_inflow_ratio": None,
                    "large_net_inflow": None,
                    "large_net_inflow_ratio": None,
                    "medium_net_inflow": None,
                    "medium_net_inflow_ratio": None,
                    "small_net_inflow": None,
                    "small_net_inflow_ratio": None,
                    "data_source": self.name,
                }
            )
        return pd.DataFrame(rows)

    def fetch_stocks(self, trade_date: date | None = None) -> pd.DataFrame:
        raw = call_with_retry(ak.stock_fund_flow_individual, symbol="即时")
        rows = []
        for _, row in raw.iterrows():
            inflow = parse_money_yuan(row.get("流入资金"))
            outflow = parse_money_yuan(row.get("流出资金"))
            net = parse_money_yuan(row.get("净额"))
            rows.append(
                {
                    "trade_date": trade_date,
                    "stock_code": normalize_stock_code(row["股票代码"]),
                    "stock_name": str(row["股票简称"]),
                    "sector_name": None,
                    "sector_type": None,
                    "price": safe_float(row.get("最新价")),
                    "pct_chg": parse_percent(row.get("涨跌幅")),
                    "turnover": parse_money_yuan(row.get("成交额")),
                    "inflow_amount": inflow,
                    "outflow_amount": outflow,
                    "net_inflow": net,
                    "main_net_inflow": net,
                    "main_net_inflow_ratio": None,
                    "super_large_net_inflow": None,
                    "super_large_net_inflow_ratio": None,
                    "large_net_inflow": None,
                    "large_net_inflow_ratio": None,
                    "medium_net_inflow": None,
                    "medium_net_inflow_ratio": None,
                    "small_net_inflow": None,
                    "small_net_inflow_ratio": None,
                    "data_source": self.name,
                }
            )
        return pd.DataFrame(rows)

    def fetch_etfs(self, trade_date: date | None = None) -> pd.DataFrame:
        from sync.sources.akshare_em import EastMoneySource

        return EastMoneySource().fetch_etfs(trade_date)
