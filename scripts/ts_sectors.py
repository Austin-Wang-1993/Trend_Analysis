"""四套行业映射（v4.0）：申万三级 / 中信三级 / 东财行业 / 同花顺行业。

每套体系归一化为统一结构：
- mapping_df：`sector_code, sector_name, sector_path, stock_code`（一股一行主行业）
- catalog_df：`sector_code, sector_name, sector_path`（含零成交行业占位）

归一化函数为纯函数（可离线单测）；fetch_* 依赖 TUSHARE_TOKEN（联网）。
接口与积分见 docs/TUSHARE_API.md；历史归属局限见 docs/TUSHARE_SECTOR_DESIGN.md §4.1。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from ts_common import call_api, ts_code_to_code6

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "data" / "cache"

KINDS = ("sw_l3", "ci_l3", "dc_ind", "ths_ind")
KIND_LABELS = {
    "sw_l3": "申万三级",
    "ci_l3": "中信三级",
    "dc_ind": "东财行业",
    "ths_ind": "同花顺行业",
}

_MAPPING_COLS = ["sector_code", "sector_name", "sector_path", "stock_code"]
_CATALOG_COLS = ["sector_code", "sector_name", "sector_path"]


def _join_path(*names: Any) -> str:
    parts = [str(n).strip() for n in names if n is not None and str(n).strip() and str(n) != "nan"]
    return " > ".join(parts)


def _empty_pair() -> tuple[pd.DataFrame, pd.DataFrame]:
    return pd.DataFrame(columns=_MAPPING_COLS), pd.DataFrame(columns=_CATALOG_COLS)


# --------------------------------------------------------------------------- #
# 归一化（纯函数）
# --------------------------------------------------------------------------- #
def _normalize_l3_member(df: pd.DataFrame, code_col: str = "l3_code", name_col: str = "l3_name") -> tuple[pd.DataFrame, pd.DataFrame]:
    """申万 / 中信通用：member 表（含 l1/l2/l3 名称）→ 一股一行主行业（L3）。"""
    if df is None or df.empty:
        return _empty_pair()
    work = df.copy()
    work["stock_code"] = work["ts_code"].map(ts_code_to_code6)
    work["sector_code"] = work[code_col].astype(str)
    work["sector_name"] = work[name_col].astype(str)
    work["sector_path"] = work.apply(
        lambda r: _join_path(r.get("l1_name"), r.get("l2_name"), r.get("l3_name")), axis=1
    )
    mapping = (
        work[_MAPPING_COLS]
        .dropna(subset=["stock_code", "sector_code"])
        .drop_duplicates(subset=["stock_code"], keep="first")
        .reset_index(drop=True)
    )
    catalog = (
        work[_CATALOG_COLS]
        .drop_duplicates(subset=["sector_code"], keep="first")
        .reset_index(drop=True)
    )
    return mapping, catalog


def normalize_sw_member(df: pd.DataFrame, classify_df: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """申万 `index_member_all` → 映射 + catalog。classify_df（index_classify L3）补零成交行业。"""
    mapping, catalog = _normalize_l3_member(df, "l3_code", "l3_name")
    if classify_df is not None and not classify_df.empty:
        extra = classify_df.rename(
            columns={"index_code": "sector_code", "industry_name": "sector_name"}
        )[["sector_code", "sector_name"]].copy()
        extra["sector_code"] = extra["sector_code"].astype(str)
        extra["sector_path"] = extra["sector_name"].astype(str)
        catalog = (
            pd.concat([catalog, extra[_CATALOG_COLS]], ignore_index=True)
            .drop_duplicates(subset=["sector_code"], keep="first")
            .reset_index(drop=True)
        )
    return mapping, catalog


def normalize_ci_member(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """中信 `ci_index_member` → 映射 + catalog。"""
    return _normalize_l3_member(df, "l3_code", "l3_name")


def normalize_board_members(
    index_df: pd.DataFrame,
    members: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """东财 / 同花顺通用：板块列表 + {板块code: 成份df} → 映射 + catalog（单层，path=name）。

    index_df 需含 `ts_code`、`name`；成份 df 用 `con_code`（或 ts_code）作为成份股。
    """
    if index_df is None or index_df.empty:
        return _empty_pair()
    cat = index_df.copy()
    cat["sector_code"] = cat["ts_code"].astype(str)
    cat["sector_name"] = cat["name"].astype(str)
    cat["sector_path"] = cat["sector_name"]
    catalog = cat[_CATALOG_COLS].drop_duplicates(subset=["sector_code"], keep="first").reset_index(drop=True)
    name_map = dict(zip(catalog["sector_code"], catalog["sector_name"]))

    rows: list[dict[str, Any]] = []
    for board_code, mdf in (members or {}).items():
        if mdf is None or mdf.empty:
            continue
        con_col = "con_code" if "con_code" in mdf.columns else ("ts_code" if "ts_code" in mdf.columns else None)
        if con_col is None:
            continue
        sname = name_map.get(str(board_code), str(board_code))
        for con in mdf[con_col].dropna():
            rows.append(
                {
                    "sector_code": str(board_code),
                    "sector_name": sname,
                    "sector_path": sname,
                    "stock_code": ts_code_to_code6(con),
                }
            )
    if not rows:
        return pd.DataFrame(columns=_MAPPING_COLS), catalog
    mapping = (
        pd.DataFrame(rows)
        .drop_duplicates(subset=["stock_code"], keep="first")  # 一股一行主板块（取首个）
        .reset_index(drop=True)
    )
    return mapping, catalog


# --------------------------------------------------------------------------- #
# 联网拉取（需 TUSHARE_TOKEN）
# --------------------------------------------------------------------------- #
def fetch_sw_mapping() -> tuple[pd.DataFrame, pd.DataFrame]:
    """申万三级：按 L1 分页拉 index_member_all，避免单次 2000 行截断。"""
    classify = call_api("index_classify", level="L1", src="SW2021")
    frames: list[pd.DataFrame] = []
    if classify is not None and not classify.empty:
        code_col = "index_code" if "index_code" in classify.columns else "industry_code"
        for l1 in classify[code_col].dropna().astype(str):
            part = call_api("index_member_all", l1_code=l1, is_new="Y")
            if part is not None and not part.empty:
                frames.append(part)
    member = pd.concat(frames, ignore_index=True) if frames else call_api("index_member_all", is_new="Y")
    classify_l3 = call_api("index_classify", level="L3", src="SW2021")
    return normalize_sw_member(member, classify_l3)


def fetch_ci_mapping() -> tuple[pd.DataFrame, pd.DataFrame]:
    """中信三级：先全量拉一次，再按发现的 L1 补全（防 5000 行截断）。"""
    bulk = call_api("ci_index_member", is_new="Y")
    if bulk is None or bulk.empty:
        return _empty_pair()
    if len(bulk) < 5000:
        return normalize_ci_member(bulk)
    frames: list[pd.DataFrame] = []
    for l1 in bulk["l1_code"].dropna().astype(str).unique():
        part = call_api("ci_index_member", l1_code=l1, is_new="Y")
        if part is not None and not part.empty:
            frames.append(part)
    member = pd.concat(frames, ignore_index=True) if frames else bulk
    return normalize_ci_member(member)


def fetch_dc_mapping(trade_date: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """东财行业：dc_index(idx_type=行业板块) + 逐板块 dc_member。trade_date=YYYYMMDD。"""
    index_df = call_api("dc_index", trade_date=trade_date, idx_type="行业板块")
    if index_df is None or index_df.empty:
        return _empty_pair()
    members: dict[str, pd.DataFrame] = {}
    for board in index_df["ts_code"].dropna().astype(str):
        members[board] = call_api("dc_member", ts_code=board, trade_date=trade_date)
    return normalize_board_members(index_df, members)


def fetch_ths_mapping() -> tuple[pd.DataFrame, pd.DataFrame]:
    """同花顺行业：ths_index(type=I) + 逐指数 ths_member。

    注意：ths_member 官方文档定位「概念板块成分」，行业指数成份需实测；见设计 §4.1。
    """
    index_df = call_api("ths_index", exchange="A", type="I")
    if index_df is None or index_df.empty:
        return _empty_pair()
    members: dict[str, pd.DataFrame] = {}
    for idx in index_df["ts_code"].dropna().astype(str):
        members[idx] = call_api("ths_member", ts_code=idx)
    return normalize_board_members(index_df, members)


def build_mapping(kind: str, *, trade_date: str | None = None, refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """拉取/缓存某体系映射。trade_date 仅东财需要（YYYYMMDD）。"""
    if kind not in KINDS:
        raise ValueError(f"unsupported kind: {kind}")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"sector_mapping_{kind}.json"
    if not refresh and cache.exists():
        payload = json.loads(cache.read_text(encoding="utf-8"))
        return (
            pd.DataFrame(payload.get("mapping", []), columns=_MAPPING_COLS),
            pd.DataFrame(payload.get("catalog", []), columns=_CATALOG_COLS),
        )
    if kind == "sw_l3":
        mapping, catalog = fetch_sw_mapping()
    elif kind == "ci_l3":
        mapping, catalog = fetch_ci_mapping()
    elif kind == "dc_ind":
        if not trade_date:
            raise ValueError("dc_ind 需要 trade_date（YYYYMMDD）")
        mapping, catalog = fetch_dc_mapping(trade_date)
    else:  # ths_ind
        mapping, catalog = fetch_ths_mapping()
    cache.write_text(
        json.dumps(
            {"mapping": mapping.to_dict("records"), "catalog": catalog.to_dict("records")},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return mapping, catalog
