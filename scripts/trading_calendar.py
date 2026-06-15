"""A 股交易日历：主用 pandas_market_calendars（SSE），必盈日 K 作校验/兜底。"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_market_calendars as mcal

CST = ZoneInfo("Asia/Shanghai")
CALENDAR_NAME = "SSE"  # 与 XSHG 等价，覆盖沪深 A 股休市规则
BIYING_ANCHOR = "000001.SZ"
RunMode = Literal["trading_day", "calendar_day"]

_cal: mcal.MarketCalendar | None = None


def get_calendar() -> mcal.MarketCalendar:
    global _cal
    if _cal is None:
        _cal = mcal.get_calendar(CALENDAR_NAME)
    return _cal


def normalize_date(value: str | date | datetime | pd.Timestamp) -> str:
    """统一为 YYYY-MM-DD。"""
    if isinstance(value, str):
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    if isinstance(value, datetime):
        return value.astimezone(CST).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def today_cst() -> str:
    return datetime.now(CST).date().isoformat()


def is_trading_day(value: str | date | datetime | pd.Timestamp) -> bool:
    d = normalize_date(value)
    cal = get_calendar()
    return len(cal.schedule(start_date=d, end_date=d)) == 1


def get_trading_days(
    start: str | date | datetime | pd.Timestamp,
    end: str | date | datetime | pd.Timestamp,
) -> list[str]:
    start_d = normalize_date(start)
    end_d = normalize_date(end)
    if start_d > end_d:
        raise ValueError(f"start {start_d} 不能晚于 end {end_d}")
    cal = get_calendar()
    sched = cal.schedule(start_date=start_d, end_date=end_d)
    return [ts.strftime("%Y-%m-%d") for ts in sched.index]


def get_recent_trading_days(
    n: int,
    *,
    end: str | date | datetime | pd.Timestamp | None = None,
) -> list[str]:
    if n <= 0:
        raise ValueError("n 必须为正整数")
    end_d = normalize_date(end or today_cst())
    # 预留足够自然日窗口以覆盖 n 个交易日（含长假）
    start_guess = (pd.Timestamp(end_d) - pd.Timedelta(days=max(n * 3, 14))).strftime("%Y-%m-%d")
    days = get_trading_days(start_guess, end_d)
    if len(days) < n:
        # 窗口不够则再往前扩
        start_guess = (pd.Timestamp(end_d) - pd.Timedelta(days=n * 5)).strftime("%Y-%m-%d")
        days = get_trading_days(start_guess, end_d)
    return days[-n:]


def should_run_scheduled_task(
    run_mode: RunMode,
    *,
    on_date: str | date | datetime | pd.Timestamp | None = None,
) -> bool:
    """调度器用：calendar_day 每天跑；trading_day 仅交易日跑。"""
    if run_mode == "calendar_day":
        return True
    return is_trading_day(on_date or today_cst())


def fetch_biying_trading_days(
    licence: str,
    start: str | date,
    end: str | date,
    *,
    anchor: str = BIYING_ANCHOR,
) -> list[str]:
    """必盈日 K 提取交易日（校验/兜底，需网络）。"""
    from by_common import _get, API_BASE

    st = normalize_date(start).replace("-", "")
    et = normalize_date(end).replace("-", "")
    rows = _get(
        f"{API_BASE}/hsstock/history/{anchor}/d/n/{licence}",
        params={"st": st, "et": et},
    )
    if not isinstance(rows, list):
        return []
    out: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        t = str(row.get("t", ""))
        if len(t) >= 10:
            out.add(t[:10])
    return sorted(out)


def compare_with_biying(
    licence: str,
    start: str | date,
    end: str | date,
) -> dict[str, list[str] | bool]:
    """对比 PMC 与必盈日 K 交易日列表。"""
    pmc = get_trading_days(start, end)
    biying = fetch_biying_trading_days(licence, start, end)
    only_pmc = sorted(set(pmc) - set(biying))
    only_biying = sorted(set(biying) - set(pmc))
    return {
        "match": pmc == biying,
        "pmc_count": len(pmc),
        "biying_count": len(biying),
        "only_pmc": only_pmc,
        "only_biying": only_biying,
        "pmc": pmc,
        "biying": biying,
    }


def ensure_trading_calendar_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_calendar (
            trade_date TEXT PRIMARY KEY,
            is_trading INTEGER NOT NULL,
            source     TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def sync_pmc_to_sqlite(
    db_path: str | Path,
    start: str | date,
    end: str | date,
) -> int:
    """将 PMC 交易日写入 SQLite（可选缓存，供 history_store / 管理页使用）。"""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    start_d = normalize_date(start)
    end_d = normalize_date(end)
    now = datetime.now(CST).isoformat()

    trading = set(get_trading_days(start_d, end_d))
    all_days: list[str] = []
    cur = pd.Timestamp(start_d)
    end_ts = pd.Timestamp(end_d)
    while cur <= end_ts:
        all_days.append(cur.strftime("%Y-%m-%d"))
        cur += pd.Timedelta(days=1)

    conn = sqlite3.connect(db_path)
    try:
        ensure_trading_calendar_table(conn)
        rows = [(d, 1 if d in trading else 0, "pmc_sse", now) for d in all_days]
        conn.executemany(
            """
            INSERT INTO trading_calendar (trade_date, is_trading, source, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(trade_date) DO UPDATE SET
                is_trading=excluded.is_trading,
                source=excluded.source,
                updated_at=excluded.updated_at
            """,
            rows,
        )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A 股交易日历（pandas_market_calendars SSE）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_recent = sub.add_parser("recent", help="最近 N 个交易日")
    p_recent.add_argument("--days", type=int, default=5)
    p_recent.add_argument("--end", help="结束日期 YYYY-MM-DD，默认今天")

    p_is = sub.add_parser("is-trading", help="判断是否交易日")
    p_is.add_argument("date", help="YYYY-MM-DD")

    p_list = sub.add_parser("list", help="列出区间内交易日")
    p_list.add_argument("--start", required=True)
    p_list.add_argument("--end", required=True)

    p_verify = sub.add_parser("verify", help="对比 PMC 与必盈日 K")
    p_verify.add_argument("--start", required=True)
    p_verify.add_argument("--end", required=True)

    p_sync = sub.add_parser("sync-db", help="PMC 写入 SQLite trading_calendar 表")
    p_sync.add_argument("db_path", help="如 data/history.db")
    p_sync.add_argument("--start", required=True)
    p_sync.add_argument("--end", required=True)

    return parser.parse_args()


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    args = parse_args()

    if args.command == "recent":
        days = get_recent_trading_days(args.days, end=args.end)
        print(f"最近 {args.days} 个交易日（截至 {args.end or today_cst()}）:")
        for d in days:
            print(f"  {d}")
        return 0

    if args.command == "is-trading":
        ok = is_trading_day(args.date)
        print(f"{normalize_date(args.date)}: {'交易日' if ok else '休市'}")
        return 0

    if args.command == "list":
        days = get_trading_days(args.start, args.end)
        print(f"{args.start} ~ {args.end}: {len(days)} 个交易日")
        for d in days:
            print(d)
        return 0

    if args.command == "verify":
        from by_common import get_licence

        try:
            licence = get_licence()
        except ValueError as exc:
            print(f"错误: {exc}", file=sys.stderr)
            return 1
        result = compare_with_biying(licence, args.start, args.end)
        print(f"PMC({result['pmc_count']}) vs 必盈({result['biying_count']}): match={result['match']}")
        if not result["match"]:
            if result["only_pmc"]:
                print(f"  仅 PMC: {result['only_pmc']}")
            if result["only_biying"]:
                print(f"  仅必盈: {result['only_biying']}")
            return 1
        return 0

    if args.command == "sync-db":
        n = sync_pmc_to_sqlite(args.db_path, args.start, args.end)
        print(f"已写入/更新 {n} 条到 {args.db_path}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
