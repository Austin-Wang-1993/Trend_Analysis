"""后台采集任务执行。"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from history_store import HistoryStore

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "history.db"
LOG_DIR = ROOT / "logs" / "jobs"
CST = ZoneInfo("Asia/Shanghai")

_lock = threading.Lock()
_running = False


def _log_path(job_id: str) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / f"{job_id}.log"


def is_job_running() -> bool:
    with _lock:
        return _running


def run_job(job_id: str, trade_date: str, *, trigger_type: str = "manual") -> None:
    global _running
    store = HistoryStore(DB_PATH)
    log_file = _log_path(job_id)
    store.update_job(job_id, log_path=str(log_file), status="running", started_at=datetime.now(CST).isoformat())

    with open(log_file, "a", encoding="utf-8") as lf:
        lf.write(f"[{datetime.now(CST).isoformat()}] start job={job_id} date={trade_date}\n")
        lf.flush()
        t0 = time.time()
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "fetch_by_date.py"),
                    "--date",
                    trade_date,
                    "--no-all-turnover",
                    "--job-id",
                    job_id,
                ],
                cwd=str(ROOT),
                stdout=lf,
                stderr=subprocess.STDOUT,
                env=_job_env(),
            )
            duration = time.time() - t0
            job = store.get_job(job_id) or {}
            status = job.get("status", "success" if proc.returncode == 0 else "failed")
            if proc.returncode != 0 and status == "running":
                status = "failed"
            store.update_job(
                job_id,
                status=status,
                finished_at=datetime.now(CST).isoformat(),
                duration_sec=duration,
            )
            lf.write(f"[{datetime.now(CST).isoformat()}] exit={proc.returncode} duration={duration:.1f}s\n")
        except Exception as exc:
            store.update_job(
                job_id,
                status="failed",
                error_message=str(exc),
                finished_at=datetime.now(CST).isoformat(),
            )
            lf.write(f"[{datetime.now(CST).isoformat()}] error: {exc}\n")
        finally:
            with _lock:
                _running = False


def _job_env() -> dict:
    import os

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("PYTHONPATH", str(SCRIPTS))
    return env


def enqueue_job(trade_date: str, trigger_type: str = "manual") -> str:
    global _running
    with _lock:
        if _running:
            raise RuntimeError("已有任务运行中")
        _running = True
    store = HistoryStore(DB_PATH)
    job_id = store.create_job(trade_date, trigger_type)

    def _worker() -> None:
        run_job(job_id, trade_date, trigger_type=trigger_type)

    threading.Thread(target=_worker, daemon=True).start()
    return job_id


def run_scheduled_fetch() -> None:
    """定时任务入口。"""
    sys.path.insert(0, str(SCRIPTS))
    from trading_calendar import should_run_scheduled_task, today_cst

    store = HistoryStore(DB_PATH)
    settings = store.get_settings()
    if settings.get("schedule_enabled", "true").lower() != "true":
        return
    mode = settings.get("schedule_run_mode", "trading_day")
    if not should_run_scheduled_task(mode):  # type: ignore[arg-type]
        job_id = store.create_job(today_cst(), "scheduled")
        store.update_job(
            job_id,
            status="success",
            progress="skipped_non_trading_day",
            finished_at=datetime.now(CST).isoformat(),
        )
        return
    if is_job_running():
        return
    try:
        enqueue_job(today_cst(), trigger_type="scheduled")
    except RuntimeError:
        pass


def read_log_tail(job_id: str, tail: int = 200) -> list[str]:
    path = _log_path(job_id)
    if not path.exists():
        job = HistoryStore(DB_PATH).get_job(job_id)
        if job and job.get("log_path"):
            path = Path(job["log_path"])
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-tail:]
