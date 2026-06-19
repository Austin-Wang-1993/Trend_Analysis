#!/usr/bin/env python3
"""根据 stock_daily 重算 market_daily 与四套 industry sector_daily。

无需重打 Tushare API；适用于映射更新后或修复 sector/stock 不一致。

若报 database is locked，请先停止看板/API 服务再执行，例如：
  sudo systemctl stop trend-analysis
  python scripts/rebuild_sector_aggregates.py
  sudo systemctl start trend-analysis
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from history_store import HistoryStore
from sector_config import KIND_LABELS, SECTOR_TABLE_KINDS

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
        for kind in SECTOR_TABLE_KINDS:
            n = conn.execute(
                "SELECT COUNT(*) FROM industry_stock_map WHERE kind=?",
                (kind,),
            ).fetchone()[0]
            print(f"industry_stock_map {kind} ({KIND_LABELS.get(kind, kind)}): {n} 条")
    if not dates:
        print("错误: stock_daily 无数据", file=sys.stderr)
        return 1
    with store._connect() as conn:
        empty = [
            k for k in SECTOR_TABLE_KINDS
            if conn.execute("SELECT COUNT(*) FROM industry_stock_map WHERE kind=?", (k,)).fetchone()[0] == 0
        ]
    if empty:
        print(
            "提示: 部分行业映射为空，请先执行：\n"
            "  set -a && source .env && set +a\n"
            "  python scripts/refresh_sector_mappings.py\n"
            "  python scripts/rebuild_sector_aggregates.py",
            file=sys.stderr,
        )
    store.rebuild_aggregates_for_dates(set(dates))
    print(f"已重聚合四套行业板块，共 {len(dates)} 日: {dates[0]} ~ {dates[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
