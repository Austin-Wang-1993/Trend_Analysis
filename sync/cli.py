from __future__ import annotations

import argparse
from datetime import date

from loguru import logger

from core.config import settings
from core.db import init_db
from sync.runner import sync_all, sync_etfs, sync_market, sync_sectors, sync_stocks


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="资金流量数据同步 CLI")
    parser.add_argument(
        "job",
        choices=["all", "market", "sector", "stock", "etf"],
        help="同步任务类型",
    )
    parser.add_argument("--date", help="交易日 YYYY-MM-DD，默认取数据源最新交易日")
    parser.add_argument("--init-db", action="store_true", help="初始化数据库表")
    args = parser.parse_args()

    if args.init_db:
        init_db()
        logger.info("数据库初始化完成: {}", settings.database_url)

    trade_date = _parse_date(args.date)
    if args.job == "all":
        result = sync_all(trade_date)
    elif args.job == "market":
        result = {"market": sync_market(trade_date)}
    elif args.job == "sector":
        result = {"sector": sync_sectors(trade_date)}
    elif args.job == "stock":
        result = {"stock": sync_stocks(trade_date)}
    else:
        result = {"etf": sync_etfs(trade_date)}

    logger.info("同步完成: {}", result)


if __name__ == "__main__":
    main()
