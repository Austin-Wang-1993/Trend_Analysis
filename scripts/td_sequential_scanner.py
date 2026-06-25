"""神奇九转全 A 扫描。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

import pandas as pd

import ts_common as tc
from td_sequential_common import (
    cache_days_required,
    evaluate_stock_td,
    min_bars_required,
    parse_td_params,
)
from td_sequential_store import TdSequentialStore
from train_track_common import is_st_name
from train_track_store import TrainTrackStore, cache_rows_from_daily, turnover_map_from_basic
from trading_calendar import get_recent_trading_days, is_trading_day, today_cst

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]

ProgressCallback = Callable[[str, int, int], None]


class TdSequentialScanner:
    def __init__(self, db_path: str | Path, *, get_settings: Any | None = None) -> None:
        self.db_path = Path(db_path)
        self.store = TdSequentialStore(db_path)
        self.cache_store = TrainTrackStore(db_path)
        self._get_settings = get_settings
        self._sector_map: dict[str, str] | None = None

    def _settings(self) -> dict[str, str]:
        if self._get_settings is None:
            from history_store import HistoryStore

            return HistoryStore(self.db_path).get_settings()
        return self._get_settings()

    def _load_sector_map(self) -> dict[str, str]:
        if self._sector_map is not None:
            return self._sector_map
        mapping: dict[str, str] = {}
        try:
            with self.cache_store._conn() as conn:
                rows = conn.execute(
                    """SELECT stock_code, sector_path FROM sector_stock_map_v4
                       WHERE kind='sw_l3' AND sector_path IS NOT NULL"""
                ).fetchall()
            for r in rows:
                mapping[str(r["stock_code"])] = str(r["sector_path"])
        except Exception:
            logger.debug("sector map unavailable", exc_info=True)
        self._sector_map = mapping
        return mapping

    def _universe(self, trade_date: str) -> tuple[dict[str, str], set[str]]:
        basic = tc.call_api(
            "stock_basic",
            exchange="",
            list_status="L",
            fields="ts_code,name",
        )
        names: dict[str, str] = {}
        if basic is not None and not basic.empty:
            for _, r in basic.iterrows():
                code = tc.ts_code_to_code6(str(r["ts_code"]))
                if is_st_name(r.get("name")):
                    continue
                names[code] = str(r.get("name") or "")
        suspended: set[str] = set()
        susp = tc.call_api("suspend_d", trade_date=trade_date.replace("-", ""))
        if susp is not None and not susp.empty:
            suspended = {tc.ts_code_to_code6(str(x)) for x in susp["ts_code"]}
        return names, suspended

    def _ensure_cache(
        self,
        trade_dates: list[str],
        *,
        progress: ProgressCallback | None = None,
    ) -> None:
        cached = set(self.cache_store.list_cached_dates())
        missing = [d for d in trade_dates if d not in cached]
        total = len(trade_dates)
        done = sum(1 for d in trade_dates if d in cached)
        if progress:
            progress("cache", done, total)
        for i, d in enumerate(missing, start=1):
            compact = d.replace("-", "")
            daily = tc.call_api(
                "daily",
                trade_date=compact,
                fields="ts_code,open,high,low,close,vol",
            )
            basic = tc.call_api(
                "daily_basic",
                trade_date=compact,
                fields="ts_code,turnover_rate",
            )
            rows = cache_rows_from_daily(daily, turnover_map_from_basic(basic), d)
            self.cache_store.upsert_cache_rows(rows)
            logger.info("td cache %s: %d rows", d, len(rows))
            if progress:
                progress("cache", done + i, total)

    def _resolve_scan_date(self, trade_date: str | None) -> str:
        td = trade_date or today_cst()
        if is_trading_day(td):
            return td
        recent = get_recent_trading_days(1, end=td)
        return recent[-1] if recent else td

    def scan(
        self,
        *,
        trade_date: str | None = None,
        progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        settings = self._settings()
        params = parse_td_params(settings)
        hist_days = int(settings.get("td_history_days", "120"))
        td = self._resolve_scan_date(trade_date)
        if not is_trading_day(td):
            return {"skipped": True, "reason": "non_trading_day", "trade_date": td}

        names, suspended = self._universe(td)
        need_days = cache_days_required(hist_days)
        dates = get_recent_trading_days(need_days, end=td)
        if len(dates) < min_bars_required():
            msg = f"交易日不足（需要至少 {need_days}，当前 {len(dates)}）"
            self.store.set_scan_log(td, universe_count=0, error=msg)
            return {"skipped": True, "reason": msg, "trade_date": td}

        lookback_dates = get_recent_trading_days(params.lookback_days, end=td)
        window_start = lookback_dates[0] if lookback_dates else td

        self._ensure_cache(dates, progress=progress)
        self.cache_store.prune_cache_before(dates[0])

        if progress:
            progress("compute", 0, 1)

        rows = self.cache_store.load_cache_panel(dates)
        if not rows:
            self.store.set_scan_log(td, universe_count=len(names), error="缓存为空")
            return {"skipped": True, "reason": "empty_cache", "trade_date": td}

        df_all = pd.DataFrame(rows)
        sector_map = self._load_sector_map()
        picks: list[dict[str, Any]] = []
        funnel: dict[str, int] = {
            "evaluated": 0,
            "col1_setup9": 0,
            "col2_vol_price": 0,
            "col3_near13": 0,
            "col4_cd13": 0,
            "col5_macd_div": 0,
            "vol_price_reject_expand_bear": 0,
            "missing_vol": 0,
        }

        for code in df_all["stock_code"].unique():
            if code not in names or code in suspended:
                continue
            sub = df_all[df_all["stock_code"] == code].copy()
            if len(sub) < min_bars_required():
                continue
            funnel["evaluated"] += 1
            sub["stock_name"] = names.get(code, "")
            ev = evaluate_stock_td(
                sub,
                scan_date=td,
                window_start=window_start,
                params=params,
            )
            if ev is None:
                continue
            if ev.get("vol_price_rejected_bear"):
                funnel["vol_price_reject_expand_bear"] += 1
            if ev.get("setup_9_vol") is None and ev.get("setup_9_turnover_rate") is None:
                funnel["missing_vol"] += 1
            if ev.get("col1_setup9"):
                funnel["col1_setup9"] += 1
            if ev.get("col2_vol_price"):
                funnel["col2_vol_price"] += 1
            if ev.get("col3_near13"):
                funnel["col3_near13"] += 1
            if ev.get("col4_cd13"):
                funnel["col4_cd13"] += 1
            if ev.get("col5_macd_div"):
                funnel["col5_macd_div"] += 1
            picks.append(
                {
                    "stock_code": code,
                    "stock_name": names.get(code, ""),
                    "sector_path": sector_map.get(code, ""),
                    **{k: v for k, v in ev.items() if k != "detail"},
                }
            )

        self.store.replace_picks(td, picks)
        self.store.set_scan_log(
            td,
            universe_count=len(names) - len(suspended),
            error=None,
            funnel=funnel,
        )
        if progress:
            progress("compute", 1, 1)
        return {
            "skipped": False,
            "trade_date": td,
            "pick_count": len(picks),
            "universe_count": len(names) - len(suspended),
            "lookback_days": params.lookback_days,
            "window_start": window_start,
            "funnel": funnel,
        }

    def board(self, trade_date: str | None = None) -> dict[str, Any]:
        settings = self._settings()
        params = parse_td_params(settings)
        td = self._resolve_scan_date(trade_date)
        log = self.store.get_scan_log(td) or {}
        funnel = None
        if log.get("funnel_json"):
            try:
                funnel = json.loads(log["funnel_json"])
            except json.JSONDecodeError:
                funnel = None
        columns: dict[str, list[dict[str, Any]]] = {}
        for col in range(1, 6):
            items = self.store.list_picks_by_col(td, col)
            for it in items:
                it.pop("detail_json", None)
            columns[str(col)] = items
        return {
            "trade_date": td,
            "lookback_days": params.lookback_days,
            "funnel": funnel,
            "columns": columns,
            "last_scan_at": log.get("last_scan_at"),
            "last_error": log.get("error_message"),
        }

    def stock_detail(self, stock_code: str, trade_date: str | None = None) -> dict[str, Any] | None:
        td = self._resolve_scan_date(trade_date)
        row = self.store.get_pick(td, stock_code)
        if row and row.get("detail_json"):
            try:
                detail = json.loads(row["detail_json"])
                detail["from_cache"] = True
                return detail
            except json.JSONDecodeError:
                pass
        settings = self._settings()
        params = parse_td_params(settings)
        hist_days = int(settings.get("td_history_days", "120"))
        dates = get_recent_trading_days(cache_days_required(hist_days), end=td)
        lookback_dates = get_recent_trading_days(params.lookback_days, end=td)
        window_start = lookback_dates[0] if lookback_dates else td
        rows = self.cache_store.load_cache_panel(dates)
        sub = pd.DataFrame([r for r in rows if r["stock_code"] == stock_code])
        if sub.empty:
            return None
        names, _ = self._universe(td)
        sub["stock_name"] = names.get(stock_code, "")
        ev = evaluate_stock_td(sub, scan_date=td, window_start=window_start, params=params)
        if ev is None:
            return None
        detail = ev.get("detail", {})
        detail["from_cache"] = False
        return detail

    def meta(self) -> dict[str, Any]:
        settings = self._settings()
        params = parse_td_params(settings)
        td = self._resolve_scan_date(None)
        log = self.store.get_scan_log(td) or {}
        funnel = None
        if log.get("funnel_json"):
            try:
                funnel = json.loads(log["funnel_json"])
            except json.JSONDecodeError:
                funnel = None
        active = self.store.get_active_scan_job()
        latest = self.store.get_latest_scan_job()
        cache_dates = self.cache_store.list_cached_dates()
        hist_days = int(settings.get("td_history_days", "120"))
        return {
            "trade_date": td,
            "is_trading_day": is_trading_day(today_cst()),
            "enabled": settings.get("td_enabled", "true").lower() == "true",
            "scan_time": settings.get("td_time", "16:45"),
            "lookback_days": params.lookback_days,
            "last_scan_at": log.get("last_scan_at"),
            "last_error": log.get("error_message"),
            "funnel": funnel,
            "cache_day_count": len(cache_dates),
            "cache_days_required": cache_days_required(hist_days),
            "scan_job": active or latest,
            "settings_meta": self.store.get_settings_meta(),
        }
