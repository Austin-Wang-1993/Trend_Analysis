"""行业映射回退：当必盈 hszg 不可用时，用 TickFlow 申万标的池构建映射。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from by_common import TYPE2_SW_L1, TYPE2_SW_L2, normalize_code6
from tf_common import build_sw_mapping, get_client


def _stock_map_to_frames(stock_map: dict[str, dict[str, str]], level: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """将 TickFlow stock_map 转为必盈兼容的 tree_df 与 mapping_df。"""
    if level == "l1":
        fields = ("industry_l1_code", "industry_l1_name", TYPE2_SW_L1, 1)
    elif level == "l2":
        fields = ("industry_l2_code", "industry_l2_name", TYPE2_SW_L2, 2)
    else:
        raise ValueError(f"unsupported level for stock_map conversion: {level}")

    code_field, name_field, type2, lv = fields
    sector_rows: dict[str, dict[str, Any]] = {}
    mapping_rows: list[dict[str, Any]] = []

    for symbol, info in stock_map.items():
        name = str(info.get(name_field, "")).strip()
        if not name:
            continue
        try:
            stock_code = normalize_code6(symbol)
        except ValueError:
            continue
        sector_code = f"sw{lv}_{name}"
        if sector_code not in sector_rows:
            sector_rows[sector_code] = {
                "name": f"A股-申万{'行业' if lv == 1 else '二级'}-{name}",
                "code": sector_code,
                "type1": 0,
                "type2": type2,
                "level": 2,
                "pcode": "swhy" if lv == 1 else "sw2_root",
                "pname": "A股-申万行业" if lv == 1 else "A股-申万二级",
                "isleaf": 1,
            }
        mapping_rows.append(
            {
                "sector_code": sector_code,
                "sector_name": name,
                "sector_type2": type2,
                "sector_level": 2,
                "parent_code": "swhy" if lv == 1 else "",
                "parent_name": "A股-申万行业" if lv == 1 else "A股-申万二级",
                "stock_code": stock_code,
                "stock_name": "",
                "exchange": "SH" if stock_code.startswith(("5", "6", "9")) else "SZ",
            }
        )

    if not mapping_rows:
        raise RuntimeError(f"TickFlow 申万 {level} 映射为空")
    tree_df = pd.DataFrame(list(sector_rows.values()))
    mapping_df = pd.DataFrame(mapping_rows).drop_duplicates(["sector_code", "stock_code"], keep="first")
    return tree_df.reset_index(drop=True), mapping_df.reset_index(drop=True)


def build_tickflow_mapping(level: str = "l1") -> tuple[pd.DataFrame, pd.DataFrame]:
    """用 TickFlow 免费申万标的池构建 (tree_df, mapping_df)。"""
    print("     必盈 hszg 不可用，回退 TickFlow 申万标的池（免费）...")
    tf = get_client()
    stock_map = build_sw_mapping(tf)
    print(f"     TickFlow 股票覆盖: {len(stock_map)}")

    if level == "both":
        tree_l1, map_l1 = _stock_map_to_frames(stock_map, "l1")
        tree_l2, map_l2 = _stock_map_to_frames(stock_map, "l2")
        tree_df = pd.concat([tree_l1, tree_l2], ignore_index=True).drop_duplicates("code")
        mapping_df = pd.concat([map_l1, map_l2], ignore_index=True).drop_duplicates(
            ["sector_code", "stock_code"], keep="first"
        )
        return tree_df.reset_index(drop=True), mapping_df.reset_index(drop=True)

    return _stock_map_to_frames(stock_map, level)
