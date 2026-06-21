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
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ts_common as tc
import ts_sectors as tsec
import ts_aggregate as agg
from train_track_store import TrainTrackStore, cache_rows_from_daily, turnover_map_from_basic
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


def fetch_stock_day(trade_date: str, name_map: dict[str, str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """daily + moneyflow → 个股当日指标（元）。返回 (stock, daily_raw)。"""
    daily_raw = tc.call_api(
        "daily",
        trade_date=trade_date,
        fields="ts_code,open,high,low,close,vol,amount,pct_chg",
    )
    daily = tc.daily_to_turnover(daily_raw)
    mf = tc.moneyflow_to_stock_flow(tc.call_api("moneyflow", trade_date=trade_date))
    if "trade_date" in mf.columns:
        mf = mf.drop(columns=["trade_date"])
    if daily.empty:
        return daily, daily_raw if daily_raw is not None else pd.DataFrame()
    stock = daily.drop(columns=[c for c in ("trade_date",) if c in daily.columns]).merge(
        mf, on="stock_code", how="left"
    )
    if name_map:
        stock["stock_name"] = stock["stock_code"].map(name_map)
    return stock, daily_raw if daily_raw is not None else pd.DataFrame()


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


def fetch_holders() -> pd.DataFrame:
    """拉取最近约 180 天公告的股东户数，取每股最近一期。"""
    today = datetime.now(CST)
    frames: list[pd.DataFrame] = []
    for i in range(6):  # 6 个 30 天窗口，规避单次 3000 行上限
        end = (today - timedelta(days=30 * i)).strftime("%Y%m%d")
        start = (today - timedelta(days=30 * (i + 1))).strftime("%Y%m%d")
        df = tc.call_api("stk_holdernumber", start_date=start, end_date=end)
        if df is not None and not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    return tc.latest_holder_numbers(pd.concat(frames, ignore_index=True))


def fetch_all_dividends() -> pd.DataFrame:
    """逐股拉取全市场分红，返回近 3 年已实施现金分红（dividend 接口不支持空参全市场）。"""
    sb = tc.call_api("stock_basic", list_status="L", fields="ts_code")
    if sb is None or sb.empty:
        return pd.DataFrame()
    codes = [str(c) for c in sb["ts_code"]]
    frames: list[pd.DataFrame] = []
    for i, code in enumerate(codes, 1):
        df = tc.call_api("dividend", ts_code=code, fields="ts_code,end_date,div_proc,cash_div_tax,ex_date")
        if df is not None and not df.empty:
            frames.append(df)
        if i % 500 == 0:
            print(f"  分红 {i}/{len(codes)} ...", flush=True)
    if not frames:
        return pd.DataFrame()
    return tc.recent_dividends(pd.concat(frames, ignore_index=True), years=3)


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


def process_day(
    store: TsStore,
    trade_date: str,
    mappings,
    *,
    do_etf: bool,
    etf_basic,
    name_map=None,
    tt_store: TrainTrackStore | None = None,
) -> None:
    print(f"==> 采集 {trade_date}", flush=True)
    stock, daily_raw = fetch_stock_day(trade_date, name_map)
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

    # 估值指标（股票清单页用）+ 火车轨缓存换手
    basic_raw = tc.call_api(
        "daily_basic",
        trade_date=trade_date,
        fields="ts_code,close,total_mv,pe,pe_ttm,pb,dv_ratio,dv_ttm,turnover_rate",
    )
    metrics = tc.daily_basic_to_metrics(basic_raw)
    store.upsert_valuation(trade_date, metrics, name_map)
    print(f"  估值指标 {len(metrics)} 只已落库", flush=True)

    if tt_store is not None:
        tr_map = turnover_map_from_basic(basic_raw)
        tt_rows = cache_rows_from_daily(daily_raw, tr_map, trade_date)
        tt_store.upsert_cache_rows(tt_rows)
        print(f"  火车轨缓存 {len(tt_rows)} 只已落库", flush=True)

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
    ap.add_argument("--mapping-only", action="store_true", help="只刷新四套行业映射（不采集当日行情）")
    ap.add_argument("--dividend-only", action="store_true", help="只预采全市场近3年分红（逐股，约15-20分钟）")
    args = ap.parse_args()

    tc.get_pro()  # 触发 token 校验

    if args.dividend_only:
        store = TsStore(DB_PATH)
        print("==> 预采全市场近 3 年分红（逐股，约 15–20 分钟）", flush=True)
        div = fetch_all_dividends()
        store.replace_dividends(div)
        print(f"==> 分红刷新完成，共 {len(div)} 条（涉及 {div['stock_code'].nunique() if not div.empty else 0} 只）", flush=True)
        return 0

    if args.mapping_only:
        store = TsStore(DB_PATH)
        td = args.date or _latest_trade_date()
        mk = [k.strip() for k in args.kinds.split(",")] if args.kinds else None
        mk = [k for k in mk if k in tsec.KINDS] if mk else None
        print(f"==> 仅刷新行业映射（trade_date={td}，kinds={mk or '全部'}）", flush=True)
        load_mappings(store, td, refresh=True, kinds=mk)
        # 周度同时刷新股东户数（季度数据）
        holders = fetch_holders()
        store.upsert_holders(holders)
        print(f"==> 股东数刷新 {len(holders)} 只；映射刷新完成", flush=True)
        return 0

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
    tt_store = TrainTrackStore(DB_PATH)
    print("==> 构建行业映射", flush=True)
    mappings = load_mappings(store, dates[-1], refresh=args.refresh_mapping, kinds=kinds)

    name_map = {}
    sb = tc.call_api("stock_basic", exchange="", list_status="L", fields="ts_code,name")
    if sb is not None and not sb.empty:
        name_map = dict(zip(sb["ts_code"].map(tc.ts_code_to_code6), sb["name"]))
    print(f"==> 个股名称 {len(name_map)} 条", flush=True)

    etf_basic = None
    if not args.no_etf:
        eb = tc.call_api("fund_basic", market="E", fields="ts_code,name")
        if eb is not None and not eb.empty:
            etf_basic = pd.DataFrame({"etf_code": eb["ts_code"].map(tc.ts_code_to_code6), "etf_name": eb["name"]})

    for d in dates:
        process_day(
            store,
            d,
            mappings,
            do_etf=not args.no_etf,
            etf_basic=etf_basic,
            name_map=name_map,
            tt_store=tt_store,
        )
    print("==> 完成", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
