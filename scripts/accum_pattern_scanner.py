"""量价吸筹全 A 扫描。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

import pandas as pd

import ts_common as tc
from accum_pattern_common import (
    cache_days_required,
    diagnose_stock_accum,
    evaluate_stock_accum,
    min_bars_required,
    parse_accum_params,
)
from accum_pattern_store import AccumPatternStore, cache_rows_from_daily_adj
from train_track_common import is_st_name
from trading_calendar import get_recent_trading_days, is_trading_day, today_cst

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]

ProgressCallback = Callable[[str, int, int], None]


class AccumPatternScanner:
    def __init__(self, db_path: str | Path, *, get_settings: Any | None = None) -> None:
        self.db_path = Path(db_path)
        self.store = AccumPatternStore(db_path)
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
            with self.store._conn() as conn:
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
        cached = set(self.store.list_cached_dates())
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
                fields="ts_code,open,close,vol",
            )
            adj = tc.call_api(
                "adj_factor",
                trade_date=compact,
                fields="ts_code,adj_factor",
            )
            rows = cache_rows_from_daily_adj(daily, adj, d)
            self.store.upsert_cache_rows(rows)
            logger.info("accum cache %s: %d rows", d, len(rows))
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
        params = parse_accum_params(settings)
        hist_days = int(settings.get("accum_history_days", "120"))
        td = self._resolve_scan_date(trade_date)
        if not is_trading_day(td):
            return {"skipped": True, "reason": "non_trading_day", "trade_date": td}

        names, suspended = self._universe(td)
        need_days = cache_days_required(hist_days)
        dates = get_recent_trading_days(need_days, end=td)
        if len(dates) < min_bars_required():
            msg = f"交易日不足（需要至少 {need_days}，当前 {len(dates)}）"
            self.store.set_scan_log(td, universe_count=0, pick_count=0, error=msg)
            return {"skipped": True, "reason": msg, "trade_date": td}

        self._ensure_cache(dates, progress=progress)
        self.store.prune_cache_before(dates[0])

        if progress:
            progress("compute", 0, 1)

        rows = self.store.load_cache_panel(dates)
        if not rows:
            self.store.set_scan_log(td, universe_count=len(names), pick_count=0, error="缓存为空")
            return {"skipped": True, "reason": "empty_cache", "trade_date": td}

        df_all = pd.DataFrame(rows)
        sector_map = self._load_sector_map()
        picks: list[dict[str, Any]] = []
        funnel: dict[str, int] = {
            "evaluated": 0,
            "wash_in_progress": 0,
            "wash_complete": 0,
            "listed": 0,
        }

        codes = [
            c
            for c in df_all["stock_code"].unique()
            if c in names and c not in suspended
        ]
        total_codes = len(codes)
        if progress:
            progress("compute", 0, max(total_codes, 1))

        for i, code in enumerate(codes):
            sub = df_all[df_all["stock_code"] == code].copy()
            if len(sub) < min_bars_required():
                continue
            funnel["evaluated"] += 1
            ev = evaluate_stock_accum(sub, scan_date=td, params=params)
            if ev is None:
                continue
            if ev.get("phase") == "wash_in_progress":
                funnel["wash_in_progress"] += 1
            elif ev.get("phase") == "wash_complete":
                funnel["wash_complete"] += 1
            funnel["listed"] += 1
            picks.append(
                {
                    "stock_code": code,
                    "stock_name": names.get(code, ""),
                    "sector_path": sector_map.get(code, ""),
                    **{k: v for k, v in ev.items() if k != "detail"},
                }
            )
            if progress and (i + 1 == total_codes or (i + 1) % 25 == 0):
                progress("compute", i + 1, total_codes)

        self.store.replace_picks(td, picks)
        self.store.set_scan_log(
            td,
            universe_count=len(names) - len(suspended),
            pick_count=len(picks),
            error=None,
            funnel=funnel,
        )
        if progress:
            progress("compute", max(total_codes, 1), max(total_codes, 1))
        return {
            "skipped": False,
            "trade_date": td,
            "pick_count": len(picks),
            "universe_count": len(names) - len(suspended),
            "funnel": funnel,
        }

    def picks(self, trade_date: str | None = None, *, phase: str | None = None) -> dict[str, Any]:
        td = self._resolve_scan_date(trade_date)
        log = self.store.get_scan_log(td) or {}
        funnel = None
        if log.get("funnel_json"):
            try:
                funnel = json.loads(log["funnel_json"])
            except json.JSONDecodeError:
                funnel = None
        items = self.store.list_picks(td, phase=phase)
        for it in items:
            it.pop("detail_json", None)
        return {
            "trade_date": td,
            "items": items,
            "pick_count": len(items),
            "funnel": funnel,
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
                detail["stock_code"] = stock_code
                detail["trade_date"] = td
                return detail
            except json.JSONDecodeError:
                pass
        settings = self._settings()
        params = parse_accum_params(settings)
        hist_days = int(settings.get("accum_history_days", "120"))
        dates = get_recent_trading_days(cache_days_required(hist_days), end=td)
        rows = self.store.load_cache_panel(dates)
        sub = pd.DataFrame([r for r in rows if r["stock_code"] == stock_code])
        if sub.empty:
            return None
        ev = evaluate_stock_accum(sub, scan_date=td, params=params)
        if ev is None:
            return None
        detail = ev.get("detail", {})
        detail["from_cache"] = False
        detail["stock_code"] = stock_code
        detail["trade_date"] = td
        return detail

    def diagnose(
        self,
        stock_code: str,
        *,
        t0_date: str,
        scan_date: str | None = None,
    ) -> dict[str, Any]:
        """单股形态逐步诊断（指定 T₀ 与扫描日）。"""
        settings = self._settings()
        params = parse_accum_params(settings)
        hist_days = int(settings.get("accum_history_days", "120"))
        td = self._resolve_scan_date(scan_date)
        need_days = cache_days_required(hist_days)
        dates = get_recent_trading_days(need_days, end=td)
        self._ensure_cache(dates)
        rows = self.store.load_cache_panel(dates)
        sub = pd.DataFrame([r for r in rows if r["stock_code"] == stock_code])
        if sub.empty:
            return diagnose_stock_accum(
                sub,
                t0_date=t0_date,
                scan_date=td,
                params=params,
            )
        report = diagnose_stock_accum(sub, t0_date=t0_date, scan_date=td, params=params)
        report["stock_code"] = stock_code
        return report

    def meta(self) -> dict[str, Any]:
        settings = self._settings()
        params = parse_accum_params(settings)
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
        cache_dates = self.store.list_cached_dates()
        hist_days = int(settings.get("accum_history_days", "120"))
        return {
            "trade_date": td,
            "is_trading_day": is_trading_day(today_cst()),
            "enabled": settings.get("accum_enabled", "true").lower() == "true",
            "scan_time": settings.get("accum_time", "17:00"),
            "history_days": params.history_days,
            "wash_mult": params.wash_mult,
            "last_scan_at": log.get("last_scan_at"),
            "last_error": log.get("error_message"),
            "pick_count": log.get("pick_count"),
            "funnel": funnel,
            "cache_day_count": len(cache_dates),
            "cache_days_required": cache_days_required(hist_days),
            "scan_job": active or latest,
            "settings_meta": self.store.get_settings_meta(),
        }
