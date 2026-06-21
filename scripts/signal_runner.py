"""后台信号扫描循环（15s）。"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_loop_thread: threading.Thread | None = None
_stop = threading.Event()
_scanner = None
_db_path: Path | None = None


def _get_scanner():
    global _scanner, _db_path
    if _scanner is None and _db_path is not None:
        from signal_scanner import SignalScanner

        _scanner = SignalScanner(_db_path)
    return _scanner


def _loop() -> None:
    while not _stop.is_set():
        try:
            scanner = _get_scanner()
            if scanner is not None:
                from signal_feed import parse_settings_signal, time_in_range
                from datetime import datetime
                from zoneinfo import ZoneInfo

                CST = ZoneInfo("Asia/Shanghai")
                settings = scanner._settings()
                cfg = parse_settings_signal(settings)
                now = datetime.now(CST)
                if cfg["enabled"] and time_in_range(now, cfg["sched_start"], cfg["sched_end"]):
                    scanner.scan_once()
        except Exception:
            logger.exception("signal scan failed")
        interval = 15
        try:
            scanner = _get_scanner()
            if scanner is not None:
                interval = parse_settings_signal(scanner._settings()).get("poll_interval_sec", 15)
        except Exception:
            pass
        _stop.wait(max(5, interval))


def start_signal_runner(db_path: str | Path) -> None:
    global _loop_thread, _db_path, _stop
    _db_path = Path(db_path)
    _stop.clear()
    if _loop_thread is not None and _loop_thread.is_alive():
        return
    _loop_thread = threading.Thread(target=_loop, name="signal-runner", daemon=True)
    _loop_thread.start()


def run_scan_once(*, force: bool = True) -> dict:
    scanner = _get_scanner()
    if scanner is None:
        raise RuntimeError("signal runner not started")
    return scanner.scan_once(force=force)
