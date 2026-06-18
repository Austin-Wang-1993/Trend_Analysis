#!/usr/bin/env python3
"""刷新板块 ↔ 个股映射：申万 L2 + 热门概念 + 概念板块（hszg/list + hszg/gg）。

建议每日凌晨定时执行；不拉成交/买卖数据。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "history.db"


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="刷新申万与概念板块映射")
    p.add_argument("--refresh-tree", action="store_true", help="强制重拉 hszg/list")
    p.add_argument("--skip-sw", action="store_true", help="跳过申万 L2 映射")
    p.add_argument("--skip-concepts", action="store_true", help="跳过热门概念/概念板块")
    p.add_argument("--hot-only", action="store_true", help="仅刷新热门概念")
    p.add_argument("--board-only", action="store_true", help="仅刷新概念板块")
    p.add_argument("--no-db", action="store_true", help="仅写 JSON 缓存，不写 SQLite")
    return p.parse_args()


def main() -> int:
    _load_dotenv()
    args = parse_args()

    from by_common import TYPE2_BOARD, TYPE2_HOT, build_sector_mapping, ensure_stock_codes, get_licence, pick_primary_sector
    from concept_common import load_or_build_concept_mapping
    from fetch_by_daily import load_or_build_tree, sectors_for_level
    from history_store import HistoryStore
    from sector_config import DEFAULT_SECTOR_LEVEL, concept_mapping_cache_name, mapping_cache_name, primary_type2_for_level

    try:
        licence = get_licence()
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    tree_cache = DATA_DIR / "cache" / "sector_tree.json"
    print("刷新板块映射...")
    tree_df = load_or_build_tree(licence, tree_cache, refresh=args.refresh_tree)

    store = None if args.no_db else HistoryStore(DB_PATH)

    if not args.skip_sw and not args.hot_only and not args.board_only:
        level = DEFAULT_SECTOR_LEVEL
        sectors_df = sectors_for_level(tree_df, level)
        print(f"  申万 {level}: {len(sectors_df)} 个板块")
        sw_mapping = ensure_stock_codes(build_sector_mapping(licence, sectors_df))
        cache_path = DATA_DIR / "cache" / mapping_cache_name(level)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(sw_mapping.to_json(orient="records", force_ascii=False), encoding="utf-8")
        primary = pick_primary_sector(sw_mapping, type2=primary_type2_for_level(level))
        print(f"  已写入 {cache_path.name}：{len(sw_mapping)} 条，{primary['sector_code'].nunique()} 板块")

    concept_jobs: list[tuple[int, str]] = []
    if not args.skip_concepts:
        if args.hot_only:
            concept_jobs = [(TYPE2_HOT, "热门概念")]
        elif args.board_only:
            concept_jobs = [(TYPE2_BOARD, "概念板块")]
        else:
            concept_jobs = [(TYPE2_HOT, "热门概念"), (TYPE2_BOARD, "概念板块")]

    for concept_type, label in concept_jobs:
        print(f"  {label} (type2={concept_type})...")
        mapping_df, sectors_df = load_or_build_concept_mapping(
            licence, tree_df, concept_type, refresh=True
        )
        print(f"    板块 {len(sectors_df)}，映射 {len(mapping_df)} 条")
        if store is not None:
            store.replace_concept_stock_map(concept_type, mapping_df)
            print(f"    已同步 concept_stock_map (type={concept_type}) → history.db")

    # 若仅 board-only，可把已有 hot 缓存一并写入 DB（避免上次中断未落库）
    if store is not None and args.board_only:
        hot_cache = DATA_DIR / "cache" / concept_mapping_cache_name(TYPE2_HOT)
        if hot_cache.exists():
            hot_df = ensure_stock_codes(pd.DataFrame(json.loads(hot_cache.read_text(encoding="utf-8"))))
            store.replace_concept_stock_map(TYPE2_HOT, hot_df)
            print(f"  已从缓存同步热门概念：{len(hot_df)} 条")

    print("完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
