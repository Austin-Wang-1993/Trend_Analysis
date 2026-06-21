"""v4.0 行业聚合（纯函数，可离线单测）。

输入个股当日指标 + 某体系映射 → 行业日表（含主动/主力买卖、涨跌家数及各类占比）。
口径见 docs/TUSHARE_SECTOR_DESIGN.md §3。
"""

from __future__ import annotations

import pandas as pd

UNMAPPED_CODE = "UNMAPPED"
UNMAPPED_NAME = "未分类"

# 个股可累加的金额字段
_SUM_FIELDS = ("turnover", "active_buy", "active_sell", "net_active", "main_buy", "main_sell")

SECTOR_COLUMNS = [
    "sector_code", "sector_name", "sector_path",
    "turnover", "turnover_pct",
    "active_buy", "buy_pct",
    "active_sell", "sell_pct",
    "net_active", "net_pct",
    "main_buy", "main_buy_pct",
    "main_sell", "main_sell_pct",
    "up_count", "down_count", "flat_count",
    "up_ratio", "down_ratio",
    "stock_count",
]


def aggregate_market(stock_df: pd.DataFrame) -> dict[str, float]:
    """全 A 汇总：各金额字段求和 + 成份数。供占比分母与 market_daily。"""
    out: dict[str, float] = {}
    for f in _SUM_FIELDS:
        out[f] = float(pd.to_numeric(stock_df.get(f), errors="coerce").sum()) if f in stock_df.columns else 0.0
    out["stock_count"] = int(len(stock_df))
    return out


def _safe_div(numer: pd.Series, denom: float) -> pd.Series:
    if denom in (0, 0.0) or denom is None:
        return pd.Series([None] * len(numer), index=numer.index)
    return numer / denom


def aggregate_sector(
    stock_df: pd.DataFrame,
    mapping_df: pd.DataFrame,
    catalog_df: pd.DataFrame | None = None,
    market: dict[str, float] | None = None,
    *,
    include_unmapped: bool = True,
) -> pd.DataFrame:
    """按体系映射聚合行业日表。

    - stock_df：个股当日指标（stock_code, turnover, active_buy/sell, net_active, main_buy/sell, pct_chg）
    - mapping_df：一股一行主行业（sector_code, sector_name, sector_path, stock_code）
    - catalog_df：行业目录（含零成份），保证零成交行业仍有一行
    - market：全 A 汇总（缺省则由 stock_df 现算），用于占比分母
    - include_unmapped：无归属个股是否汇总为「未分类」行
    """
    if market is None:
        market = aggregate_market(stock_df)

    present_sum = [f for f in _SUM_FIELDS if f in stock_df.columns]
    stock_slim = stock_df.copy()
    if "stock_code" in stock_slim.columns:
        stock_slim["stock_code"] = stock_slim["stock_code"].astype(str)

    if mapping_df is None or mapping_df.empty:
        merged = stock_slim.copy()
        merged["sector_code"] = UNMAPPED_CODE
        merged["sector_name"] = UNMAPPED_NAME
        merged["sector_path"] = UNMAPPED_NAME
    else:
        m = mapping_df[["sector_code", "sector_name", "sector_path", "stock_code"]].copy()
        m["stock_code"] = m["stock_code"].astype(str)
        merged = stock_slim.merge(m, on="stock_code", how="left")
        unmapped_mask = merged["sector_code"].isna()
        if include_unmapped:
            merged.loc[unmapped_mask, ["sector_code", "sector_name", "sector_path"]] = [
                UNMAPPED_CODE, UNMAPPED_NAME, UNMAPPED_NAME,
            ]
        else:
            merged = merged[~unmapped_mask]

    if "pct_chg" in merged.columns:
        pc = pd.to_numeric(merged["pct_chg"], errors="coerce")
        merged["_up"] = (pc > 0).astype(int)
        merged["_down"] = (pc < 0).astype(int)
        merged["_flat"] = ((pc == 0) | pc.isna()).astype(int)
    else:
        merged["_up"] = 0
        merged["_down"] = 0
        merged["_flat"] = 0

    agg_spec = {f: (f, "sum") for f in present_sum}
    grouped = merged.groupby(["sector_code", "sector_name", "sector_path"], as_index=False, dropna=False).agg(
        **agg_spec,
        up_count=("_up", "sum"),
        down_count=("_down", "sum"),
        flat_count=("_flat", "sum"),
        stock_count=("stock_code", "nunique"),
    )

    # catalog 左连接补零成份行业
    if catalog_df is not None and not catalog_df.empty:
        cat = catalog_df[["sector_code", "sector_name", "sector_path"]].drop_duplicates("sector_code")
        out = cat.merge(grouped, on=["sector_code", "sector_name", "sector_path"], how="outer")
    else:
        out = grouped

    for f in _SUM_FIELDS:
        out[f] = pd.to_numeric(out.get(f), errors="coerce").fillna(0.0)
    for c in ("up_count", "down_count", "flat_count", "stock_count"):
        out[c] = pd.to_numeric(out.get(c), errors="coerce").fillna(0).astype(int)

    out["turnover_pct"] = _safe_div(out["turnover"], market.get("turnover", 0.0))
    out["buy_pct"] = _safe_div(out["active_buy"], market.get("active_buy", 0.0))
    out["sell_pct"] = _safe_div(out["active_sell"], market.get("active_sell", 0.0))
    out["net_pct"] = _safe_div(out["net_active"], market.get("net_active", 0.0))
    out["main_buy_pct"] = _safe_div(out["main_buy"], market.get("main_buy", 0.0))
    out["main_sell_pct"] = _safe_div(out["main_sell"], market.get("main_sell", 0.0))

    denom = out["stock_count"].astype(float).where(out["stock_count"] > 0)  # 0 → NaN，避免除零
    out["up_ratio"] = out["up_count"] / denom
    out["down_ratio"] = out["down_count"] / denom

    for col in SECTOR_COLUMNS:
        if col not in out.columns:
            out[col] = None
    return out[SECTOR_COLUMNS].sort_values("turnover", ascending=False).reset_index(drop=True)
