"""板块层级默认配置（看板展示用申万二级）。"""

from __future__ import annotations

from by_common import TYPE2_SW_L1, TYPE2_SW_L2, TYPE2_HOT, TYPE2_BOARD

DEFAULT_SECTOR_LEVEL = "l2"

SECTOR_TABLE_KINDS = ("sw_l2", "hot", "board")


def mapping_cache_name(level: str | None = None) -> str:
    lv = level or DEFAULT_SECTOR_LEVEL
    return f"sector_mapping_{lv}.json"


def concept_mapping_cache_name(concept_type: int) -> str:
    if concept_type == TYPE2_HOT:
        return "concept_mapping_hot.json"
    if concept_type == TYPE2_BOARD:
        return "concept_mapping_board.json"
    raise ValueError(f"unsupported concept_type: {concept_type}")


def concept_type_for_kind(kind: str) -> int | None:
    if kind == "sw_l2":
        return None
    if kind == "hot":
        return TYPE2_HOT
    if kind == "board":
        return TYPE2_BOARD
    raise ValueError(f"unsupported kind: {kind}")


def primary_type2_for_level(level: str | None = None) -> int:
    lv = level or DEFAULT_SECTOR_LEVEL
    if lv == "l1":
        return TYPE2_SW_L1
    return TYPE2_SW_L2
