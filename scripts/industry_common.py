"""四套行业映射构建与聚合（Tushare）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from sector_config import (
    DEFAULT_SECTOR_KIND,
    KIND_LABELS,
    UNMAPPED_SECTOR_CODE,
    UNMAPPED_SECTOR_NAME,
    mapping_cache_name,
)
from ts_common import ROOT, _call, get_pro, normalize_ts_code

DATA_DIR = ROOT / "data"

FLOW_SUM_COLUMNS = (
    "turnover",
    "active_buy",
    "active_sell",
    "net_active",
    "main_buy",
    "main_sell",
    "zmbtdcje",
    "zmbddcje",
    "zmbzdcje",
    "zmbxdcje",
    "zmstdcje",
    "zmsddcje",
    "zmszdcje",
    "zmsxdcje",
)


def _path_join(*parts: str) -> str:
    return " > ".join(p for p in parts if p and str(p).strip())


def build_sw_l3_mapping(pro=None) -> pd.DataFrame:
    pro = pro or get_pro()
    df = _call(pro, "index_member_all", is_new="Y")
    if df.empty:
        raise RuntimeError("申万 index_member_all 为空")
    rows = []
    for _, r in df.iterrows():
        code = str(r.get("l3_code") or "").strip()
        if not code:
            continue
        stock = normalize_ts_code(str(r.get("ts_code", "")))
        if not stock:
            continue
        rows.append(
            {
                "kind": "sw_l3",
                "sector_code": code,
                "sector_name": str(r.get("l3_name", "")).strip(),
                "sector_path": _path_join(r.get("l1_name"), r.get("l2_name"), r.get("l3_name")),
                "stock_code": stock,
            }
        )
    return pd.DataFrame(rows)


def build_ci_l3_mapping(pro=None) -> pd.DataFrame:
    pro = pro or get_pro()
    df = _call(pro, "ci_index_member", is_new="Y")
    if df.empty:
        raise RuntimeError("中信 ci_index_member 为空")
    rows = []
    for _, r in df.iterrows():
        code = str(r.get("l3_code") or "").strip()
        if not code:
            continue
        stock = normalize_ts_code(str(r.get("ts_code", "")))
        if not stock:
            continue
        rows.append(
            {
                "kind": "ci_l3",
                "sector_code": code,
                "sector_name": str(r.get("l3_name", "")).strip(),
                "sector_path": _path_join(r.get("l1_name"), r.get("l2_name"), r.get("l3_name")),
                "stock_code": stock,
            }
        )
    return pd.DataFrame(rows)


def _dc_trade_date_candidates(explicit: str | None = None) -> list[str]:
    """东财 dc_index 需有效交易日；勿用 trade_cal limit=5（易取到错误日期）。"""
    if explicit:
        return [explicit.replace("-", "")]
    from trading_calendar import get_recent_trading_days

    return [d.replace("-", "") for d in reversed(get_recent_trading_days(30))]


def _fetch_dc_index_industry(pro, trade_date: str) -> pd.DataFrame:
    """拉取东财行业板块列表，兼容 idx_type 参数与客户端过滤。"""
    idx = _call(
        pro,
        "dc_index",
        trade_date=trade_date,
        idx_type="行业板块",
        fields="ts_code,name,idx_type,level",
    )
    if idx.empty:
        raw = _call(pro, "dc_index", trade_date=trade_date, fields="ts_code,name,idx_type,level")
        if not raw.empty and "idx_type" in raw.columns:
            idx = raw[raw["idx_type"].astype(str) == "行业板块"].copy()
    if idx.empty:
        return idx
    if "level" in idx.columns:
        levels = idx["level"].astype(str).str.strip()
        if (levels != "").any():
            # 优先最细层级（常见为 L3 或数字最大）
            uniq = sorted({lv for lv in levels.unique() if lv and lv.lower() != "nan"})
            if uniq:
                finest = uniq[-1]
                finer = idx[levels == finest]
                if not finer.empty:
                    idx = finer
    return idx.drop_duplicates(subset=["ts_code"], keep="first")


def build_dc_ind_mapping(pro=None, trade_date: str | None = None) -> pd.DataFrame:
    pro = pro or get_pro()
    idx = pd.DataFrame()
    td_used = ""
    for td in _dc_trade_date_candidates(trade_date):
        idx = _fetch_dc_index_industry(pro, td)
        if not idx.empty:
            td_used = td
            break
    if idx.empty:
        cached = load_mapping_cache("dc_ind")
        if not cached.empty:
            print("    警告: dc_index 行业板块为空，回退使用本地缓存", flush=True)
            return cached
        tried = ", ".join(_dc_trade_date_candidates(trade_date)[:5])
        raise RuntimeError(
            f"东财 dc_index 行业板块为空（已尝试交易日: {tried} …）。"
            "可指定 --trade-date YYYY-MM-DD 或稍后重试"
        )
    print(f"    东财 dc_index 使用 trade_date={td_used}，板块 {len(idx)} 个", flush=True)
    rows: list[dict[str, Any]] = []
    for _, sec in idx.iterrows():
        sc = str(sec["ts_code"])
        name = str(sec["name"])
        mem = _call(pro, "dc_member", trade_date=td_used, ts_code=sc, fields="con_code")
        if mem.empty:
            # 成份接口偶发缺当日数据，再试前一交易日
            for alt in _dc_trade_date_candidates(trade_date):
                if alt == td_used:
                    continue
                mem = _call(pro, "dc_member", trade_date=alt, ts_code=sc, fields="con_code")
                if not mem.empty:
                    break
        if mem.empty:
            continue
        for _, m in mem.iterrows():
            stock = normalize_ts_code(str(m.get("con_code", "")))
            if not stock:
                continue
            rows.append(
                {
                    "kind": "dc_ind",
                    "sector_code": sc,
                    "sector_name": name,
                    "sector_path": name,
                    "stock_code": stock,
                }
            )
    if not rows:
        cached = load_mapping_cache("dc_ind")
        if not cached.empty:
            print("    警告: dc_member 成份为空，回退使用本地缓存", flush=True)
            return cached
        raise RuntimeError(f"东财 dc_member 成份为空（trade_date={td_used}）")
    return pd.DataFrame(rows)


def build_ths_ind_mapping(pro=None) -> pd.DataFrame:
    pro = pro or get_pro()
    idx = _call(pro, "ths_index", exchange="A", type="I", fields="ts_code,name")
    if idx.empty:
        raise RuntimeError("同花顺 ths_index 行业为空")
    rows: list[dict[str, Any]] = []
    for _, sec in idx.iterrows():
        sc = str(sec["ts_code"])
        name = str(sec["name"])
        mem = _call(pro, "ths_member", ts_code=sc, fields="con_code")
        if mem.empty:
            continue
        for _, m in mem.iterrows():
            stock = normalize_ts_code(str(m.get("con_code", "")))
            if not stock:
                continue
            rows.append(
                {
                    "kind": "ths_ind",
                    "sector_code": sc,
                    "sector_name": name,
                    "sector_path": name,
                    "stock_code": stock,
                }
            )
    if not rows:
        raise RuntimeError("同花顺 ths_member 成份为空")
    return pd.DataFrame(rows)


BUILDERS = {
    "sw_l3": build_sw_l3_mapping,
    "ci_l3": build_ci_l3_mapping,
    "dc_ind": build_dc_ind_mapping,
    "ths_ind": build_ths_ind_mapping,
}


def build_mapping(kind: str, pro=None, **kwargs) -> pd.DataFrame:
    from sector_config import validate_kind

    validate_kind(kind)
    return BUILDERS[kind](pro=pro, **kwargs)


def save_mapping_cache(kind: str, df: pd.DataFrame) -> Path:
    path = DATA_DIR / "cache" / mapping_cache_name(kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(df.to_json(orient="records", force_ascii=False), encoding="utf-8")
    return path


def load_mapping_cache(kind: str) -> pd.DataFrame:
    path = DATA_DIR / "cache" / mapping_cache_name(kind)
    if not path.exists():
        return pd.DataFrame()
    return pd.DataFrame(json.loads(path.read_text(encoding="utf-8")))


def sector_catalog(mapping_df: pd.DataFrame) -> pd.DataFrame:
    if mapping_df.empty:
        return pd.DataFrame(columns=["sector_code", "sector_name", "sector_path"])
    cat = (
        mapping_df[["sector_code", "sector_name", "sector_path"]]
        .drop_duplicates(subset=["sector_code"])
        .reset_index(drop=True)
    )
    return cat


def aggregate_industry_sectors(
    stock_df: pd.DataFrame,
    mapping_df: pd.DataFrame,
    catalog: pd.DataFrame,
) -> pd.DataFrame:
    """一股一行归属；catalog 保证零成交行业仍有一行。"""
    base_cols = ["sector_code", "sector_name", "sector_path"]
    catalog = catalog[base_cols].copy()
    if mapping_df.empty or stock_df.empty:
        out = catalog.copy()
        for col in FLOW_SUM_COLUMNS + ("up_count", "down_count", "flat_count", "stock_count"):
            out[col] = 0
        for col in ("up_ratio", "down_ratio", "flat_ratio"):
            out[col] = 0.0
        return out

    present = [c for c in FLOW_SUM_COLUMNS if c in stock_df.columns]
    map_df = mapping_df[["sector_code", "sector_name", "sector_path", "stock_code"]].copy()
    stock_cols = ["stock_code", "pct_chg"] + present
    stock_slim = stock_df[[c for c in stock_cols if c in stock_df.columns]].copy()
    merged = map_df.merge(stock_slim, on="stock_code", how="inner")

    if merged.empty:
        out = catalog.copy()
        for col in FLOW_SUM_COLUMNS + ("up_count", "down_count", "flat_count", "stock_count"):
            out[col] = 0
        for col in ("up_ratio", "down_ratio", "flat_ratio"):
            out[col] = 0.0
        return out

    def _count(series: pd.Series) -> int:
        return int(series.fillna(0).gt(0).sum())

    def _count_down(series: pd.Series) -> int:
        return int(series.fillna(0).lt(0).sum())

    agg_dict = {c: (c, "sum") for c in present}
    grouped = merged.groupby(["sector_code", "sector_name", "sector_path"], as_index=False).agg(
        **agg_dict,
        stock_count=("stock_code", "nunique"),
        up_count=("pct_chg", _count),
        down_count=("pct_chg", _count_down),
    )
    grouped["flat_count"] = (
        grouped["stock_count"] - grouped["up_count"] - grouped["down_count"]
    ).clip(lower=0)
    for col, num in (("up_ratio", "up_count"), ("down_ratio", "down_count"), ("flat_ratio", "flat_count")):
        grouped[col] = grouped.apply(
            lambda r, n=num: (r[n] / r["stock_count"]) if r["stock_count"] else 0.0,
            axis=1,
        )

    out = catalog.merge(grouped, on=["sector_code", "sector_name", "sector_path"], how="left")
    for col in present + ("stock_count", "up_count", "down_count", "flat_count"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)
    for col in ("up_ratio", "down_ratio", "flat_ratio"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    if "stock_count" in out.columns:
        out["stock_count"] = out["stock_count"].astype(int)
    return out.reset_index(drop=True)


def assign_unmapped(stock_df: pd.DataFrame, mapping_df: pd.DataFrame, sector_df: pd.DataFrame) -> pd.DataFrame:
    """将 mapping 未覆盖的股票计入 UNMAPPED 行。"""
    if stock_df.empty:
        return sector_df
    mapped = set(mapping_df["stock_code"].astype(str)) if not mapping_df.empty else set()
    extra = stock_df[~stock_df["stock_code"].astype(str).isin(mapped)].copy()
    if extra.empty:
        return sector_df
    present = [c for c in FLOW_SUM_COLUMNS if c in extra.columns]
    row: dict[str, Any] = {
        "sector_code": UNMAPPED_SECTOR_CODE,
        "sector_name": UNMAPPED_SECTOR_NAME,
        "sector_path": UNMAPPED_SECTOR_NAME,
        "stock_count": len(extra),
    }
    for c in present:
        row[c] = float(extra[c].fillna(0).sum())
    pct = extra["pct_chg"] if "pct_chg" in extra.columns else pd.Series(dtype=float)
    row["up_count"] = int(pct.fillna(0).gt(0).sum())
    row["down_count"] = int(pct.fillna(0).lt(0).sum())
    row["flat_count"] = max(0, row["stock_count"] - row["up_count"] - row["down_count"])
    sc = row["stock_count"] or 1
    row["up_ratio"] = row["up_count"] / sc
    row["down_ratio"] = row["down_count"] / sc
    row["flat_ratio"] = row["flat_count"] / sc
    return pd.concat([sector_df, pd.DataFrame([row])], ignore_index=True)


def display_sector_name(row: pd.Series) -> str:
    path = str(row.get("sector_path") or "").strip()
    name = str(row.get("sector_name") or "").strip()
    return path if path else name
