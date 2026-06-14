from __future__ import annotations

from apscheduler.schedulers.blocking import BlockingScheduler
from loguru import logger

from core.config import settings
from core.db import init_db
from sync.runner import sync_all


def main() -> None:
    init_db()
    scheduler = BlockingScheduler()
    parts = settings.sync_cron.split()
    if len(parts) != 5:
        raise ValueError(f"无效的 SYNC_CRON: {settings.sync_cron}")

    minute, hour, day, month, day_of_week = parts
    scheduler.add_job(
        sync_all,
        trigger="cron",
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
        id="daily_fund_flow_sync",
    )
    logger.info("定时同步已启动，cron={}", settings.sync_cron)
    scheduler.start()


if __name__ == "__main__":
    main()
