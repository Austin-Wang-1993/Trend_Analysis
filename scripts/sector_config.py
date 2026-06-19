"""板块 kind 配置（v4.0 Tushare 四套细分行业）。"""

from __future__ import annotations

# 页面 2/3 Tab 顺序
SECTOR_TABLE_KINDS = ("sw_l3", "ci_l3", "dc_ind", "ths_ind")

DEFAULT_SECTOR_KIND = "sw_l3"

KIND_LABELS: dict[str, str] = {
    "sw_l3": "申万三级",
    "ci_l3": "中信三级",
    "dc_ind": "东财行业",
    "ths_ind": "同花顺行业",
}

UNMAPPED_SECTOR_CODE = "UNMAPPED"
UNMAPPED_SECTOR_NAME = "未分类"

VIEW_DAYS_OPTIONS = (5, 15, 30)
DEFAULT_VIEW_DAYS = 5

MAX_FETCH_TRADING_DAYS = 400


def kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, kind)


def mapping_cache_name(kind: str) -> str:
    return f"industry_mapping_{kind}.json"


def validate_kind(kind: str) -> str:
    if kind not in SECTOR_TABLE_KINDS:
        raise ValueError(f"unsupported kind: {kind}")
    return kind
