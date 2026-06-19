"""APScheduler 定时采集。"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

if TYPE_CHECKING:
    from history_store import HistoryStore

CST = ZoneInfo("Asia/Shanghai")
_scheduler: BackgroundScheduler | None = None
_SCRIPTS = Path(__file__).resolve().parent


def _run_mapping_refresh() -> None:
    subprocess.run(
        [sys.executable, str(_SCRIPTS / "refresh_sector_mappings.py")],
        cwd=str(_SCRIPTS.parent),
        check=False,
    )


def _parse_time(s: str) -> tuple[int, int]:
    parts = s.strip().split(":")
    return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0


def compute_next_run(settings: dict[str, str]) -> dict:
    """计算下次触发时间（供管理页展示）。"""
    sys_path_added = False
    import sys
    from pathlib import Path

    scripts = Path(__file__).resolve().parent
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
        sys_path_added = True

    from trading_calendar import get_recent_trading_days, is_trading_day, today_cst

    enabled = settings.get("schedule_enabled", "true").lower() == "true"
    tz_name = settings.get("schedule_timezone", "Asia/Shanghai")
    tz = ZoneInfo(tz_name)
    hour, minute = _parse_time(settings.get("schedule_time", "21:35"))
    mode = settings.get("schedule_run_mode", "trading_day")
    now = datetime.now(tz)
    next_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_at <= now:
        next_at += timedelta(days=1)

    will_execute = True
    next_trading_at = None
    if mode == "trading_day" and not is_trading_day(next_at.date().isoformat()):
        will_execute = False
        probe = next_at
        for _ in range(366):
            if is_trading_day(probe.date().isoformat()):
                next_trading_at = probe.isoformat()
                break
            probe += timedelta(days=1)

    return {
        "next_run_at": next_at.isoformat(),
        "next_run_will_execute": will_execute,
        "next_trading_run_at": next_trading_at,
    }


def start_scheduler(store: "HistoryStore", run_callback) -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    settings = store.get_settings()
    tz_name = settings.get("schedule_timezone", "Asia/Shanghai")
    tz = ZoneInfo(tz_name)
    hour, minute = _parse_time(settings.get("schedule_time", "21:35"))

    _scheduler = BackgroundScheduler(timezone=tz)

    def _job() -> None:
        run_callback()

    if settings.get("schedule_enabled", "true").lower() == "true":
        _scheduler.add_job(
            _job,
            CronTrigger(hour=hour, minute=minute, timezone=tz),
            id="daily_fetch",
            replace_existing=True,
        )
    if settings.get("mapping_refresh_enabled", "true").lower() == "true":
        map_hour, map_minute = _parse_time(settings.get("mapping_refresh_time", "02:00"))
        _scheduler.add_job(
            _run_mapping_refresh,
            CronTrigger(day_of_week="sun", hour=map_hour, minute=map_minute, timezone=tz),
            id="mapping_refresh",
            replace_existing=True,
        )
    _scheduler.start()
    return _scheduler


def reload_scheduler(store: "HistoryStore", run_callback) -> None:
    global _scheduler
    if _scheduler is None:
        start_scheduler(store, run_callback)
        return
    settings = store.get_settings()
    tz_name = settings.get("schedule_timezone", "Asia/Shanghai")
    tz = ZoneInfo(tz_name)
    hour, minute = _parse_time(settings.get("schedule_time", "21:35"))

    try:
        _scheduler.remove_job("daily_fetch")
    except Exception:
        pass

    if settings.get("schedule_enabled", "true").lower() == "true":
        _scheduler.add_job(
            run_callback,
            CronTrigger(hour=hour, minute=minute, timezone=tz),
            id="daily_fetch",
            replace_existing=True,
        )

    try:
        _scheduler.remove_job("mapping_refresh")
    except Exception:
        pass
    if settings.get("mapping_refresh_enabled", "true").lower() == "true":
        map_hour, map_minute = _parse_time(settings.get("mapping_refresh_time", "02:00"))
        _scheduler.add_job(
            _run_mapping_refresh,
            CronTrigger(day_of_week="sun", hour=map_hour, minute=map_minute, timezone=tz),
            id="mapping_refresh",
            replace_existing=True,
        )
