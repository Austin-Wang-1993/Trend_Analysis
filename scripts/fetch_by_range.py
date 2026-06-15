#!/usr/bin/env python3
"""区间补数：闭区间内全部 A 股交易日，按股 st/et 拉买卖 + 日 K 成交额。"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

from by_common import (
    ensure_stock_codes,
    fetch_fund_flow_history,
    fetch_stock_kline_daily,
    fetch_stock_list,
    get_licence,
    pick_primary_sector,
)
from fetch_by_daily import DATA_DIR, DB_PATH, load_or_build_mapping, load_or_build_tree, sectors_for_level
from history_store import HistoryStore
from sector_config import DEFAULT_SECTOR_LEVEL, mapping_cache_name, primary_type2_for_level
from trading_calendar import get_trading_days, is_trading_day, normalize_date, today_cst

CST = ZoneInfo("Asia/Shanghai")
MAX_TRADING_DAYS = 30


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="区间补数（开始/结束必填，相等=单日）")
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument("--no-all-turnover", action="store_true")
    p.add_argument("--no-etf", action="store_true")
    p.add_argument("--job-id", help="关联 fetch_jobs")
    p.add_argument("--level", choices=["l1", "l2"], default=DEFAULT_SECTOR_LEVEL)
    p.add_argument("--sleep", type=float, default=0.15, help="逐股请求间隔秒")
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
    if len(days) > MAX_TRADING_DAYS:
        raise ValueError(f"区间内交易日过多（{len(days)}），单次最多 {MAX_TRADING_DAYS} 个")
    if start_d == end_d and not is_trading_day(start_d):
        raise ValueError(f"{start_d} 不是 A 股交易日（休市），休市日无数据，请选择交易日")
    return days


def _run_single_day(args: argparse.Namespace, trade_date: str) -> int:
    from fetch_by_date import main as fetch_by_date_main

    sys.argv = [
        "fetch_by_date.py",
        "--date",
        trade_date,
        "--no-all-turnover",
        "--level",
        args.level,
    ]
    if args.no_etf:
        sys.argv.append("--no-etf")
    if args.job_id:
        sys.argv.extend(["--job-id", args.job_id])
    return fetch_by_date_main()


def fetch_range(licence: str, trading_days: list[str], args: argparse.Namespace) -> int:
    job_id = args.job_id
    store = HistoryStore(DB_PATH)
    cache_name = mapping_cache_name(args.level)
    tree_cache = DATA_DIR / "cache" / "sector_tree.json"
    tree_df = load_or_build_tree(licence, tree_cache, refresh=False)
    sectors_df = sectors_for_level(tree_df, args.level)
    mapping_df = load_or_build_mapping(licence, sectors_df, refresh=False, cache_name=cache_name)
    stocks_df = ensure_stock_codes(fetch_stock_list(licence))
    primary_df = pick_primary_sector(mapping_df, type2=primary_type2_for_level(args.level))
    name_map = dict(zip(stocks_df["stock_code"], stocks_df["stock_name"]))
    sector_map = primary_df.set_index("stock_code")[["sector_code", "sector_name"]].to_dict("index")

    day_set = set(trading_days)
    st, et = trading_days[0], trading_days[-1]
    codes = stocks_df["stock_code"].tolist()
    total = len(codes)
    all_rows: list[dict] = []

    for idx, code in enumerate(codes, start=1):
        if _job_cancelled(job_id):
            print("  任务已取消，停止补数", flush=True)
            return 1
        if idx == 1 or idx % 200 == 0 or idx == total:
            _update_job(job_id, progress=f"stocks {idx}/{total}")
            print(f"  区间补数 {idx}/{total}...", flush=True)

        sec = sector_map.get(code, {})
        turnover_by_date: dict[str, float] = {}
        flow_by_date: dict[str, dict] = {}

        try:
            for row in fetch_stock_kline_daily(licence, code, st, et):
                td = row["trade_date"]
                if td in day_set:
                    turnover_by_date[td] = row["turnover"]
        except Exception:
            pass

        try:
            for row in fetch_fund_flow_history(licence, code, st=st, et=et):
                td = row["trade_date"]
                if td in day_set:
                    flow_by_date[td] = row
        except Exception:
            pass

        dates_for_code = day_set & (set(turnover_by_date) | set(flow_by_date))
        for td in sorted(dates_for_code):
            ff = flow_by_date.get(td, {})
            all_rows.append(
                {
                    "trade_date": td,
                    "stock_code": code,
                    "stock_name": name_map.get(code),
                    "sector_code": sec.get("sector_code"),
                    "sector_name": sec.get("sector_name"),
                    "turnover": turnover_by_date.get(td),
                    "active_buy": ff.get("active_buy"),
                    "active_sell": ff.get("active_sell"),
                    "net_active": ff.get("net_active"),
                }
            )
        time.sleep(args.sleep)

    if not all_rows:
        raise RuntimeError(f"区间 {st} ~ {et} 无可用数据")

    print(f"写入 {len(all_rows)} 条 stock_daily...", flush=True)
    store.upsert_stock_daily_rows(all_rows)

    today = today_cst()
    historical = [d for d in trading_days if d != today]
    if historical:
        print(f"重聚合 {len(historical)} 个历史交易日...", flush=True)
        store.rebuild_aggregates_for_dates(set(historical))

    if today in day_set and not args.no_etf:
        print(f"区间含今日 {today}，执行 fetch_by_daily 补 ETF 与当日快照...", flush=True)
        _update_job(job_id, progress="fetch_by_daily:today")
        from fetch_by_daily import main as daily_main

        sys.argv = ["fetch_by_daily.py", "--no-all-turnover", "--level", args.level]
        rc = daily_main()
        if rc != 0:
            return rc
    elif today in day_set:
        store.rebuild_aggregates_for_dates({today})
    else:
        store.rebuild_aggregates_for_dates(set(trading_days))

    return 0


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

    try:
        licence = get_licence()
    except ValueError as exc:
        _update_job(job_id, status="failed", error_message=str(exc), finished_at=datetime.now(CST).isoformat())
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    try:
        if len(trading_days) == 1:
            _update_job(job_id, progress=f"single:{trading_days[0]}")
            rc = _run_single_day(args, trading_days[0])
        else:
            rc = fetch_range(licence, trading_days, args)

        finished = datetime.now(CST).isoformat()
        if _job_cancelled(job_id):
            return 1
        if rc == 0:
            _update_job(job_id, status="success", finished_at=finished, progress="done")
        else:
            _update_job(job_id, status="failed", finished_at=finished, progress="failed")
        return rc
    except Exception as exc:
        if _job_cancelled(job_id):
            return 1
        _update_job(
            job_id,
            status="failed",
            error_message=str(exc),
            finished_at=datetime.now(CST).isoformat(),
        )
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
