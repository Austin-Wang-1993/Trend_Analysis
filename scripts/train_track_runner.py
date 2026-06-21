"""火车轨扫描后台任务（进度可轮询）。"""

from __future__ import annotations

import logging
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "history.db"
CST = ZoneInfo("Asia/Shanghai")

sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT / "scripts"))

from history_store import HistoryStore
from train_track_scanner import TrainTrackScanner
from train_track_store import TrainTrackStore, format_scan_progress

_lock = threading.Lock()
_running = False
_current_job_id: str | None = None

logger = logging.getLogger(__name__)


def is_train_track_scan_running() -> bool:
    with _lock:
        return _running


def get_running_train_track_job_id() -> str | None:
    with _lock:
        return _current_job_id if _running else None


def _resolve_trade_date(trade_date: str | None) -> str:
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from trading_calendar import get_recent_trading_days, is_trading_day, today_cst

    td = trade_date or today_cst()
    if is_trading_day(td):
        return td
    recent = get_recent_trading_days(1, end=td)
    return recent[-1] if recent else td


def run_scan_job(job_id: str, *, trade_date: str | None = None, trigger_type: str = "manual") -> None:
    global _running, _current_job_id
    tt_store = TrainTrackStore(DB_PATH)
    hist = HistoryStore(DB_PATH)
    td = _resolve_trade_date(trade_date)
    t0 = time.time()

    def on_progress(phase: str, current: int, total: int) -> None:
        tt_store.update_scan_job(
            job_id,
            progress=format_scan_progress(phase, current, total),
        )

    try:
        tt_store.update_scan_job(
            job_id,
            status="running",
            started_at=datetime.now(CST).isoformat(),
            trade_date=td,
            progress="cache:0/0",
        )
        scanner = TrainTrackScanner(DB_PATH, get_settings=hist.get_settings)
        result = scanner.scan(trade_date=td, progress=on_progress)
        duration = time.time() - t0
        if result.get("skipped"):
            tt_store.update_scan_job(
                job_id,
                status="success",
                finished_at=datetime.now(CST).isoformat(),
                duration_sec=duration,
                progress=result.get("reason", "skipped"),
                pick_count=0,
                error_message=result.get("reason"),
            )
        else:
            tt_store.update_scan_job(
                job_id,
                status="success",
                finished_at=datetime.now(CST).isoformat(),
                duration_sec=duration,
                progress="done",
                pick_count=result.get("pick_count", 0),
            )
    except Exception as exc:
        logger.exception("train track scan job failed")
        tt_store.update_scan_job(
            job_id,
            status="failed",
            finished_at=datetime.now(CST).isoformat(),
            duration_sec=time.time() - t0,
            progress="failed",
            error_message=str(exc),
        )
    finally:
        with _lock:
            _running = False
            _current_job_id = None


def enqueue_train_track_scan(
    *,
    trade_date: str | None = None,
    trigger_type: str = "manual",
) -> dict[str, Any]:
    global _running, _current_job_id
    from job_worker import is_job_running

    if is_job_running():
        raise RuntimeError("数据采集任务运行中，请稍后再试")
    with _lock:
        if _running:
            active = TrainTrackStore(DB_PATH).get_active_scan_job()
            if active:
                return {"job_id": active["job_id"], "status": active["status"], "reused": True}
            raise RuntimeError("火车轨扫描任务运行中")
        _running = True

    tt_store = TrainTrackStore(DB_PATH)
    td = _resolve_trade_date(trade_date)
    job_id = tt_store.create_scan_job(td, trigger_type)

    def _worker() -> None:
        global _current_job_id
        with _lock:
            _current_job_id = job_id
        run_scan_job(job_id, trade_date=td, trigger_type=trigger_type)

    threading.Thread(target=_worker, daemon=True).start()
    return {"job_id": job_id, "status": "pending", "trade_date": td}


def get_scan_status(job_id: str | None = None) -> dict[str, Any]:
    tt_store = TrainTrackStore(DB_PATH)
    if job_id:
        job = tt_store.get_scan_job(job_id)
    else:
        job = tt_store.get_active_scan_job() or tt_store.get_latest_scan_job()
    if not job:
        return {"active": False}
    return {
        "active": job.get("status") in ("pending", "running"),
        "job": job,
    }


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="火车轨扫描任务")
    ap.add_argument("--scheduled", action="store_true", help="定时任务：同步执行并写任务记录")
    ap.add_argument("--enqueue", action="store_true", help="后台入队（供调试）")
    ns = ap.parse_args()
    if ns.scheduled:
        td = _resolve_trade_date(None)
        store = TrainTrackStore(DB_PATH)
        job_id = store.create_scan_job(td, "scheduled")
        run_scan_job(job_id, trade_date=td, trigger_type="scheduled")
    elif ns.enqueue:
        print(json.dumps(enqueue_train_track_scan(trigger_type="manual"), ensure_ascii=False))
    else:
        ap.print_help()
