"""Trend Analysis FastAPI 服务。"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "history.db"
DASHBOARD = ROOT / "dashboard"

sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "api"))

from history_store import HistoryStore  # noqa: E402
from accum_pattern_store import ACCUM_PATTERN_SETTINGS_DEFAULTS  # noqa: E402
from ts_store import TsStore  # noqa: E402
from ts_sectors import KINDS as TS_KINDS  # noqa: E402
from job_worker import cancel_job, enqueue_job, is_job_running, read_log_tail, run_scheduled_fetch  # noqa: E402
from scheduler import compute_next_run, reload_scheduler, start_scheduler  # noqa: E402
from signal_runner import run_scan_once, start_signal_runner  # noqa: E402
from signal_scanner import SignalScanner  # noqa: E402
from train_track_scanner import TrainTrackScanner  # noqa: E402
from train_track_runner import enqueue_train_track_scan, get_scan_status  # noqa: E402
from td_sequential_scanner import TdSequentialScanner  # noqa: E402
from td_sequential_runner import enqueue_td_scan, get_scan_status as get_td_scan_status  # noqa: E402
from accum_pattern_scanner import AccumPatternScanner  # noqa: E402
from accum_pattern_runner import enqueue_accum_scan, get_scan_status as get_accum_scan_status  # noqa: E402
from trading_calendar import compare_with_biying, get_trading_days, is_trading_day, normalize_date, sync_pmc_to_sqlite, today_cst  # noqa: E402

CST = ZoneInfo("Asia/Shanghai")

app = FastAPI(title="Trend Analysis", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_store: HistoryStore | None = None
_ts_store: TsStore | None = None
_signal_scanner: SignalScanner | None = None
_train_track_scanner: TrainTrackScanner | None = None
_td_sequential_scanner: TdSequentialScanner | None = None
_accum_pattern_scanner: AccumPatternScanner | None = None

# v4.0 行业 kind 校验（申万三级/中信三级/东财/同花顺）
KIND_PATTERN = "^(" + "|".join(TS_KINDS) + ")$"


def get_store() -> HistoryStore:
    global _store
    if _store is None:
        _store = HistoryStore(DB_PATH)
    return _store


def get_ts_store() -> TsStore:
    """v4.0 数据访问层（看板公共 API 使用）。"""
    global _ts_store
    if _ts_store is None:
        _ts_store = TsStore(DB_PATH)
    return _ts_store


class SettingsUpdate(BaseModel):
    schedule_enabled: bool | None = None
    schedule_time: str | None = None
    schedule_timezone: str | None = None
    schedule_run_mode: str | None = Field(default=None, pattern="^(trading_day|calendar_day)$")
    signal_enabled: bool | None = None
    signal_poll_interval_sec: int | None = Field(default=None, ge=5, le=120)
    signal_sched_start: str | None = None
    signal_sched_end: str | None = None
    signal_window_start: str | None = None
    signal_window_end: str | None = None
    signal_pct_threshold: float | None = Field(default=None, ge=0, le=30)
    signal_engulf_mode: str | None = Field(default=None, pattern="^(high|body)$")
    signal_cross_body_ratio: float | None = Field(default=None, ge=0, le=1)
    signal_long_upper_ratio: float | None = Field(default=None, ge=0, le=10)
    signal_data_stale_sec: int | None = Field(default=None, ge=30, le=600)
    train_track_enabled: bool | None = None
    train_track_time: str | None = None
    train_track_history_days: int | None = Field(default=None, ge=200, le=300)
    train_track_default_limit: int | None = Field(default=None, ge=1, le=500)
    train_track_rps_sum_min: float | None = None
    train_track_near_high_250_min: float | None = Field(default=None, ge=0.5, le=1.0)
    train_track_drawdown_20_max: float | None = Field(default=None, ge=0.05, le=0.5)
    train_track_turnover_max: float | None = Field(default=None, ge=1, le=50)
    train_track_count_ma250_30_min: int | None = Field(default=None, ge=1, le=30)
    train_track_count_ma200_30_min: int | None = Field(default=None, ge=1, le=30)
    train_track_count_ma20_10_min: int | None = Field(default=None, ge=1, le=10)
    train_track_count_ma10_4_min: int | None = Field(default=None, ge=1, le=4)
    train_track_count_ma20_4_min: int | None = Field(default=None, ge=1, le=4)
    train_track_ma_rise_days: int | None = Field(default=None, ge=2, le=20)
    train_track_recent_20d_pct_max: float | None = Field(default=None, ge=5, le=200)
    train_track_ma_touch_band_pct: float | None = Field(default=None, ge=0.5, le=10)
    td_enabled: bool | None = None
    td_time: str | None = None
    td_history_days: int | None = Field(default=None, ge=60, le=250)
    td_lookback_days: int | None = Field(default=None, ge=5, le=60)
    td_vol_shrink_ratio: float | None = Field(default=None, ge=0.1, le=1.0)
    td_vol_expand_ratio: float | None = Field(default=None, ge=1.0, le=3.0)
    td_shadow_lower_min: float | None = Field(default=None, ge=0, le=1.0)
    td_cross_body_max: float | None = Field(default=None, ge=0, le=1.0)
    td_bear_lower_max: float | None = Field(default=None, ge=0, le=1.0)
    td_vol_price_mode: str | None = Field(default=None, pattern="^(or|and)$")
    td_countdown_near_min: int | None = Field(default=None, ge=1, le=12)
    td_countdown_near_max: int | None = Field(default=None, ge=1, le=13)
    td_countdown_after_setup_days: int | None = Field(default=None, ge=1, le=30)
    td_macd_fast: int | None = Field(default=None, ge=5, le=20)
    td_macd_slow: int | None = Field(default=None, ge=10, le=40)
    td_macd_signal: int | None = Field(default=None, ge=3, le=20)
    td_macd_valley_close_pct: float | None = Field(default=None, ge=0.01, le=1.0)
    td_macd_ref_valley_max: int | None = Field(default=None, ge=1, le=5)
    td_macd_ref_valley_min: int | None = Field(default=None, ge=1, le=5)
    td_macd_div_ref: str | None = Field(default=None, pattern="^(hist|dif|both)$")
    td_stop_loss_pct: float | None = Field(default=None, ge=0.01, le=0.1)
    accum_enabled: bool | None = None
    accum_time: str | None = None
    accum_history_days: int | None = Field(default=None, ge=60, le=250)
    accum_vol_expand_trigger: float | None = Field(default=None, ge=1.0, le=5.0)
    accum_vol_expand_start: float | None = Field(default=None, ge=1.0, le=5.0)
    accum_vol_expand_decay: float | None = Field(default=None, ge=0.0, le=1.0)
    accum_vol_expand_floor: float | None = Field(default=None, ge=1.0, le=3.0)
    accum_vol_expand_max_consecutive_miss: int | None = Field(default=None, ge=1, le=10)
    accum_vol_min_days: int | None = Field(default=None, ge=3, le=30)
    accum_price_rise_min: float | None = Field(default=None, ge=0.05, le=2.0)
    accum_wash_mult: float | None = Field(default=None, ge=1.0, le=5.0)
    accum_vol_shrink_max: float | None = Field(default=None, ge=1.0, le=2.0)
    accum_vol_wash_max_consecutive_over: int | None = Field(default=None, ge=1, le=5)
    accum_vol_reset_trigger: float | None = Field(default=None, ge=1.5, le=5.0)
    accum_drawdown_min: float | None = Field(default=None, ge=0.1, le=1.0)
    accum_drawdown_max: float | None = Field(default=None, ge=0.1, le=1.0)


class FetchRequest(BaseModel):
    start_date: str
    end_date: str


MAX_FETCH_TRADING_DAYS = 400


def _validate_fetch_range(start_date: str, end_date: str) -> tuple[str, str, list[str]]:
    """校验区间并返回 (start, end, trading_days)。"""
    start_d = normalize_date(start_date)
    end_d = normalize_date(end_date)
    if start_d > end_d:
        raise HTTPException(status_code=400, detail="结束日期不能早于开始日期")
    if end_d > today_cst():
        raise HTTPException(status_code=400, detail="结束日期不能晚于今天")
    try:
        days = get_trading_days(start_d, end_d)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not days:
        raise HTTPException(status_code=400, detail="所选区间无 A 股交易日")
    if len(days) > MAX_FETCH_TRADING_DAYS:
        raise HTTPException(
            status_code=400,
            detail=f"区间内交易日过多（{len(days)}），单次最多 {MAX_FETCH_TRADING_DAYS} 个",
        )
    if start_d == end_d and not is_trading_day(start_d):
        raise HTTPException(
            status_code=400,
            detail=f"{start_d} 不是 A 股交易日（休市），休市日无数据，请选择交易日",
        )
    return start_d, end_d, days


def _preview_fetch_range(start_date: str, end_date: str) -> dict[str, Any]:
    start_d = normalize_date(start_date)
    end_d = normalize_date(end_date)
    try:
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
        return {
            "start_date": start_d,
            "end_date": end_d,
            "trading_day_count": len(days),
            "trading_days": days,
            "valid": True,
            "error": None,
        }
    except ValueError as exc:
        return {
            "start_date": start_d,
            "end_date": end_d,
            "trading_day_count": 0,
            "trading_days": [],
            "valid": False,
            "error": str(exc),
        }


class CalendarSyncRequest(BaseModel):
    start: str
    end: str


class CalendarVerifyRequest(BaseModel):
    start: str
    end: str


def get_signal_scanner() -> SignalScanner:
    global _signal_scanner
    if _signal_scanner is None:
        _signal_scanner = SignalScanner(DB_PATH, get_settings=get_store().get_settings)
    return _signal_scanner


def get_train_track_scanner() -> TrainTrackScanner:
    global _train_track_scanner
    if _train_track_scanner is None:
        _train_track_scanner = TrainTrackScanner(DB_PATH, get_settings=get_store().get_settings)
    return _train_track_scanner


def get_td_sequential_scanner() -> TdSequentialScanner:
    global _td_sequential_scanner
    if _td_sequential_scanner is None:
        _td_sequential_scanner = TdSequentialScanner(DB_PATH, get_settings=get_store().get_settings)
    return _td_sequential_scanner


def get_accum_pattern_scanner() -> AccumPatternScanner:
    global _accum_pattern_scanner
    if _accum_pattern_scanner is None:
        _accum_pattern_scanner = AccumPatternScanner(DB_PATH, get_settings=get_store().get_settings)
    return _accum_pattern_scanner


@app.on_event("startup")
def on_startup() -> None:
    store = get_store()
    year = datetime.now(CST).year
    sync_pmc_to_sqlite(DB_PATH, f"{year}-01-01", f"{year}-12-31")
    start_scheduler(store, run_scheduled_fetch)
    start_signal_runner(DB_PATH)
    get_signal_scanner().store.init_schema()
    get_train_track_scanner().store.init_schema()
    get_td_sequential_scanner().store.init_schema()
    get_accum_pattern_scanner().store.init_schema()
    store.ensure_settings_defaults(ACCUM_PATTERN_SETTINGS_DEFAULTS)


# --- 公共 API（v4.0：Tushare 四套行业，days 支持 5/15/30）---

@app.get("/api/meta/trading-days")
def api_trading_days(days: int = Query(5, ge=1, le=60)) -> dict[str, Any]:
    trade_dates = get_ts_store().list_trading_days(days)
    return {
        "days_requested": days,
        "days_actual": len(trade_dates),
        "trade_dates": trade_dates,
    }


@app.get("/api/market")
def api_market(days: int = Query(5, ge=1, le=60)) -> dict[str, Any]:
    return get_ts_store().get_market_series(days)


@app.get("/api/sectors/table")
def api_sectors_table(
    days: int = Query(5, ge=1, le=60),
    sort: str = Query("turnover_pct_desc"),
    kind: str = Query("sw_l3", pattern=KIND_PATTERN),
) -> dict[str, Any]:
    return get_ts_store().get_sector_table(days, sort=sort, kind=kind)


@app.get("/api/sectors/charts")
def api_sectors_charts(
    days: int = Query(5, ge=1, le=60),
    kind: str = Query("sw_l3", pattern=KIND_PATTERN),
) -> list[dict[str, Any]]:
    return get_ts_store().get_sector_charts(days, kind=kind)


@app.get("/api/sectors/{sector_code}/stocks")
def api_sector_stocks(
    sector_code: str,
    days: int = Query(5, ge=1, le=60),
    sort: str = Query("turnover_pct_desc"),
    kind: str = Query("sw_l3", pattern=KIND_PATTERN),
) -> dict[str, Any]:
    return get_ts_store().get_sector_stocks(sector_code, days, sort=sort, kind=kind)


@app.get("/api/stocks/{stock_code}/series")
def api_stock_series(
    stock_code: str,
    days: int = Query(5, ge=1, le=60),
    sector: str | None = Query(None),
    kind: str | None = Query(None),
) -> dict[str, Any]:
    return get_ts_store().get_stock_series(stock_code, days)


@app.get("/api/etf/table")
def api_etf_table(
    days: int = Query(5, ge=1, le=60),
    sort: str = Query("turnover_pct_desc"),
) -> dict[str, Any]:
    return get_ts_store().get_etf_table(days, sort=sort)


@app.get("/api/etfs/{etf_code}/series")
def api_etf_series(
    etf_code: str,
    days: int = Query(5, ge=1, le=60),
) -> dict[str, Any]:
    return get_ts_store().get_etf_series(etf_code, days)


@app.get("/api/stocks/list")
def api_stock_list(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    sort: str = Query("total_mv"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    q: str = Query(""),
    sectors: str = Query("", description="申万三级 sector_code，逗号分隔，多选"),
) -> dict[str, Any]:
    sector_list = [s.strip() for s in sectors.split(",") if s.strip()] or None
    return get_ts_store().get_stock_list(
        page=page, page_size=page_size, sort=sort, order=order, q=q, sectors=sector_list
    )


@app.get("/api/sectors/catalog")
def api_sector_catalog(kind: str = Query("sw_l3", pattern=KIND_PATTERN)) -> list[dict[str, Any]]:
    return get_ts_store().get_sector_catalog(kind)


@app.get("/api/signals/meta")
def api_signals_meta() -> dict[str, Any]:
    return get_signal_scanner().get_meta()


@app.get("/api/signals/today")
def api_signals_today(min_score: int = Query(1, ge=0, le=2)) -> dict[str, Any]:
    trade_date = today_cst()
    items = get_signal_scanner().store.list_hits(trade_date, min_score=min_score)
    meta = get_signal_scanner().get_meta()
    return {"trade_date": trade_date, "items": items, "meta": meta}


@app.post("/api/admin/signals/scan")
def admin_signals_scan() -> dict[str, Any]:
    try:
        return run_scan_once(force=True)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/train-track/meta")
def api_train_track_meta() -> dict[str, Any]:
    return get_train_track_scanner().meta()


@app.get("/api/train-track/picks")
def api_train_track_picks(
    limit: int | None = Query(None, ge=1, le=500),
    sort: str = Query("rps250"),
    all_rows: bool = Query(False, alias="all"),
) -> dict[str, Any]:
    scanner = get_train_track_scanner()
    meta = scanner.meta()
    td = meta["trade_date"]
    if all_rows:
        lim = None
    elif limit is not None:
        lim = limit
    else:
        lim = meta.get("default_limit", 20)
    items = scanner.store.list_picks(td, limit=lim, sort=sort)
    return {"trade_date": td, "items": items, "meta": meta}


@app.get("/api/train-track/scan/status")
def api_train_track_scan_status(job_id: str | None = Query(None)) -> dict[str, Any]:
    return get_scan_status(job_id)


@app.post("/api/admin/train-track/scan")
def admin_train_track_scan() -> dict[str, Any]:
    try:
        result = enqueue_train_track_scan(trigger_type="manual")
        return {"ok": True, **result}
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/td-sequential/meta")
def api_td_sequential_meta() -> dict[str, Any]:
    return get_td_sequential_scanner().meta()


@app.get("/api/td-sequential/board")
def api_td_sequential_board(trade_date: str | None = Query(None)) -> dict[str, Any]:
    return get_td_sequential_scanner().board(trade_date)


@app.get("/api/td-sequential/stocks/{stock_code}")
def api_td_sequential_stock(
    stock_code: str,
    trade_date: str | None = Query(None),
) -> dict[str, Any]:
    detail = get_td_sequential_scanner().stock_detail(stock_code, trade_date)
    if detail is None:
        raise HTTPException(status_code=404, detail="未找到该股的九转序列")
    return detail


@app.get("/api/td-sequential/scan/status")
def api_td_sequential_scan_status(job_id: str | None = Query(None)) -> dict[str, Any]:
    return get_td_scan_status(job_id)


@app.post("/api/admin/td-sequential/scan")
def admin_td_sequential_scan() -> dict[str, Any]:
    try:
        result = enqueue_td_scan(trigger_type="manual")
        return {"ok": True, **result}
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/accum-pattern/meta")
def api_accum_pattern_meta() -> dict[str, Any]:
    return get_accum_pattern_scanner().meta()


@app.get("/api/accum-pattern/picks")
def api_accum_pattern_picks(
    trade_date: str | None = Query(None),
    phase: str | None = Query(None, pattern="^(wash_in_progress|wash_complete)$"),
) -> dict[str, Any]:
    return get_accum_pattern_scanner().picks(trade_date, phase=phase)


@app.get("/api/accum-pattern/stocks/{stock_code}")
def api_accum_pattern_stock(
    stock_code: str,
    trade_date: str | None = Query(None),
) -> dict[str, Any]:
    detail = get_accum_pattern_scanner().stock_detail(stock_code, trade_date)
    if detail is None:
        raise HTTPException(status_code=404, detail="未找到该股的量价吸筹形态")
    return detail


@app.get("/api/accum-pattern/diagnose")
def api_accum_pattern_diagnose(
    stock_code: str = Query(..., min_length=6, max_length=6, pattern=r"^\d{6}$"),
    t0_date: str = Query(..., description="T₀ 放量触发日 YYYY-MM-DD"),
    scan_date: str | None = Query(None, description="扫描/观察日，默认最近交易日"),
) -> dict[str, Any]:
    code = stock_code.strip()
    t0 = normalize_date(t0_date)
    scan = normalize_date(scan_date) if scan_date else None
    if not is_trading_day(t0):
        raise HTTPException(status_code=400, detail=f"{t0} 不是交易日")
    if scan and not is_trading_day(scan):
        raise HTTPException(status_code=400, detail=f"{scan} 不是交易日")
    return get_accum_pattern_scanner().diagnose(code, t0_date=t0, scan_date=scan)


@app.get("/api/accum-pattern/scan/status")
def api_accum_pattern_scan_status(job_id: str | None = Query(None)) -> dict[str, Any]:
    return get_accum_scan_status(job_id)


@app.post("/api/admin/accum-pattern/scan")
def admin_accum_pattern_scan() -> dict[str, Any]:
    try:
        result = enqueue_accum_scan(trigger_type="manual")
        return {"ok": True, **result}
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# --- 管理 API ---

@app.get("/api/admin/settings")
def admin_get_settings() -> dict[str, Any]:
    store = get_store()
    settings = store.get_settings()
    meta = compute_next_run(settings)
    return {**settings, **meta}


@app.put("/api/admin/settings")
def admin_put_settings(body: SettingsUpdate) -> dict[str, Any]:
    store = get_store()
    updates = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    for bool_key in ("schedule_enabled", "signal_enabled", "train_track_enabled", "td_enabled", "accum_enabled"):
        if bool_key in updates:
            updates[bool_key] = "true" if updates[bool_key] else "false"
    settings = store.set_settings({k: str(v) for k, v in updates.items()})
    reload_scheduler(store, run_scheduled_fetch)
    return {**settings, **compute_next_run(settings)}


@app.post("/api/admin/fetch")
def admin_fetch(body: FetchRequest) -> dict[str, Any]:
    if is_job_running():
        raise HTTPException(status_code=409, detail="已有任务运行中")
    start_d, end_d, days = _validate_fetch_range(body.start_date, body.end_date)
    try:
        job_id = enqueue_job(start_d, trigger_type="manual", end_date=end_d)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "job_id": job_id,
        "status": "pending",
        "start_date": start_d,
        "end_date": end_d,
        "trading_day_count": len(days),
    }


@app.get("/api/admin/fetch-preview")
def admin_fetch_preview(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
) -> dict[str, Any]:
    return _preview_fetch_range(start, end)


@app.get("/api/admin/trading-day")
def admin_trading_day(date: str = Query(..., description="YYYY-MM-DD")) -> dict[str, Any]:
    d = normalize_date(date)
    return {"trade_date": d, "is_trading_day": is_trading_day(d)}


@app.get("/api/admin/jobs")
def admin_list_jobs(
    limit: int = Query(20, ge=1, le=100),
    status: str | None = None,
) -> list[dict[str, Any]]:
    return get_store().list_jobs(limit=limit, status=status)


@app.get("/api/admin/jobs/{job_id}")
def admin_get_job(job_id: str) -> dict[str, Any]:
    job = get_store().get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    job = dict(job)
    job["log_tail"] = read_log_tail(job_id, tail=200)
    return job


@app.get("/api/admin/jobs/{job_id}/log")
def admin_job_log(job_id: str, tail: int = Query(200, ge=1, le=2000)) -> dict[str, Any]:
    return {"lines": read_log_tail(job_id, tail=tail)}


@app.post("/api/admin/jobs/{job_id}/retry")
def admin_retry_job(job_id: str) -> dict[str, str]:
    job = get_store().get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if is_job_running():
        raise HTTPException(status_code=409, detail="已有任务运行中")
    start_d = job["trade_date"]
    end_d = job.get("end_date") or start_d
    start_d, end_d, _ = _validate_fetch_range(start_d, end_d)
    new_id = enqueue_job(start_d, trigger_type="manual", end_date=end_d)
    return {"job_id": new_id, "status": "pending", "start_date": start_d, "end_date": end_d}


@app.post("/api/admin/jobs/{job_id}/cancel")
def admin_cancel_job(job_id: str) -> dict[str, str]:
    try:
        cancel_job(job_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"job_id": job_id, "status": "cancelled"}


@app.get("/api/admin/calendar")
def admin_calendar() -> dict[str, Any]:
    return {"dates": get_store().get_data_calendar()}


@app.get("/api/admin/export/{trade_date}")
def admin_export(trade_date: str) -> Response:
    data = get_store().export_zip(trade_date)
    filename = f"trend_analysis_{trade_date}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/admin/calendar/sync-db")
def admin_calendar_sync(body: CalendarSyncRequest) -> dict[str, Any]:
    n = sync_pmc_to_sqlite(DB_PATH, body.start, body.end)
    return {"updated": n}


@app.post("/api/admin/calendar/verify")
def admin_calendar_verify(body: CalendarVerifyRequest) -> dict[str, Any]:
    from by_common import get_licence

    try:
        licence = get_licence()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return compare_with_biying(licence, body.start, body.end)


# --- 静态页面 ---

def _html(name: str) -> FileResponse:
    path = DASHBOARD / name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"页面不存在: {name}")
    return FileResponse(
        path,
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@app.get("/")
def page_index() -> FileResponse:
    return _html("index.html")


@app.get("/sectors-table.html")
def page_sectors_table() -> FileResponse:
    return _html("sectors-table.html")


@app.get("/sectors-charts.html")
def page_sectors_charts() -> FileResponse:
    return _html("sectors-charts.html")


@app.get("/stock-detail.html")
def page_stock_detail() -> FileResponse:
    return _html("stock-detail.html")


@app.get("/sector-stocks.html")
def page_sector_stocks() -> FileResponse:
    return _html("sector-stocks.html")


@app.get("/stock-list.html")
def page_stock_list() -> FileResponse:
    return _html("stock-list.html")


@app.get("/signals.html")
def page_signals() -> FileResponse:
    return _html("signals.html")


@app.get("/train-track.html")
def page_train_track() -> FileResponse:
    return _html("train-track.html")


@app.get("/td-sequential.html")
def page_td_sequential() -> FileResponse:
    return _html("td-sequential.html")


@app.get("/td-sequential-detail.html")
def page_td_sequential_detail() -> FileResponse:
    return _html("td-sequential-detail.html")


@app.get("/accum-pattern.html")
def page_accum_pattern() -> FileResponse:
    return _html("accum-pattern.html")


@app.get("/accum-pattern-detail.html")
def page_accum_pattern_detail() -> FileResponse:
    return _html("accum-pattern-detail.html")


@app.get("/etf-table.html")
def page_etf_table() -> FileResponse:
    return _html("etf-table.html")


@app.get("/etf-detail.html")
def page_etf_detail() -> FileResponse:
    return _html("etf-detail.html")


@app.get("/etf-charts.html")
def page_etf_charts() -> RedirectResponse:
    return RedirectResponse(url="/etf-table.html", status_code=302)


@app.get("/admin.html")
def page_admin() -> FileResponse:
    return _html("admin.html")


static_dir = DASHBOARD / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
