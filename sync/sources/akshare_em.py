from __future__ import annotations

from datetime import date, datetime

import akshare as ak
import pandas as pd

from core.utils import normalize_stock_code, parse_trade_date, safe_float
from sync.sources.base import FundFlowSource
from sync.sources.retry import call_with_retry


class EastMoneySource(FundFlowSource):
    name = "eastmoney"

    def fetch_market(self, trade_date: date | None = None) -> pd.DataFrame:
        raw = call_with_retry(ak.stock_market_fund_flow)
        rows = []
        for _, row in raw.iterrows():
            d = parse_trade_date(row["日期"])
            if trade_date and d != trade_date:
                continue
            inflow = None
            outflow = None
            main_net = safe_float(row.get("主力净流入-净额"))
            rows.append(
                {
                    "trade_date": d,
                    "index_sh_close": safe_float(row.get("上证-收盘价")),
                    "index_sh_pct_chg": safe_float(row.get("上证-涨跌幅")),
                    "index_sz_close": safe_float(row.get("深证-收盘价")),
                    "index_sz_pct_chg": safe_float(row.get("深证-涨跌幅")),
                    "inflow_amount": inflow,
                    "outflow_amount": outflow,
                    "net_inflow": main_net,
                    "main_net_inflow": main_net,
                    "main_net_inflow_ratio": safe_float(row.get("主力净流入-净占比")),
                    "super_large_net_inflow": safe_float(row.get("超大单净流入-净额")),
                    "super_large_net_inflow_ratio": safe_float(row.get("超大单净流入-净占比")),
                    "large_net_inflow": safe_float(row.get("大单净流入-净额")),
                    "large_net_inflow_ratio": safe_float(row.get("大单净流入-净占比")),
                    "medium_net_inflow": safe_float(row.get("中单净流入-净额")),
                    "medium_net_inflow_ratio": safe_float(row.get("中单净流入-净占比")),
                    "small_net_inflow": safe_float(row.get("小单净流入-净额")),
                    "small_net_inflow_ratio": safe_float(row.get("小单净流入-净占比")),
                    "data_source": self.name,
                }
            )
        return pd.DataFrame(rows)

    def fetch_sectors(self, sector_type: str, trade_date: date | None = None) -> pd.DataFrame:
        em_type_map = {
            "industry": "行业资金流",
            "concept": "概念资金流",
            "region": "地域资金流",
        }
        raw = call_with_retry(
            ak.stock_sector_fund_flow_rank,
            indicator="今日",
            sector_type=em_type_map[sector_type],
        )
        rows = []
        for _, row in raw.iterrows():
            main_net = safe_float(row.get("今日主力净流入-净额") or row.get("主力净流入-净额"))
            rows.append(
                {
                    "trade_date": trade_date,
                    "sector_type": sector_type,
                    "sector_name": str(row["名称"]),
                    "stock_count": None,
                    "pct_chg": safe_float(row.get("今日涨跌幅") or row.get("涨跌幅")),
                    "inflow_amount": None,
                    "outflow_amount": None,
                    "net_inflow": main_net,
                    "main_net_inflow": main_net,
                    "main_net_inflow_ratio": safe_float(
                        row.get("今日主力净流入-净占比") or row.get("主力净流入-净占比")
                    ),
                    "super_large_net_inflow": safe_float(
                        row.get("今日超大单净流入-净额") or row.get("超大单净流入-净额")
                    ),
                    "super_large_net_inflow_ratio": safe_float(
                        row.get("今日超大单净流入-净占比") or row.get("超大单净流入-净占比")
                    ),
                    "large_net_inflow": safe_float(
                        row.get("今日大单净流入-净额") or row.get("大单净流入-净额")
                    ),
                    "large_net_inflow_ratio": safe_float(
                        row.get("今日大单净流入-净占比") or row.get("大单净流入-净占比")
                    ),
                    "medium_net_inflow": safe_float(
                        row.get("今日中单净流入-净额") or row.get("中单净流入-净额")
                    ),
                    "medium_net_inflow_ratio": safe_float(
                        row.get("今日中单净流入-净占比") or row.get("中单净流入-净占比")
                    ),
                    "small_net_inflow": safe_float(
                        row.get("今日小单净流入-净额") or row.get("小单净流入-净额")
                    ),
                    "small_net_inflow_ratio": safe_float(
                        row.get("今日小单净流入-净占比") or row.get("小单净流入-净占比")
                    ),
                    "data_source": self.name,
                }
            )
        return pd.DataFrame(rows)

    def fetch_stocks(self, trade_date: date | None = None) -> pd.DataFrame:
        raw = call_with_retry(ak.stock_individual_fund_flow_rank, indicator="今日")
        rows = []
        for _, row in raw.iterrows():
            inflow = None
            outflow = None
            main_net = safe_float(row.get("今日主力净流入-净额"))
            rows.append(
                {
                    "trade_date": trade_date,
                    "stock_code": normalize_stock_code(row["代码"]),
                    "stock_name": str(row["名称"]),
                    "sector_name": None,
                    "sector_type": None,
                    "price": safe_float(row.get("最新价")),
                    "pct_chg": safe_float(row.get("今日涨跌幅")),
                    "turnover": None,
                    "inflow_amount": inflow,
                    "outflow_amount": outflow,
                    "net_inflow": main_net,
                    "main_net_inflow": main_net,
                    "main_net_inflow_ratio": safe_float(row.get("今日主力净流入-净占比")),
                    "super_large_net_inflow": safe_float(row.get("今日超大单净流入-净额")),
                    "super_large_net_inflow_ratio": safe_float(row.get("今日超大单净流入-净占比")),
                    "large_net_inflow": safe_float(row.get("今日大单净流入-净额")),
                    "large_net_inflow_ratio": safe_float(row.get("今日大单净流入-净占比")),
                    "medium_net_inflow": safe_float(row.get("今日中单净流入-净额")),
                    "medium_net_inflow_ratio": safe_float(row.get("今日中单净流入-净占比")),
                    "small_net_inflow": safe_float(row.get("今日小单净流入-净额")),
                    "small_net_inflow_ratio": safe_float(row.get("今日小单净流入-净占比")),
                    "data_source": self.name,
                }
            )
        return pd.DataFrame(rows)

    def fetch_sector_stocks(self, sector_name: str, trade_date: date | None = None) -> pd.DataFrame:
        raw = call_with_retry(
            ak.stock_sector_fund_flow_summary,
            symbol=sector_name,
            indicator="今日",
        )
        rows = []
        for _, row in raw.iterrows():
            main_net = safe_float(row.get("今日主力净流入-净额"))
            rows.append(
                {
                    "trade_date": trade_date,
                    "stock_code": normalize_stock_code(row["代码"]),
                    "stock_name": str(row["名称"]),
                    "sector_name": sector_name,
                    "sector_type": "industry",
                    "price": safe_float(row.get("最新价")),
                    "pct_chg": safe_float(row.get("今日涨跌幅")),
                    "turnover": None,
                    "inflow_amount": None,
                    "outflow_amount": None,
                    "net_inflow": main_net,
                    "main_net_inflow": main_net,
                    "main_net_inflow_ratio": safe_float(row.get("今日主力净流入-净占比")),
                    "super_large_net_inflow": safe_float(row.get("今日超大单净流入-净额")),
                    "super_large_net_inflow_ratio": safe_float(row.get("今日超大单净流入-净占比")),
                    "large_net_inflow": safe_float(row.get("今日大单净流入-净额")),
                    "large_net_inflow_ratio": safe_float(row.get("今日大单净流入-净占比")),
                    "medium_net_inflow": safe_float(row.get("今日中单净流入-净额")),
                    "medium_net_inflow_ratio": safe_float(row.get("今日中单净流入-净占比")),
                    "small_net_inflow": safe_float(row.get("今日小单净流入-净额")),
                    "small_net_inflow_ratio": safe_float(row.get("今日小单净流入-净占比")),
                    "data_source": self.name,
                }
            )
        return pd.DataFrame(rows)

    def fetch_etfs(self, trade_date: date | None = None) -> pd.DataFrame:
        raw = call_with_retry(ak.fund_etf_spot_em)
        rows = []
        for _, row in raw.iterrows():
            d = parse_trade_date(row.get("数据日期")) or trade_date
            rows.append(
                {
                    "trade_date": d,
                    "etf_code": normalize_stock_code(row["代码"]),
                    "etf_name": str(row["名称"]),
                    "price": safe_float(row.get("最新价")),
                    "pct_chg": safe_float(row.get("涨跌幅")),
                    "volume": safe_float(row.get("成交量")),
                    "turnover": safe_float(row.get("成交额")),
                    "main_net_inflow": safe_float(row.get("主力净流入-净额")),
                    "main_net_inflow_ratio": safe_float(row.get("主力净流入-净占比")),
                    "super_large_net_inflow": safe_float(row.get("超大单净流入-净额")),
                    "super_large_net_inflow_ratio": safe_float(row.get("超大单净流入-净占比")),
                    "large_net_inflow": safe_float(row.get("大单净流入-净额")),
                    "large_net_inflow_ratio": safe_float(row.get("大单净流入-净占比")),
                    "medium_net_inflow": safe_float(row.get("中单净流入-净额")),
                    "medium_net_inflow_ratio": safe_float(row.get("中单净流入-净占比")),
                    "small_net_inflow": safe_float(row.get("小单净流入-净额")),
                    "small_net_inflow_ratio": safe_float(row.get("小单净流入-净占比")),
                    "data_source": self.name,
                }
            )
        return pd.DataFrame(rows)
