from __future__ import annotations

import argparse
import json
from datetime import date

from loguru import logger
from sqlalchemy import select

from analysis.aggregator import build_daily_snapshot
from core.db import get_session, init_db
from core.models import AnalysisSnapshot, SyncLog


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _latest_synced_date() -> date | None:
    with get_session() as session:
        row = session.scalar(
            select(SyncLog.trade_date)
            .where(SyncLog.status == "success", SyncLog.trade_date.is_not(None))
            .order_by(SyncLog.trade_date.desc())
            .limit(1)
        )
        return row


def print_daily_report(trade_date: date) -> None:
    with get_session() as session:
        rows = session.scalars(
            select(AnalysisSnapshot)
            .where(AnalysisSnapshot.trade_date == trade_date)
            .order_by(AnalysisSnapshot.entity_type, AnalysisSnapshot.rank_no)
        ).all()
        records = [
            {
                "entity_type": row.entity_type,
                "entity_key": row.entity_key,
                "rank_no": row.rank_no,
                "net_inflow": row.net_inflow,
                "inflow_amount": row.inflow_amount,
                "outflow_amount": row.outflow_amount,
                "market_share": row.market_share,
                "stock_count": row.stock_count,
                "extra_json": row.extra_json,
            }
            for row in rows
        ]

    grouped: dict[str, list] = {"market": [], "sector": [], "stock": [], "etf": []}
    for row in records:
        grouped.setdefault(row["entity_type"], []).append(row)

    print(f"\n========== {trade_date} 资金流量日报 ==========")
    for market in grouped.get("market", []):
        print(
            f"[大盘] 净流入={market['net_inflow']} 流入={market['inflow_amount']} 流出={market['outflow_amount']}"
        )

    print("\n[板块 TOP10]")
    for row in grouped.get("sector", [])[:10]:
        extra = json.loads(row["extra_json"] or "{}")
        print(
            f"  #{row['rank_no']} {extra.get('sector_name')} "
            f"净流入={row['net_inflow']} 大盘占比={row['market_share']}% 个股数={row['stock_count']}"
        )

    print("\n[个股 TOP10]")
    for row in grouped.get("stock", [])[:10]:
        extra = json.loads(row["extra_json"] or "{}")
        print(
            f"  #{row['rank_no']} {row['entity_key']} {extra.get('stock_name')} "
            f"净流入={row['net_inflow']} 大盘占比={row['market_share']}%"
        )

    print("\n[ETF TOP10]")
    for row in grouped.get("etf", [])[:10]:
        extra = json.loads(row["extra_json"] or "{}")
        print(
            f"  #{row['rank_no']} {row['entity_key']} {extra.get('etf_name')} "
            f"净流入={row['net_inflow']} 大盘占比={row['market_share']}%"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="资金流量分析 CLI")
    parser.add_argument("action", choices=["build", "report"], help="build=生成快照, report=打印日报")
    parser.add_argument("--date", help="交易日 YYYY-MM-DD")
    parser.add_argument("--init-db", action="store_true")
    args = parser.parse_args()

    if args.init_db:
        init_db()

    trade_date = _parse_date(args.date) or _latest_synced_date()
    if not trade_date:
        raise SystemExit("未找到可分析日期，请先执行 sync")

    if args.action == "build":
        result = build_daily_snapshot(trade_date)
        logger.info("分析快照已生成: date={} counts={}", trade_date, result)
    else:
        print_daily_report(trade_date)


if __name__ == "__main__":
    main()
