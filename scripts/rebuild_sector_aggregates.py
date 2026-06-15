#!/usr/bin/env python3
"""根据 stock_daily 重算 market/sector_daily，并清理当日僵尸板块行。

无需重打必盈 API；适用于 L1→L2 迁移后或修复 sector/stock 不一致。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from history_store import HistoryStore

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "history.db"


def main() -> int:
    store = HistoryStore(DB_PATH)
    with store._connect() as conn:
        dates = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date"
            ).fetchall()
        ]
    if not dates:
        print("错误: stock_daily 无数据", file=sys.stderr)
        return 1
    store.rebuild_aggregates_for_dates(set(dates))
    print(f"已重聚合并清理 sector 僵尸行，共 {len(dates)} 日: {dates}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
