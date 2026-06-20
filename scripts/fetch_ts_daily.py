"""v4.0 采集编排（Tushare）：daily + moneyflow + 四套行业聚合 + ETF。

替代 v3.6 的 fetch_by_daily.py（必盈）。落库到 ts_store（*_v4 表）。

用法：
  python3 scripts/fetch_ts_daily.py                  # 默认最近交易日
  python3 scripts/fetch_ts_daily.py --date 20250613  # 指定单日
  python3 scripts/fetch_ts_daily.py --start 20250601 --end 20250613   # 区间
  python3 scripts/fetch_ts_daily.py --refresh-mapping # 强制刷新四套映射
  python3 scripts/fetch_ts_daily.py --no-etf          # 跳过 ETF
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ts_common as tc
import ts_sectors as tsec
import ts_aggregate as agg
from ts_store import TsStore

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "history.db"
CST = ZoneInfo("Asia/Shanghai")


def _latest_trade_date() -> str:
    """最近交易日（YYYYMMDD），用 trade_cal。"""
    today = datetime.now(CST).strftime("%Y%m%d")
    start = (datetime.now(CST).replace(month=1, day=1)).strftime("%Y%m%d")
    cal = tc.call_api("trade_cal", exchange="SSE", start_date=start, end_date=today, is_open="1")
    if cal is None or cal.empty:
        return today
    return str(sorted(cal["cal_date"].astype(str))[-1])


def _trading_days_in_range(start: str, end: str) -> list[str]:
    cal = tc.call_api("trade_cal", exchange="SSE", start_date=start, end_date=end, is_open="1")
    if cal is None or cal.empty:
        return []
    return sorted(cal["cal_date"].astype(str))


def fetch_stock_day(trade_date: str) -> pd.DataFrame:
    """daily + moneyflow → 个股当日指标（元）。"""
    daily = tc.daily_to_turnover(tc.call_api("daily", trade_date=trade_date, fields="ts_code,amount,pct_chg"))
    mf = tc.moneyflow_to_stock_flow(tc.call_api("moneyflow", trade_date=trade_date))
    if "trade_date" in mf.columns:
        mf = mf.drop(columns=["trade_date"])
    if daily.empty:
        return daily
    stock = daily.drop(columns=[c for c in ("trade_date",) if c in daily.columns]).merge(
        mf, on="stock_code", how="left"
    )
    return stock


def fetch_etf_day(trade_date: str, market_turnover: float, basic: pd.DataFrame) -> pd.DataFrame:
    """fund_daily + fund_share → ETF 当日。"""
    fd = tc.fund_daily_to_turnover(tc.call_api("fund_daily", trade_date=trade_date, fields="ts_code,amount,pct_chg"))
    if fd.empty:
        return fd
    if basic is not None and not basic.empty:
        nm = dict(zip(basic["etf_code"], basic["etf_name"]))
        fd["etf_name"] = fd["etf_code"].map(nm)
    share = tc.call_api("fund_share", trade_date=trade_date)
    if share is not None and not share.empty:
        share = share.copy()
        share["etf_code"] = share["ts_code"].map(tc.ts_code_to_code6)
        share_map = dict(zip(share["etf_code"], pd.to_numeric(share["fd_share"], errors="coerce")))
        fd["fd_share"] = fd["etf_code"].map(share_map)
    else:
        fd["fd_share"] = None
    fd["turnover_pct"] = fd["turnover"] / market_turnover if market_turnover > 0 else None
    return fd


def load_mappings(store: TsStore, trade_date: str, *, refresh: bool, kinds=None) -> dict[str, tuple[pd.DataFrame, pd.DataFrame]]:
    """四套映射：构建/缓存并写入 store。trade_date 供东财使用。"""
    out: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    for kind in (kinds or tsec.KINDS):
        td = trade_date if kind == "dc_ind" else None
        mapping, catalog = tsec.build_mapping(kind, trade_date=td, refresh=refresh)
        store.upsert_mapping(kind, mapping, catalog)
        out[kind] = (mapping, catalog)
        print(f"  [{kind}] 映射 {len(mapping)} 股 / {len(catalog)} 行业", flush=True)
    return out


def process_day(store: TsStore, trade_date: str, mappings, *, do_etf: bool, etf_basic) -> None:
    print(f"==> 采集 {trade_date}", flush=True)
    stock = fetch_stock_day(trade_date)
    if stock.empty:
        print(f"  {trade_date} 无 daily 数据（休市或未更新），跳过", flush=True)
        return
    up, down, flat = tc.count_up_down(stock["pct_chg"])
    market = agg.aggregate_market(stock)
    market.update({"up_count": up, "down_count": down, "flat_count": flat})
    snapshot = datetime.now(CST).isoformat()

    store.upsert_stocks(trade_date, stock)
    store.upsert_market(trade_date, market, snapshot)
    for kind, (mapping, catalog) in mappings.items():
        sector_df = agg.aggregate_sector(stock, mapping, catalog, market, include_unmapped=True)
        store.upsert_sectors(trade_date, kind, sector_df)
    print(f"  全A 成交 {market['turnover']/1e8:.0f}亿 涨/跌 {up}/{down}；四套行业已聚合", flush=True)

    if do_etf:
        etf = fetch_etf_day(trade_date, market["turnover"], etf_basic)
        store.upsert_etfs(trade_date, etf)
        print(f"  ETF {len(etf)} 只已落库", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="v4.0 Tushare 采集")
    ap.add_argument("--date", help="单日 YYYYMMDD")
    ap.add_argument("--start", help="区间起 YYYYMMDD")
    ap.add_argument("--end", help="区间止 YYYYMMDD")
    ap.add_argument("--refresh-mapping", action="store_true", help="强制刷新四套映射")
    ap.add_argument("--no-etf", action="store_true", help="跳过 ETF")
    ap.add_argument("--kinds", help="仅处理指定体系（逗号分隔，如 sw_l3,ci_l3）；默认四套全做")
    args = ap.parse_args()

    tc.get_pro()  # 触发 token 校验

    if args.start and args.end:
        dates = _trading_days_in_range(args.start, args.end)
    elif args.date:
        dates = [args.date]
    else:
        dates = [_latest_trade_date()]
    if not dates:
        print("无交易日可采集", file=sys.stderr)
        return 1
    print(f"待采集交易日（{len(dates)}）：{dates[0]} ~ {dates[-1]}", flush=True)

    kinds = None
    if args.kinds:
        kinds = [k.strip() for k in args.kinds.split(",") if k.strip() in tsec.KINDS]
        if not kinds:
            print(f"--kinds 无有效体系（可选 {tsec.KINDS}）", file=sys.stderr)
            return 1

    store = TsStore(DB_PATH)
    print("==> 构建行业映射", flush=True)
    mappings = load_mappings(store, dates[-1], refresh=args.refresh_mapping, kinds=kinds)

    etf_basic = None
    if not args.no_etf:
        eb = tc.call_api("fund_basic", market="E", fields="ts_code,name")
        if eb is not None and not eb.empty:
            etf_basic = pd.DataFrame({"etf_code": eb["ts_code"].map(tc.ts_code_to_code6), "etf_name": eb["name"]})

    for d in dates:
        process_day(store, d, mappings, do_etf=not args.no_etf, etf_basic=etf_basic)
    print("==> 完成", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
