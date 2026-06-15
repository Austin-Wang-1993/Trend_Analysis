"""Trend Analysis FastAPI 服务。"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
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
from job_worker import cancel_job, enqueue_job, is_job_running, read_log_tail, run_scheduled_fetch  # noqa: E402
from scheduler import compute_next_run, reload_scheduler, start_scheduler  # noqa: E402
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


def get_store() -> HistoryStore:
    global _store
    if _store is None:
        _store = HistoryStore(DB_PATH)
    return _store


class SettingsUpdate(BaseModel):
    schedule_enabled: bool | None = None
    schedule_time: str | None = None
    schedule_timezone: str | None = None
    schedule_run_mode: str | None = Field(default=None, pattern="^(trading_day|calendar_day)$")


class FetchRequest(BaseModel):
    start_date: str
    end_date: str


MAX_FETCH_TRADING_DAYS = 30


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


@app.on_event("startup")
def on_startup() -> None:
    store = get_store()
    year = datetime.now(CST).year
    sync_pmc_to_sqlite(DB_PATH, f"{year}-01-01", f"{year}-12-31")
    start_scheduler(store, run_scheduled_fetch)


# --- 公共 API ---

@app.get("/api/meta/trading-days")
def api_trading_days(days: int = Query(5, ge=1, le=30)) -> dict[str, Any]:
    store = get_store()
    trade_dates = store.list_trading_days(days)
    return {
        "days_requested": days,
        "days_actual": len(trade_dates),
        "trade_dates": trade_dates,
    }


@app.get("/api/market")
def api_market(days: int = Query(5, ge=1, le=30)) -> dict[str, Any]:
    return get_store().get_market_series(days)


@app.get("/api/sectors/table")
def api_sectors_table(
    days: int = Query(5, ge=1, le=30),
    sort: str = Query("pct_desc"),
) -> dict[str, Any]:
    return get_store().get_sector_table(days, sort=sort)


@app.get("/api/sectors/charts")
def api_sectors_charts(days: int = Query(5, ge=1, le=30)) -> list[dict[str, Any]]:
    return get_store().get_sector_charts(days)


@app.get("/api/sectors/{sector_code}/stocks")
def api_sector_stocks(sector_code: str, days: int = Query(5, ge=1, le=30)) -> dict[str, Any]:
    return get_store().get_sector_stocks(sector_code, days)


@app.get("/api/etf/table")
def api_etf_table(
    days: int = Query(5, ge=1, le=30),
    sort: str = Query("pct_desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=10, le=200),
    q: str = Query(""),
) -> dict[str, Any]:
    return get_store().get_etf_table(days, sort=sort, page=page, page_size=page_size, q=q)


@app.get("/api/etf/charts")
def api_etf_charts(
    days: int = Query(5, ge=1, le=30),
    top: int = Query(50, ge=1, le=500),
    q: str = Query(""),
) -> list[dict[str, Any]]:
    return get_store().get_etf_charts(days, top=top, q=q)


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
    updates = {k: str(v).lower() if isinstance(v, bool) else v for k, v in body.model_dump(exclude_none=True).items()}
    if "schedule_enabled" in updates:
        updates["schedule_enabled"] = "true" if updates["schedule_enabled"] in ("true", "True", True) else "false"
    settings = store.set_settings(updates)
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
    return FileResponse(path)


@app.get("/")
def page_index() -> FileResponse:
    return _html("index.html")


@app.get("/sectors-table.html")
def page_sectors_table() -> FileResponse:
    return _html("sectors-table.html")


@app.get("/sectors-charts.html")
def page_sectors_charts() -> FileResponse:
    return _html("sectors-charts.html")


@app.get("/sector-stocks.html")
def page_sector_stocks() -> FileResponse:
    return _html("sector-stocks.html")


@app.get("/etf-table.html")
def page_etf_table() -> FileResponse:
    return _html("etf-table.html")


@app.get("/etf-charts.html")
def page_etf_charts() -> FileResponse:
    return _html("etf-charts.html")


@app.get("/admin.html")
def page_admin() -> FileResponse:
    return _html("admin.html")


static_dir = DASHBOARD / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
