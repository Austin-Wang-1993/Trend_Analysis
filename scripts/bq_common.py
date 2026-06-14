"""BigQuant DAI 共享工具：认证、行业分类、成份映射、成交额查询。"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

import pandas as pd
from bigquant import dai, init, init_from_config

CST = ZoneInfo("Asia/Shanghai")
IndustryStd = Literal["sw2021", "sw2014", "cs"]
DEFAULT_INDUSTRY: IndustryStd = "sw2021"

SECTOR_COLUMNS = [
    "industry",
    "industry_level1_code",
    "industry_level1_name",
    "industry_level2_code",
    "industry_level2_name",
    "industry_level3_code",
    "industry_level3_name",
    "industry_name",
]

MAPPING_COLUMNS = [
    "trade_date",
    "stock_code",
    "industry_std",
    "industry_name",
    "industry_l1_code",
    "industry_l1_name",
    "industry_l2_code",
    "industry_l2_name",
    "industry_l3_code",
    "industry_l3_name",
]


def ensure_auth() -> None:
    """从环境变量或 ~/.bigquant/config.json 初始化 SDK。"""
    apikey = os.environ.get("BIGQUANT_APIKEY", "").strip()
    if apikey:
        if "." not in apikey:
            raise ValueError("BIGQUANT_APIKEY 格式应为 AK.SK")
        ak, sk = apikey.split(".", 1)
        init(ak=ak, sk=sk)
        return

    ak = os.environ.get("BIGQUANT_AK", "").strip()
    sk = os.environ.get("BIGQUANT_SK", "").strip()
    if ak and sk:
        init(ak=ak, sk=sk)
        return

    init_from_config()


def _date_filter(trade_date: date) -> dict[str, list[str]]:
    d = trade_date.isoformat()
    return {"date": [d, d]}


def _recent_date_filter(days: int = 30) -> dict[str, list[str]]:
    end = datetime.now(CST).date()
    start = end - timedelta(days=days)
    return {"date": [start.isoformat(), end.isoformat()]}


def query_df(sql: str, filters: dict[str, list[str]] | None = None) -> pd.DataFrame:
    result = dai.query(sql, filters=filters)
    return result.df()


def fetch_sectors(industry: IndustryStd = DEFAULT_INDUSTRY) -> pd.DataFrame:
    """全量行业分类明细（cn_stock_industry）。"""
    sql = f"""
    SELECT DISTINCT
        industry,
        industry_level1_code,
        industry_level1_name,
        industry_level2_code,
        industry_level2_name,
        industry_level3_code,
        industry_level3_name,
        industry_name
    FROM cn_stock_industry
    WHERE industry = '{industry}'
    ORDER BY industry_level1_code, industry_level2_code, industry_level3_code
    """
    df = query_df(sql, filters=None)
    if df.empty:
        raise RuntimeError(f"cn_stock_industry 无数据（industry={industry}）")
    return df.reset_index(drop=True)


def fetch_latest_trade_date() -> date:
    """查询 cn_stock_bar1d 最近一个交易日。"""
    sql = "SELECT max(date) AS trade_date FROM cn_stock_bar1d"
    df = query_df(sql, filters=_recent_date_filter(60))
    if df.empty or pd.isna(df.loc[0, "trade_date"]):
        raise RuntimeError("无法获取最近交易日，请确认 SDK 权限与数据访问范围")
    return pd.to_datetime(df.loc[0, "trade_date"]).date()


def fetch_sector_mapping(trade_date: date, industry: IndustryStd = DEFAULT_INDUSTRY) -> pd.DataFrame:
    """指定交易日板块-个股映射（cn_stock_industry_component）。"""
    sql = f"""
    SELECT
        date,
        instrument,
        industry,
        industry_name,
        industry_level1_code,
        industry_level1_name,
        industry_level2_code,
        industry_level2_name,
        industry_level3_code,
        industry_level3_name
    FROM cn_stock_industry_component
    WHERE industry = '{industry}'
    """
    df = query_df(sql, filters=_date_filter(trade_date))
    if df.empty:
        raise RuntimeError(f"{trade_date} 无行业成份数据（industry={industry}）")

    df = df.rename(
        columns={
            "date": "trade_date",
            "instrument": "stock_code",
            "industry": "industry_std",
            "industry_level1_code": "industry_l1_code",
            "industry_level1_name": "industry_l1_name",
            "industry_level2_code": "industry_l2_code",
            "industry_level2_name": "industry_l2_name",
            "industry_level3_code": "industry_l3_code",
            "industry_level3_name": "industry_l3_name",
        }
    )
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date.astype(str)
    return df[MAPPING_COLUMNS].reset_index(drop=True)


def fetch_stock_turnover(trade_date: date) -> pd.DataFrame:
    """指定交易日全市场个股成交额（cn_stock_bar1d.amount）。"""
    sql = """
    SELECT date, instrument, name, amount, volume, turn
    FROM cn_stock_bar1d
    """
    df = query_df(sql, filters=_date_filter(trade_date))
    if df.empty:
        raise RuntimeError(f"{trade_date} 无行情数据")

    df = df.rename(
        columns={
            "date": "trade_date",
            "instrument": "stock_code",
            "name": "stock_name",
            "amount": "turnover",
            "turn": "turnover_ratio",
        }
    )
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date.astype(str)
    df["turnover"] = pd.to_numeric(df["turnover"], errors="coerce").fillna(0.0)
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")
    df["turnover_ratio"] = pd.to_numeric(df["turnover_ratio"], errors="coerce")
    return df.reset_index(drop=True)


def attach_industry(turnover_df: pd.DataFrame, mapping_df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in mapping_df.columns if c not in {"trade_date"}]
    merged = turnover_df.merge(mapping_df[cols], on="stock_code", how="left")
    return merged


def aggregate_sector_turnover(stock_df: pd.DataFrame, level: int = 1) -> pd.DataFrame:
    code_col = f"industry_l{level}_code"
    name_col = f"industry_l{level}_name"
    grouped = (
        stock_df.groupby([code_col, name_col], dropna=False)["turnover"]
        .agg(turnover="sum", stock_count="count")
        .reset_index()
    )
    grouped = grouped.rename(columns={code_col: "sector_code", name_col: "sector_name"})
    grouped = grouped[grouped["sector_code"].notna() & (grouped["sector_code"].astype(str).str.len() > 0)]
    return grouped.sort_values("turnover", ascending=False).reset_index(drop=True)


def infer_snapshot_time() -> datetime:
    return datetime.now(CST)
