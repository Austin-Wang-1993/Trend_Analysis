#!/usr/bin/env python3
"""指定 trade_date 采集（当日走 fetch_by_daily，历史日走 K 线 + transaction）。"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from by_common import (
    ensure_stock_codes,
    fetch_etf_list,
    fetch_etf_turnover_batch,
    fetch_fund_flow_history,
    fetch_stock_kline_daily,
    fetch_stock_list,
    get_licence,
    pick_primary_sector,
)
from sector_config import DEFAULT_SECTOR_LEVEL, mapping_cache_name, primary_type2_for_level
from fetch_by_daily import (
    DATA_DIR,
    DB_PATH,
    aggregate_sector_turnover,
    load_or_build_mapping,
    load_or_build_tree,
    sectors_for_level,
)
from history_store import HistoryStore
from trading_calendar import is_trading_day, normalize_date, today_cst

CST = ZoneInfo("Asia/Shanghai")


def _job_cancelled(job_id: str | None) -> bool:
    if not job_id:
        return False
    job = HistoryStore(DB_PATH).get_job(job_id)
    return bool(job and job.get("status") == "cancelled")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="指定日采集")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--no-all-turnover", action="store_true")
    p.add_argument("--no-etf", action="store_true")
    p.add_argument("--job-id", help="关联 fetch_jobs")
    p.add_argument("--level", choices=["l1", "l2"], default=DEFAULT_SECTOR_LEVEL)
    return p.parse_args()


def _update_job(job_id: str | None, **fields) -> None:
    if not job_id:
        return
    store = HistoryStore(DB_PATH)
    store.update_job(job_id, **fields)


def fetch_historical_day(licence: str, trade_date: str, args: argparse.Namespace) -> int:
    """历史日：K 线成交额 + transaction(st/et) 买卖。"""
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

    rows: list[dict] = []
    codes = stocks_df["stock_code"].tolist()
    total = len(codes)
    td_compact = trade_date.replace("-", "")

    for idx, code in enumerate(codes, start=1):
        if _job_cancelled(job_id):
            print("  任务已取消，停止补数", flush=True)
            return 1
        if idx == 1 or idx % 200 == 0 or idx == total:
            print(f"  历史补数 {idx}/{total}...", flush=True)
        sec = sector_map.get(code, {})
        turnover = None
        try:
            klines = fetch_stock_kline_daily(licence, code, trade_date, trade_date)
            if klines:
                turnover = klines[0]["turnover"]
        except Exception:
            pass
        active_buy = active_sell = net_active = None
        try:
            ff = fetch_fund_flow_history(licence, code, lt=10)
            for r in ff:
                if r["trade_date"] == trade_date:
                    active_buy = r.get("active_buy")
                    active_sell = r.get("active_sell")
                    net_active = r.get("net_active")
                    break
        except Exception:
            pass
        if turnover is None and active_buy is None:
            continue
        rows.append(
            {
                "trade_date": trade_date,
                "stock_code": code,
                "stock_name": name_map.get(code),
                "sector_code": sec.get("sector_code"),
                "sector_name": sec.get("sector_name"),
                "turnover": turnover,
                "active_buy": active_buy,
                "active_sell": active_sell,
                "net_active": net_active,
            }
        )
        time.sleep(0.15)

    if not rows:
        raise RuntimeError(f"历史日 {trade_date} 无可用数据")

    store.upsert_stock_daily_rows(rows)
    snapshot_time = datetime.now(CST).isoformat()

    if not args.no_etf and trade_date == today_cst():
        etf_list = fetch_etf_list(licence)
        etf_turn = fetch_etf_turnover_batch(licence, etf_list["etf_code"].tolist())
        etf_df = etf_list.merge(etf_turn, on="etf_code", how="inner")
        stock_df = pd.DataFrame(rows)
        sector_df = aggregate_sector_turnover(stock_df.dropna(subset=["sector_code"]))
        store.upsert_snapshot(
            trade_date=trade_date,
            stock_df=stock_df,
            sector_df=sector_df,
            sector_ff_df=None,
            market_row=None,
            etf_df=etf_df,
            snapshot_time=snapshot_time,
        )
    return 0


def main() -> int:
    args = parse_args()
    trade_date = normalize_date(args.date)
    job_id = args.job_id
    started = datetime.now(CST).isoformat()
    _update_job(job_id, status="running", started_at=started, progress="starting")

    if not is_trading_day(trade_date):
        msg = f"{trade_date} 不是 A 股交易日（休市），已拒绝执行"
        _update_job(
            job_id,
            status="failed",
            error_message=msg,
            finished_at=datetime.now(CST).isoformat(),
            progress="rejected_non_trading_day",
        )
        print(f"错误: {msg}", file=sys.stderr)
        return 1

    try:
        licence = get_licence()
    except ValueError as exc:
        _update_job(job_id, status="failed", error_message=str(exc), finished_at=datetime.now(CST).isoformat())
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    try:
        if trade_date == today_cst():
            _update_job(job_id, progress="fetch_by_daily")
            from fetch_by_daily import main as daily_main

            sys.argv = ["fetch_by_daily.py", "--no-all-turnover", "--level", DEFAULT_SECTOR_LEVEL]
            if args.no_etf:
                sys.argv.append("--no-etf")
            rc = daily_main()
        else:
            _update_job(job_id, progress=f"historical:{trade_date}")
            rc = fetch_historical_day(licence, trade_date, args)

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
