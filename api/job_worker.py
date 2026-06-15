"""后台采集任务执行。"""

from __future__ import annotations

import os
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
_current_proc: subprocess.Popen[str] | None = None
_current_job_id: str | None = None


def _log_path(job_id: str) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / f"{job_id}.log"


def is_job_running() -> bool:
    with _lock:
        return _running


def get_running_job_id() -> str | None:
    with _lock:
        return _current_job_id if _running else None


def _terminate_proc(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def run_job(
    job_id: str,
    start_date: str,
    *,
    end_date: str | None = None,
    trigger_type: str = "manual",
) -> None:
    global _running, _current_proc, _current_job_id
    end = end_date or start_date
    store = HistoryStore(DB_PATH)
    log_file = _log_path(job_id)
    store.update_job(job_id, log_path=str(log_file), status="running", started_at=datetime.now(CST).isoformat())

    with open(log_file, "a", encoding="utf-8") as lf:
        lf.write(f"[{datetime.now(CST).isoformat()}] start job={job_id} range={start_date}~{end}\n")
        lf.flush()
        t0 = time.time()
        proc: subprocess.Popen[str] | None = None
        try:
            proc = subprocess.Popen(
                [
                    sys.executable,
                    str(SCRIPTS / "fetch_by_range.py"),
                    "--start",
                    start_date,
                    "--end",
                    end,
                    "--no-all-turnover",
                    "--level",
                    "l2",
                    "--job-id",
                    job_id,
                ],
                cwd=str(ROOT),
                stdout=lf,
                stderr=subprocess.STDOUT,
                env=_job_env(),
            )
            with _lock:
                _current_proc = proc
                _current_job_id = job_id

            returncode = proc.wait()
            duration = time.time() - t0
            job = store.get_job(job_id) or {}

            if job.get("status") == "cancelled":
                lf.write(f"[{datetime.now(CST).isoformat()}] cancelled duration={duration:.1f}s\n")
            elif returncode == 0 and job.get("status") != "failed":
                store.update_job(
                    job_id,
                    status="success",
                    finished_at=datetime.now(CST).isoformat(),
                    duration_sec=duration,
                    progress="done",
                )
                lf.write(f"[{datetime.now(CST).isoformat()}] exit=0 duration={duration:.1f}s\n")
            elif job.get("status") != "cancelled":
                store.update_job(
                    job_id,
                    status="failed",
                    finished_at=datetime.now(CST).isoformat(),
                    duration_sec=duration,
                    progress="failed",
                )
                lf.write(f"[{datetime.now(CST).isoformat()}] exit={returncode} duration={duration:.1f}s\n")
        except Exception as exc:
            job = store.get_job(job_id) or {}
            if job.get("status") != "cancelled":
                store.update_job(
                    job_id,
                    status="failed",
                    error_message=str(exc),
                    finished_at=datetime.now(CST).isoformat(),
                )
            lf.write(f"[{datetime.now(CST).isoformat()}] error: {exc}\n")
        finally:
            if proc and proc.poll() is None:
                _terminate_proc(proc)
            with _lock:
                _running = False
                _current_proc = None
                _current_job_id = None


def _job_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("PYTHONPATH", str(SCRIPTS))
    return env


def enqueue_job(
    start_date: str,
    trigger_type: str = "manual",
    *,
    end_date: str | None = None,
) -> str:
    global _running
    end = end_date or start_date
    with _lock:
        if _running:
            raise RuntimeError("已有任务运行中")
        _running = True
    store = HistoryStore(DB_PATH)
    job_id = store.create_job(start_date, trigger_type, end_date=end)

    def _worker() -> None:
        run_job(job_id, start_date, end_date=end, trigger_type=trigger_type)

    threading.Thread(target=_worker, daemon=True).start()
    return job_id


def cancel_job(job_id: str) -> None:
    """取消 pending / running 任务。"""
    store = HistoryStore(DB_PATH)
    job = store.get_job(job_id)
    if not job:
        raise RuntimeError("任务不存在")
    if job["status"] in ("success", "failed", "cancelled"):
        raise RuntimeError(f"任务已结束（{job['status']}），无法取消")

    now = datetime.now(CST).isoformat()
    store.update_job(
        job_id,
        status="cancelled",
        finished_at=now,
        progress="user_cancelled",
        error_message="用户取消",
    )

    log_file = _log_path(job_id)
    with open(log_file, "a", encoding="utf-8") as lf:
        lf.write(f"[{now}] cancel requested by user\n")

    with _lock:
        if _current_job_id == job_id and _current_proc is not None:
            _terminate_proc(_current_proc)


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
        today = today_cst()
        job_id = store.create_job(today, "scheduled", end_date=today)
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
        today = today_cst()
        enqueue_job(today, trigger_type="scheduled", end_date=today)
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
