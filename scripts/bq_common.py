"""BigQuant DAI 共享常量与查询工具。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterator

import pandas as pd
from bigquant import dai

INDUSTRY_STD = "sw2021"
# cn_stock_industry_component 表可用起始日（BigQuant 文档）
MAPPING_MIN_DATE = date(2023, 7, 5)

MAPPING_COLUMNS = [
    "trade_date",
    "stock_code",
    "stock_name",
    "industry_l1_code",
    "industry_l1_name",
    "industry_l2_code",
    "industry_l2_name",
    "industry_l3_code",
    "industry_l3_name",
    "industry_name",
]

MARKET_COLUMNS = ["trade_date", "snapshot_time", "total_turnover", "stock_count"]

INDUSTRY_COLUMNS = [
    "trade_date",
    "snapshot_time",
    "industry_l1_code",
    "industry_l1_name",
    "turnover",
    "volume",
    "stock_count",
]

STOCK_COLUMNS = [
    "trade_date",
    "snapshot_time",
    "stock_code",
    "stock_name",
    "industry_l1_code",
    "industry_l1_name",
    "turnover",
    "volume",
    "turnover_rate",
    "pct_chg",
]


def query_df(sql: str, start_date: date, end_date: date) -> pd.DataFrame:
    return dai.query(
        sql,
        filters={"date": [start_date.isoformat(), end_date.isoformat()]},
    ).df()


def normalize_mapping(df: pd.DataFrame) -> pd.DataFrame:
    renamed = df.rename(
        columns={
            "date": "trade_date",
            "instrument": "stock_code",
            "name": "stock_name",
            "industry_level1_code": "industry_l1_code",
            "industry_level1_name": "industry_l1_name",
            "industry_level2_code": "industry_l2_code",
            "industry_level2_name": "industry_l2_name",
            "industry_level3_code": "industry_l3_code",
            "industry_level3_name": "industry_l3_name",
        }
    )
    for col in MAPPING_COLUMNS:
        if col not in renamed.columns:
            renamed[col] = pd.NA
    return renamed[MAPPING_COLUMNS]


def normalize_industry(df: pd.DataFrame) -> pd.DataFrame:
    renamed = df.rename(
        columns={
            "date": "trade_date",
            "industry_level1_code": "industry_l1_code",
            "industry_level1_name": "industry_l1_name",
        }
    )
    for col in INDUSTRY_COLUMNS:
        if col not in renamed.columns and col != "snapshot_time":
            renamed[col] = pd.NA
    return renamed


def normalize_stock(df: pd.DataFrame) -> pd.DataFrame:
    renamed = df.rename(
        columns={
            "date": "trade_date",
            "instrument": "stock_code",
            "name": "stock_name",
            "amount": "turnover",
            "turn": "turnover_rate",
            "change_ratio": "pct_chg",
            "industry_level1_code": "industry_l1_code",
            "industry_level1_name": "industry_l1_name",
        }
    )
    for col in STOCK_COLUMNS:
        if col not in renamed.columns and col != "snapshot_time":
            renamed[col] = pd.NA
    return renamed


def fetch_mapping_range(start_date: date, end_date: date, with_stock_name: bool = True) -> pd.DataFrame:
    name_expr = "b.name" if with_stock_name else "NULL AS name"
    join_clause = (
        """
    LEFT JOIN cn_stock_bar1d b
      ON c.date = b.date AND c.instrument = b.instrument
    """
        if with_stock_name
        else ""
    )
    sql = f"""
    SELECT
        c.date,
        c.instrument,
        {name_expr},
        c.industry_level1_code,
        c.industry_level1_name,
        c.industry_level2_code,
        c.industry_level2_name,
        c.industry_level3_code,
        c.industry_level3_name,
        c.industry_name
    FROM cn_stock_industry_component c
    {join_clause}
    WHERE c.industry = '{INDUSTRY_STD}'
  """
    return normalize_mapping(query_df(sql, start_date, end_date))


def fetch_market_range(start_date: date, end_date: date) -> pd.DataFrame:
    sql = """
    SELECT
        date,
        SUM(amount) AS total_turnover,
        COUNT(*) AS stock_count
    FROM cn_stock_bar1d
    GROUP BY date
  """
    df = query_df(sql, start_date, end_date)
    return df.rename(columns={"date": "trade_date"})


def fetch_industry_range(start_date: date, end_date: date) -> pd.DataFrame:
    sql = f"""
    SELECT
        b.date,
        c.industry_level1_code,
        c.industry_level1_name,
        SUM(b.amount) AS turnover,
        SUM(b.volume) AS volume,
        COUNT(DISTINCT b.instrument) AS stock_count
    FROM cn_stock_bar1d b
    JOIN cn_stock_industry_component c
      ON b.date = c.date AND b.instrument = c.instrument
    WHERE c.industry = '{INDUSTRY_STD}'
    GROUP BY b.date, c.industry_level1_code, c.industry_level1_name
  """
    return normalize_industry(query_df(sql, start_date, end_date))


def fetch_stock_range(start_date: date, end_date: date) -> pd.DataFrame:
    sql = f"""
    SELECT
        b.date,
        b.instrument,
        b.name,
        b.amount,
        b.volume,
        b.turn,
        b.change_ratio,
        c.industry_level1_code,
        c.industry_level1_name
    FROM cn_stock_bar1d b
    JOIN cn_stock_industry_component c
      ON b.date = c.date AND b.instrument = c.instrument
    WHERE c.industry = '{INDUSTRY_STD}'
  """
    return normalize_stock(query_df(sql, start_date, end_date))


def month_chunks(start_date: date, end_date: date) -> Iterator[tuple[date, date]]:
    if start_date > end_date:
        return
    cursor = start_date.replace(day=1)
    while cursor <= end_date:
        if cursor.month == 12:
            month_end = date(cursor.year + 1, 1, 1)
        else:
            month_end = date(cursor.year, cursor.month + 1, 1)
        chunk_start = max(cursor, start_date)
        chunk_end = min(month_end - timedelta(days=1), end_date)
        yield chunk_start, chunk_end
        cursor = month_end
