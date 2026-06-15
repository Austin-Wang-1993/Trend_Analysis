#!/usr/bin/env python3
"""回填近 N 交易日买卖数据（history/transaction?lt=N）并写入 history.db。"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from by_common import (
    ensure_stock_codes,
    fetch_fund_flow_history,
    fetch_stock_kline_daily,
    fetch_stock_list,
    get_licence,
    pick_primary_sector,
)
from sector_config import mapping_cache_name, primary_type2_for_level
from history_store import HistoryStore
from trading_calendar import get_recent_trading_days

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "history.db"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="回填近 N 日 A 股买卖 + 成交额")
    p.add_argument("--days", type=int, default=5, help="回填交易日数（默认 5）")
    p.add_argument("--with-kline", action="store_true", help="逐股拉日 K 补成交额（慢，5200+ 请求）")
    p.add_argument("--sleep", type=float, default=0.21, help="逐股请求间隔秒")
    p.add_argument("--progress-every", type=int, default=100)
    return p.parse_args()


def load_mapping() -> pd.DataFrame:
    cache = DATA_DIR / "cache" / mapping_cache_name("l2")
    if not cache.exists():
        raise FileNotFoundError(f"缺少映射缓存 {cache}，请先运行 fetch_by_daily.py")
    return ensure_stock_codes(pd.DataFrame(json.loads(cache.read_text(encoding="utf-8"))))


def main() -> int:
    args = parse_args()
    try:
        licence = get_licence()
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    target_days = get_recent_trading_days(args.days)
    if not target_days:
        print("错误: 无法计算目标交易日", file=sys.stderr)
        return 1
    start, end = target_days[0], target_days[-1]
    print(f"目标交易日 ({len(target_days)}): {start} ~ {end}")

    stocks_df = ensure_stock_codes(fetch_stock_list(licence))
    mapping_df = load_mapping()
    primary_df = pick_primary_sector(mapping_df, type2=primary_type2_for_level("l2"))
    name_map = dict(zip(stocks_df["stock_code"], stocks_df["stock_name"]))
    sector_map = primary_df.set_index("stock_code")[["sector_code", "sector_name"]].to_dict("index")

    store = HistoryStore(DB_PATH)
    all_rows: list[dict] = []
    codes = stocks_df["stock_code"].tolist()
    total = len(codes)

    for idx, code in enumerate(codes, start=1):
        if idx == 1 or idx % args.progress_every == 0 or idx == total:
            print(f"  资金流 {idx}/{total}...", flush=True)
        try:
            ff_rows = fetch_fund_flow_history(licence, code, lt=args.days)
            turnover_by_date: dict[str, float] = {}
            if args.with_kline:
                klines = fetch_stock_kline_daily(licence, code, start, end)
                turnover_by_date = {r["trade_date"]: r["turnover"] for r in klines}
            for row in ff_rows:
                td = row["trade_date"]
                if td not in target_days:
                    continue
                sec = sector_map.get(code, {})
                all_rows.append(
                    {
                        "trade_date": td,
                        "stock_code": code,
                        "stock_name": name_map.get(code),
                        "sector_code": sec.get("sector_code"),
                        "sector_name": sec.get("sector_name"),
                        "turnover": turnover_by_date.get(td),
                        "active_buy": row.get("active_buy"),
                        "active_sell": row.get("active_sell"),
                        "net_active": row.get("net_active"),
                    }
                )
        except Exception as exc:
            if idx <= 3:
                print(f"    警告 [{code}]: {exc}")
        time.sleep(args.sleep)

    if not all_rows:
        print("错误: 未获取到任何回填数据", file=sys.stderr)
        return 1

    print(f"写入 {len(all_rows)} 条 stock_daily 记录...")
    store.upsert_stock_daily_rows(all_rows)
    dates_in_db = store.list_trading_days(args.days)
    print(f"完成。库内近 {args.days} 日: {dates_in_db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
