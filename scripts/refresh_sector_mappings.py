#!/usr/bin/env python3
"""刷新四套行业 ↔ 个股映射（Tushare）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "history.db"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="刷新 Tushare 四套行业映射")
    p.add_argument(
        "--kinds",
        nargs="+",
        choices=["sw_l3", "ci_l3", "dc_ind", "ths_ind", "all"],
        default=["all"],
        help="要刷新的 kind（默认全部）",
    )
    p.add_argument("--no-db", action="store_true", help="仅写 JSON 缓存，不写 SQLite")
    p.add_argument("--trade-date", help="东财 dc_index/dc_member 使用的交易日 YYYY-MM-DD")
    return p.parse_args()


def main() -> int:
    from industry_common import build_mapping, save_mapping_cache
    from sector_config import KIND_LABELS, SECTOR_TABLE_KINDS
    from history_store import HistoryStore
    from ts_common import get_pro, load_dotenv

    load_dotenv()
    args = parse_args()

    try:
        pro = get_pro()
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    kinds = list(SECTOR_TABLE_KINDS) if "all" in args.kinds else args.kinds
    store = None if args.no_db else HistoryStore(DB_PATH)

    print("刷新 Tushare 行业映射...")
    for kind in kinds:
        label = KIND_LABELS.get(kind, kind)
        print(f"  {label} ({kind})...")
        kwargs = {}
        if kind == "dc_ind" and args.trade_date:
            kwargs["trade_date"] = args.trade_date
        mapping_df = build_mapping(kind, pro=pro, **kwargs)
        path = save_mapping_cache(kind, mapping_df)
        print(f"    缓存 {path.name}: {len(mapping_df)} 条，{mapping_df['sector_code'].nunique()} 板块")
        if store is not None:
            store.replace_industry_stock_map(kind, mapping_df)
            print(f"    已同步 industry_stock_map → history.db")

    print("完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
