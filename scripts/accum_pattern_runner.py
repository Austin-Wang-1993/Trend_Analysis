"""量价吸筹扫描后台任务。"""

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

from accum_pattern_scanner import AccumPatternScanner
from accum_pattern_store import AccumPatternStore, format_scan_progress
from history_store import HistoryStore

_lock = threading.Lock()
_running = False
_current_job_id: str | None = None

logger = logging.getLogger(__name__)


def is_accum_scan_running() -> bool:
    with _lock:
        return _running


def _resolve_trade_date(trade_date: str | None) -> str:
    from trading_calendar import get_recent_trading_days, is_trading_day, today_cst

    td = trade_date or today_cst()
    if is_trading_day(td):
        return td
    recent = get_recent_trading_days(1, end=td)
    return recent[-1] if recent else td


def run_scan_job(job_id: str, *, trade_date: str | None = None, trigger_type: str = "manual") -> None:
    global _running, _current_job_id
    store = AccumPatternStore(DB_PATH)
    hist = HistoryStore(DB_PATH)
    td = _resolve_trade_date(trade_date)
    t0 = time.time()

    def on_progress(phase: str, current: int, total: int) -> None:
        store.update_scan_job(
            job_id,
            progress=format_scan_progress(phase, current, total),
        )

    try:
        store.update_scan_job(
            job_id,
            status="running",
            started_at=datetime.now(CST).isoformat(),
            trade_date=td,
            progress="cache:0/0",
        )
        scanner = AccumPatternScanner(DB_PATH, get_settings=hist.get_settings)
        result = scanner.scan(trade_date=td, progress=on_progress)
        duration = time.time() - t0
        if result.get("skipped"):
            store.update_scan_job(
                job_id,
                status="success",
                finished_at=datetime.now(CST).isoformat(),
                duration_sec=duration,
                progress=result.get("reason", "skipped"),
                pick_count=0,
                error_message=result.get("reason"),
            )
        else:
            store.update_scan_job(
                job_id,
                status="success",
                finished_at=datetime.now(CST).isoformat(),
                duration_sec=duration,
                progress="done",
                pick_count=result.get("pick_count", 0),
            )
    except Exception as exc:
        logger.exception("accum pattern scan job failed")
        store.update_scan_job(
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


def enqueue_accum_scan(
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
            active = AccumPatternStore(DB_PATH).get_active_scan_job()
            if active:
                return {"job_id": active["job_id"], "status": active["status"], "reused": True}
            raise RuntimeError("量价吸筹扫描任务运行中")
        _running = True

    try:
        store = AccumPatternStore(DB_PATH)
        td = _resolve_trade_date(trade_date)
        job_id = store.create_scan_job(td, trigger_type)
    except Exception:
        with _lock:
            _running = False
        raise

    def _worker() -> None:
        global _current_job_id
        with _lock:
            _current_job_id = job_id
        run_scan_job(job_id, trade_date=td, trigger_type=trigger_type)

    threading.Thread(target=_worker, daemon=True).start()
    return {"job_id": job_id, "status": "pending", "trade_date": td}


def get_scan_status(job_id: str | None = None) -> dict[str, Any]:
    store = AccumPatternStore(DB_PATH)
    if job_id:
        job = store.get_scan_job(job_id)
    else:
        job = store.get_active_scan_job() or store.get_latest_scan_job()
    if not job:
        return {"active": False}
    return {
        "active": job.get("status") in ("pending", "running"),
        "job": job,
    }


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="量价吸筹扫描任务")
    ap.add_argument("--scheduled", action="store_true")
    ap.add_argument("--enqueue", action="store_true")
    ns = ap.parse_args()
    if ns.scheduled:
        td = _resolve_trade_date(None)
        store = AccumPatternStore(DB_PATH)
        job_id = store.create_scan_job(td, "scheduled")
        run_scan_job(job_id, trade_date=td, trigger_type="scheduled")
    elif ns.enqueue:
        print(json.dumps(enqueue_accum_scan(trigger_type="manual"), ensure_ascii=False))
    else:
        ap.print_help()
