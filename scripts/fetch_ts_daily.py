#!/usr/bin/env python3
"""Tushare 单日采集：daily + moneyflow → 四套行业聚合 + ETF。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from history_store import HistoryStore
from industry_common import aggregate_industry_sectors, assign_unmapped, sector_catalog
from sector_config import SECTOR_TABLE_KINDS
from ts_common import infer_snapshot_time, merge_etf_day, merge_stock_day

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "history.db"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Tushare 单日采集")
    p.add_argument("--date", help="YYYY-MM-DD，默认最近交易日")
    p.add_argument("--no-etf", action="store_true", help="跳过 ETF")
    p.add_argument("--no-db", action="store_true", help="不写 SQLite（当前版本未实现，保留占位）")
    p.add_argument("--job-id", help="关联 fetch_jobs")
    return p.parse_args()


def _update_job(job_id: str | None, **fields) -> None:
    if not job_id:
        return
    HistoryStore(DB_PATH).update_job(job_id, **fields)


def _prev_etf_shares(store: HistoryStore, trade_date: str) -> dict[str, float]:
    with store._connect() as conn:
        row = conn.execute(
            """
            SELECT MAX(trade_date) AS d FROM etf_daily
            WHERE trade_date < ?
            """,
            (trade_date,),
        ).fetchone()
        if not row or not row["d"]:
            return {}
        rows = conn.execute(
            "SELECT etf_code, total_share FROM etf_daily WHERE trade_date=? AND total_share IS NOT NULL",
            (row["d"],),
        ).fetchall()
    return {str(r["etf_code"]): float(r["total_share"]) for r in rows}


def _load_mapping(store: HistoryStore, kind: str) -> pd.DataFrame:
    with store._connect() as conn:
        return pd.read_sql_query(
            """
            SELECT sector_code, sector_name, sector_path, stock_code
            FROM industry_stock_map WHERE kind=?
            """,
            conn,
            params=(kind,),
        )


def fetch_one_day(
    trade_date: str,
    store: HistoryStore,
    *,
    include_etf: bool = True,
    job_id: str | None = None,
) -> dict[str, int]:
    from ts_common import get_pro

    pro = get_pro()
    _update_job(job_id, progress=f"daily:{trade_date}")

    stock_df = merge_stock_day(trade_date, pro=pro)
    if stock_df.empty:
        raise RuntimeError(f"{trade_date} 无 Tushare 个股数据")

    stock_df = stock_df[stock_df["stock_code"].astype(str).str.len() > 0].copy()
    for col in ("turnover", "active_buy", "active_sell", "main_buy", "main_sell"):
        if col in stock_df.columns:
            stock_df[col] = pd.to_numeric(stock_df[col], errors="coerce").fillna(0.0)

    market_row = {
        "turnover": float(stock_df["turnover"].sum()),
        "active_buy": float(stock_df["active_buy"].sum()) if "active_buy" in stock_df else 0.0,
        "active_sell": float(stock_df["active_sell"].sum()) if "active_sell" in stock_df else 0.0,
        "main_buy": float(stock_df["main_buy"].sum()) if "main_buy" in stock_df else 0.0,
        "main_sell": float(stock_df["main_sell"].sum()) if "main_sell" in stock_df else 0.0,
        "stock_count": len(stock_df),
    }

    sector_by_kind: dict[str, pd.DataFrame] = {}
    for kind in SECTOR_TABLE_KINDS:
        mapping = _load_mapping(store, kind)
        if mapping.empty:
            print(f"  警告: {kind} 映射为空，跳过聚合", flush=True)
            continue
        catalog = sector_catalog(mapping)
        sector_df = aggregate_industry_sectors(stock_df, mapping, catalog)
        sector_df = assign_unmapped(stock_df, mapping, sector_df)
        mkt_turn = market_row["turnover"]
        if mkt_turn > 0:
            sector_df["turnover_pct"] = sector_df["turnover"] / mkt_turn
        sector_by_kind[kind] = sector_df

    etf_df = pd.DataFrame()
    if include_etf:
        _update_job(job_id, progress=f"etf:{trade_date}")
        prev = _prev_etf_shares(store, trade_date)
        etf_df = merge_etf_day(trade_date, pro=pro, prev_shares=prev)

    snapshot_time = infer_snapshot_time().isoformat()
    store.upsert_ts_snapshot(
        trade_date=trade_date,
        stock_df=stock_df,
        sector_by_kind=sector_by_kind,
        market_row=market_row,
        etf_df=etf_df if include_etf else None,
        snapshot_time=snapshot_time,
    )
    return {
        "stocks": len(stock_df),
        "sectors": sum(len(df) for df in sector_by_kind.values()),
        "etfs": len(etf_df),
    }


def main() -> int:
    args = parse_args()
    store = HistoryStore(DB_PATH)

    trade_date = args.date
    if not trade_date:
        days = store.list_trading_days(1)
        if days:
            trade_date = days[-1]
        else:
            from trading_calendar import today_cst

            trade_date = today_cst()

    print(f"Tushare 采集 trade_date={trade_date}", flush=True)
    try:
        stats = fetch_one_day(
            trade_date,
            store,
            include_etf=not args.no_etf,
            job_id=args.job_id,
        )
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    if args.no_db:
        print("错误: --no-db 尚未实现", file=sys.stderr)
        return 1

    print(
        f"完成: 个股 {stats['stocks']}，板块行 {stats['sectors']}，ETF {stats['etfs']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
