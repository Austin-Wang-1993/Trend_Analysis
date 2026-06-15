"""板块层级默认配置（看板展示用申万二级）。"""

from __future__ import annotations

from by_common import TYPE2_SW_L1, TYPE2_SW_L2

DEFAULT_SECTOR_LEVEL = "l2"


def mapping_cache_name(level: str | None = None) -> str:
    lv = level or DEFAULT_SECTOR_LEVEL
    return f"sector_mapping_{lv}.json"


def primary_type2_for_level(level: str | None = None) -> int:
    lv = level or DEFAULT_SECTOR_LEVEL
    if lv == "l1":
        return TYPE2_SW_L1
    return TYPE2_SW_L2
