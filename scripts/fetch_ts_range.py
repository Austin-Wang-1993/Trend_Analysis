#!/usr/bin/env python3
"""Tushare 区间补数：闭区间内全部 A 股交易日。"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_ts_daily import DB_PATH, fetch_one_day
from history_store import HistoryStore
from sector_config import MAX_FETCH_TRADING_DAYS
from trading_calendar import get_trading_days, is_trading_day, normalize_date, today_cst

CST = ZoneInfo("Asia/Shanghai")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Tushare 区间补数")
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument("--no-etf", action="store_true")
    p.add_argument("--job-id", help="关联 fetch_jobs")
    return p.parse_args()


def _update_job(job_id: str | None, **fields) -> None:
    if not job_id:
        return
    HistoryStore(DB_PATH).update_job(job_id, **fields)


def _job_cancelled(job_id: str | None) -> bool:
    if not job_id:
        return False
    job = HistoryStore(DB_PATH).get_job(job_id)
    return bool(job and job.get("status") == "cancelled")


def validate_range(start: str, end: str) -> list[str]:
    start_d = normalize_date(start)
    end_d = normalize_date(end)
    if start_d > end_d:
        raise ValueError("结束日期不能早于开始日期")
    if end_d > today_cst():
        raise ValueError("结束日期不能晚于今天")
    days = get_trading_days(start_d, end_d)
    if not days:
        raise ValueError("所选区间无 A 股交易日")
    if len(days) > MAX_FETCH_TRADING_DAYS:
        raise ValueError(f"区间内交易日过多（{len(days)}），单次最多 {MAX_FETCH_TRADING_DAYS} 个")
    if start_d == end_d and not is_trading_day(start_d):
        raise ValueError(f"{start_d} 不是 A 股交易日（休市），休市日无数据，请选择交易日")
    return days


def main() -> int:
    args = parse_args()
    job_id = args.job_id
    started = datetime.now(CST).isoformat()
    _update_job(job_id, status="running", started_at=started, progress="validating")

    try:
        trading_days = validate_range(args.start, args.end)
    except ValueError as exc:
        msg = str(exc)
        _update_job(
            job_id,
            status="failed",
            error_message=msg,
            finished_at=datetime.now(CST).isoformat(),
            progress="validation_failed",
        )
        print(f"错误: {msg}", file=sys.stderr)
        return 1

    start_d, end_d = trading_days[0], trading_days[-1]
    print(f"目标交易日 ({len(trading_days)}): {start_d} ~ {end_d}", flush=True)
    _update_job(job_id, progress=f"days {len(trading_days)}")

    store = HistoryStore(DB_PATH)
    try:
        from ts_common import get_token

        get_token()
    except ValueError as exc:
        _update_job(job_id, status="failed", error_message=str(exc), finished_at=datetime.now(CST).isoformat())
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    total = len(trading_days)
    for idx, td in enumerate(trading_days, start=1):
        if _job_cancelled(job_id):
            print("  任务已取消，停止补数", flush=True)
            return 1
        _update_job(job_id, progress=f"day {idx}/{total}:{td}")
        print(f"  [{idx}/{total}] {td} ...", flush=True)
        try:
            fetch_one_day(td, store, include_etf=not args.no_etf, job_id=job_id)
        except Exception as exc:
            _update_job(
                job_id,
                status="failed",
                error_message=str(exc),
                finished_at=datetime.now(CST).isoformat(),
                progress=f"failed:{td}",
            )
            print(f"错误: {exc}", file=sys.stderr)
            return 1

    finished = datetime.now(CST).isoformat()
    if _job_cancelled(job_id):
        return 1
    _update_job(job_id, status="success", finished_at=finished, progress="done")
    print("区间补数完成。", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
