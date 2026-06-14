#!/usr/bin/env python3
"""单日端到端验证：初始化库 → 同步 → 分析 → 输出报告。"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from loguru import logger

from analysis.aggregator import build_daily_snapshot
from analysis.cli import print_daily_report
from core.db import init_db
from sync.runner import sync_all


def main() -> int:
    parser = argparse.ArgumentParser(description="验证单日资金流量流水线")
    parser.add_argument("--date", help="交易日 YYYY-MM-DD，默认由数据源推断")
    args = parser.parse_args()

    trade_date = date.fromisoformat(args.date) if args.date else None

    init_db()
    logger.info("开始单日同步...")
    try:
        counts = sync_all(trade_date)
        logger.info("同步结果: {}", counts)
    except Exception as exc:
        logger.exception("同步失败: {}", exc)
        return 1

    resolved_date = trade_date
    if resolved_date is None:
        from core.db import get_session
        from core.models import StockFundFlow
        from sqlalchemy import select

        with get_session() as session:
            resolved_date = session.scalar(
                select(StockFundFlow.trade_date).order_by(StockFundFlow.trade_date.desc()).limit(1)
            )
    if not resolved_date:
        logger.error("未能确定交易日")
        return 1

    logger.info("开始分析: {}", resolved_date)
    snapshot_counts = build_daily_snapshot(resolved_date)
    logger.info("快照结果: {}", snapshot_counts)
    print_daily_report(resolved_date)
    return 0


if __name__ == "__main__":
    sys.exit(main())
