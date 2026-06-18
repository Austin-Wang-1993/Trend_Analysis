#!/usr/bin/env python3
"""根据 stock_daily 重算 market/sector_daily、concept_sector_daily，并清理僵尸行。

无需重打必盈 API；适用于 L1→L2 迁移后、概念映射更新后或修复 sector/stock 不一致。

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
        for concept_type, label in ((2, "热门概念"), (3, "概念板块")):
            n = conn.execute(
                "SELECT COUNT(*) FROM concept_stock_map WHERE concept_type=?",
                (concept_type,),
            ).fetchone()[0]
            print(f"concept_stock_map type={concept_type} ({label}): {n} 条")
    if not dates:
        print("错误: stock_daily 无数据", file=sys.stderr)
        return 1
    with store._connect() as conn:
        board_map = conn.execute(
            "SELECT COUNT(*) FROM concept_stock_map WHERE concept_type=3"
        ).fetchone()[0]
    if board_map == 0:
        print(
            "提示: 概念板块映射为空，请先执行：\n"
            "  set -a && source .env && set +a\n"
            "  python scripts/refresh_sector_mappings.py --board-only\n"
            "  python scripts/rebuild_sector_aggregates.py",
            file=sys.stderr,
        )
    store.rebuild_aggregates_for_dates(set(dates))
    print(f"已重聚合 sector + concept，共 {len(dates)} 日: {dates[0]} ~ {dates[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
