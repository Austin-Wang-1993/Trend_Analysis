#!/usr/bin/env python3
"""刷新板块 ↔ 个股映射：申万 L2 + 热门概念 + 概念板块（hszg/list + hszg/gg）。

建议每日凌晨定时执行；不拉成交/买卖数据。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from by_common import TYPE2_BOARD, TYPE2_HOT, build_sector_mapping, ensure_stock_codes, get_licence, pick_primary_sector
from concept_common import load_or_build_concept_mapping
from fetch_by_daily import DATA_DIR, load_or_build_tree, sectors_for_level
from history_store import HistoryStore
from sector_config import DEFAULT_SECTOR_LEVEL, mapping_cache_name, primary_type2_for_level

DB_PATH = DATA_DIR / "history.db"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="刷新申万与概念板块映射")
    p.add_argument("--refresh-tree", action="store_true", help="强制重拉 hszg/list")
    p.add_argument("--skip-sw", action="store_true", help="跳过申万 L2 映射")
    p.add_argument("--skip-concepts", action="store_true", help="跳过热门概念/概念板块")
    p.add_argument("--no-db", action="store_true", help="仅写 JSON 缓存，不写 SQLite")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    try:
        licence = get_licence()
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    tree_cache = DATA_DIR / "cache" / "sector_tree.json"
    print("刷新板块映射...")
    tree_df = load_or_build_tree(licence, tree_cache, refresh=args.refresh_tree)

    if not args.skip_sw:
        level = DEFAULT_SECTOR_LEVEL
        sectors_df = sectors_for_level(tree_df, level)
        print(f"  申万 {level}: {len(sectors_df)} 个板块")
        sw_mapping = ensure_stock_codes(build_sector_mapping(licence, sectors_df))
        cache_path = DATA_DIR / "cache" / mapping_cache_name(level)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(sw_mapping.to_json(orient="records", force_ascii=False), encoding="utf-8")
        primary = pick_primary_sector(sw_mapping, type2=primary_type2_for_level(level))
        print(f"  已写入 {cache_path.name}：{len(sw_mapping)} 条，{primary['sector_code'].nunique()} 板块")

    concept_frames = []
    if not args.skip_concepts:
        for concept_type, label in ((TYPE2_HOT, "热门概念"), (TYPE2_BOARD, "概念板块")):
            print(f"  {label} (type2={concept_type})...")
            mapping_df, sectors_df = load_or_build_concept_mapping(
                licence, tree_df, concept_type, refresh=True
            )
            concept_frames.append((concept_type, mapping_df))
            print(f"    板块 {len(sectors_df)}，映射 {len(mapping_df)} 条")

    if not args.no_db and concept_frames:
        store = HistoryStore(DB_PATH)
        for concept_type, mapping_df in concept_frames:
            store.replace_concept_stock_map(concept_type, mapping_df)
        print("  已同步 concept_stock_map → history.db")

    print("完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
