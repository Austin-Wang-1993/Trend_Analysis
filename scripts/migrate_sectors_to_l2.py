#!/usr/bin/env python3
"""将 history.db 已有 stock_daily 板块归属迁移为申万 L2，并重聚合 sector_daily。

无需重打必盈成交/买卖 API；前提是 data/cache/sector_mapping_l2.json 已存在。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from by_common import ensure_stock_codes, pick_primary_sector
from history_store import HistoryStore
from sector_config import DEFAULT_SECTOR_LEVEL, mapping_cache_name, primary_type2_for_level

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "history.db"


def main() -> int:
    l2_cache = DATA_DIR / "cache" / mapping_cache_name("l2")
    if not l2_cache.exists():
        tree_cache = DATA_DIR / "cache" / "sector_tree.json"
        if tree_cache.exists():
            print(f"缺少 {l2_cache.name}，尝试从 sector_tree 缓存自动构建 L2 映射...")
            import subprocess

            rc = subprocess.run(
                [sys.executable, str(Path(__file__).resolve().parent / "build_sector_mapping.py"), "--level", "l2"],
                cwd=str(ROOT),
            ).returncode
            if rc != 0 or not l2_cache.exists():
                print("自动构建失败", file=sys.stderr)
                return 1
        else:
            print(
                f"错误: 缺少 {l2_cache}\n"
                "请先执行（约 2–3 分钟，仅拉映射，不拉成交）:\n"
                "  python3 scripts/build_sector_mapping.py --level l2\n"
                "若连 sector_tree.json 也没有，加 --refresh-tree\n"
                "然后: python3 scripts/migrate_sectors_to_l2.py",
                file=sys.stderr,
            )
            return 1

    mapping = ensure_stock_codes(pd.DataFrame(json.loads(l2_cache.read_text(encoding="utf-8"))))
    primary = pick_primary_sector(mapping, type2=primary_type2_for_level("l2"))
    primary = ensure_stock_codes(primary)
    sector_by_code = primary.set_index("stock_code")[["sector_code", "sector_name"]].to_dict("index")
    sector_count = primary["sector_code"].nunique()

    store = HistoryStore(DB_PATH)
    with store._connect() as conn:
        dates = [
            r[0]
            for r in conn.execute("SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date").fetchall()
        ]
        if not dates:
            print("错误: stock_daily 无数据", file=sys.stderr)
            return 1
        stock_count = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]

    updated = 0
    unmapped = 0
    with store._connect() as conn:
        rows = conn.execute("SELECT trade_date, stock_code FROM stock_daily").fetchall()
        for row in rows:
            td, code = row["trade_date"], str(row["stock_code"]).zfill(6) if str(row["stock_code"]).isdigit() else str(row["stock_code"])
            sec = sector_by_code.get(code)
            if not sec:
                unmapped += 1
                continue
            conn.execute(
                """
                UPDATE stock_daily SET sector_code=?, sector_name=?
                WHERE trade_date=? AND stock_code=?
                """,
                (sec["sector_code"], sec["sector_name"], td, code),
            )
            updated += 1
        conn.commit()

    store.rebuild_aggregates_for_dates(set(dates))
    print(f"已迁移 {updated}/{stock_count} 条 stock_daily → 申万 L2（{sector_count} 个板块）")
    print(f"仍无 L2 归属: {unmapped} 条（与全 A 未归类新股一致）")
    print(f"重聚合日期: {dates}")
    print(f"默认层级: {DEFAULT_SECTOR_LEVEL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
