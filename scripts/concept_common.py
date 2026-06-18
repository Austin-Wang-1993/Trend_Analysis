"""概念板块映射与聚合（必盈 hszg/list + hszg/gg）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from by_common import (
    ATOMIC_FLOW_AMOUNT_FIELDS,
    TYPE2_HOT,
    TYPE2_BOARD,
    build_sector_mapping,
    ensure_stock_codes,
    filter_sectors,
)
from sector_config import concept_mapping_cache_name

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"

FLOW_SUM_COLUMNS = (
    "turnover",
    "active_buy",
    "active_sell",
    "net_active",
    *ATOMIC_FLOW_AMOUNT_FIELDS,
)


def sectors_for_concept_type(tree_df: pd.DataFrame, concept_type: int) -> pd.DataFrame:
    if concept_type == TYPE2_HOT:
        return filter_sectors(tree_df, type2=TYPE2_HOT)
    if concept_type == TYPE2_BOARD:
        return filter_sectors(tree_df, type2=TYPE2_BOARD)
    raise ValueError(f"unsupported concept_type: {concept_type}")


def load_or_build_concept_mapping(
    licence: str,
    tree_df: pd.DataFrame,
    concept_type: int,
    *,
    refresh: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    cache_path = DATA_DIR / "cache" / concept_mapping_cache_name(concept_type)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    sectors_df = sectors_for_concept_type(tree_df, concept_type)
    if not refresh and cache_path.exists():
        mapping_df = ensure_stock_codes(pd.DataFrame(json.loads(cache_path.read_text(encoding="utf-8"))))
        return mapping_df, sectors_df
    mapping_df = ensure_stock_codes(build_sector_mapping(licence, sectors_df))
    cache_path.write_text(mapping_df.to_json(orient="records", force_ascii=False), encoding="utf-8")
    return mapping_df, sectors_df


def aggregate_concept_sectors(
    stock_df: pd.DataFrame,
    mapping_df: pd.DataFrame,
    sectors_catalog: pd.DataFrame,
) -> pd.DataFrame:
    """多标签聚合：一股可计入多个概念；sectors_catalog 保证零成交概念仍有一行。"""
    catalog = sectors_catalog[["code", "name"]].rename(columns={"code": "sector_code", "name": "sector_name"})
    if mapping_df.empty or stock_df.empty:
        out = catalog.copy()
        for col in FLOW_SUM_COLUMNS:
            out[col] = 0.0
        out["stock_count"] = 0
        return out

    present = [c for c in FLOW_SUM_COLUMNS if c in stock_df.columns]
    map_df = mapping_df[["sector_code", "sector_name", "stock_code"]].copy()
    stock_cols = ["stock_code"] + present
    stock_slim = stock_df[[c for c in stock_cols if c in stock_df.columns]].copy()
    merged = map_df.merge(stock_slim, on="stock_code", how="inner")
    if merged.empty:
        out = catalog.copy()
        for col in FLOW_SUM_COLUMNS:
            out[col] = 0.0
        out["stock_count"] = 0
        return out

    agg_dict = {c: (c, "sum") for c in present}
    grouped = merged.groupby(["sector_code", "sector_name"], as_index=False).agg(
        **agg_dict,
        stock_count=("stock_code", "nunique"),
    )
    out = catalog.merge(grouped, on=["sector_code", "sector_name"], how="left")
    for col in present:
        if col in out.columns:
            out[col] = out[col].fillna(0.0)
    if "stock_count" in out.columns:
        out["stock_count"] = out["stock_count"].fillna(0).astype(int)
    else:
        out["stock_count"] = 0
    return out.reset_index(drop=True)


def apply_turnover_pct(sector_df: pd.DataFrame, market_turnover: float) -> pd.DataFrame:
    out = sector_df.copy()
    if market_turnover > 0 and "turnover" in out.columns:
        out["turnover_pct"] = out["turnover"] / market_turnover
    else:
        out["turnover_pct"] = None
    return out
