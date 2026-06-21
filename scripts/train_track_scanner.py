"""火车轨选股扫描：缓存日线 + SXHCG + RPS。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

import ts_common as tc
from train_track_common import TrainTrackParams, evaluate_sxhcg, is_st_name, parse_train_track_params
from train_track_store import TrainTrackStore
from trading_calendar import get_recent_trading_days, is_trading_day, today_cst

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]


class TrainTrackScanner:
    def __init__(self, db_path: str | Path, *, get_settings: Any | None = None) -> None:
        self.store = TrainTrackStore(db_path)
        self._get_settings = get_settings
        self._sector_map: dict[str, str] | None = None

    def _settings(self) -> dict[str, str]:
        if self._get_settings is None:
            from history_store import HistoryStore

            return HistoryStore(self.store.db_path).get_settings()
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

    def _ensure_cache(self, trade_dates: list[str]) -> None:
        cached = set(self.store.list_cached_dates())
        missing = [d for d in trade_dates if d not in cached]
        for d in missing:
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
            tr_map: dict[str, float] = {}
            if basic is not None and not basic.empty:
                for _, r in basic.iterrows():
                    code = tc.ts_code_to_code6(str(r["ts_code"]))
                    if pd.notna(r.get("turnover_rate")):
                        tr_map[code] = float(r["turnover_rate"])
            rows: list[dict[str, Any]] = []
            if daily is not None and not daily.empty:
                for _, r in daily.iterrows():
                    code = tc.ts_code_to_code6(str(r["ts_code"]))
                    rows.append(
                        {
                            "trade_date": d,
                            "stock_code": code,
                            "open": float(r["open"]) if pd.notna(r.get("open")) else None,
                            "high": float(r["high"]) if pd.notna(r.get("high")) else None,
                            "low": float(r["low"]) if pd.notna(r.get("low")) else None,
                            "close": float(r["close"]) if pd.notna(r.get("close")) else None,
                            "vol": float(r["vol"]) if pd.notna(r.get("vol")) else None,
                            "turnover_rate": tr_map.get(code),
                        }
                    )
            self.store.upsert_cache_rows(rows)
            logger.info("train_track cache %s: %d rows", d, len(rows))

    def scan(self, *, trade_date: str | None = None) -> dict[str, Any]:
        settings = self._settings()
        params = parse_train_track_params(settings)
        hist_days = int(settings.get("train_track_history_days", "250"))
        td = trade_date or today_cst()
        if not is_trading_day(td):
            return {"skipped": True, "reason": "non_trading_day", "trade_date": td}

        names, suspended = self._universe(td)
        dates = get_recent_trading_days(hist_days, end=td)
        if len(dates) < 250:
            msg = f"交易日不足 {hist_days}（当前 {len(dates)}）"
            self.store.set_scan_log(td, pick_count=0, universe_count=0, error=msg)
            return {"skipped": True, "reason": msg, "trade_date": td}

        self._ensure_cache(dates)
        prune_before = dates[0]
        self.store.prune_cache_before(prune_before)

        rows = self.store.load_cache_panel(dates)
        if not rows:
            self.store.set_scan_log(td, pick_count=0, universe_count=len(names), error="缓存为空")
            return {"skipped": True, "reason": "empty_cache", "trade_date": td}

        df = pd.DataFrame(rows)
        close_panel = df.pivot(index="trade_date", columns="stock_code", values="close").sort_index()
        high_panel = df.pivot(index="trade_date", columns="stock_code", values="high").sort_index()
        turn_panel = df.pivot(index="trade_date", columns="stock_code", values="turnover_rate").sort_index()

        day_idx = len(close_panel) - 1
        ret120 = close_panel.iloc[day_idx] / close_panel.iloc[day_idx - 120] - 1.0
        ret250 = close_panel.iloc[day_idx] / close_panel.iloc[day_idx - 250] - 1.0
        rps120_all = ret120.rank(pct=True, method="average") * 99.0
        rps250_all = ret250.rank(pct=True, method="average") * 99.0

        sector_map = self._load_sector_map()
        picks: list[dict[str, Any]] = []

        for code in close_panel.columns:
            if code not in names or code in suspended:
                continue
            closes = close_panel[code].dropna()
            if len(closes) < 250:
                continue
            highs = high_panel[code].reindex(closes.index).fillna(closes)
            turnover = None
            if code in turn_panel.columns:
                tv = turn_panel[code].iloc[-1]
                if pd.notna(tv):
                    turnover = float(tv)

            rps120 = float(rps120_all[code]) if code in rps120_all.index and pd.notna(rps120_all[code]) else None
            rps250 = float(rps250_all[code]) if code in rps250_all.index and pd.notna(rps250_all[code]) else None

            ev = evaluate_sxhcg(
                closes,
                highs,
                turnover,
                rps120=rps120,
                rps250=rps250,
                params=params,
            )
            if not ev.get("pass"):
                continue
            picks.append(
                {
                    "stock_code": code,
                    "stock_name": names.get(code, ""),
                    "sector_path": sector_map.get(code, ""),
                    **ev,
                }
            )

        picks.sort(key=lambda x: (-(x.get("rps250") or 0), x["stock_code"]))
        for i, p in enumerate(picks, start=1):
            p["rank_rps250"] = i

        self.store.replace_picks(td, picks)
        self.store.set_scan_log(
            td,
            pick_count=len(picks),
            universe_count=len(names) - len(suspended),
            error=None,
        )
        return {
            "skipped": False,
            "trade_date": td,
            "pick_count": len(picks),
            "universe_count": len(names) - len(suspended),
            "cached_days": len(dates),
        }

    def meta(self) -> dict[str, Any]:
        settings = self._settings()
        td = today_cst()
        log = self.store.get_scan_log(td) or {}
        return {
            "trade_date": td,
            "is_trading_day": is_trading_day(td),
            "enabled": settings.get("train_track_enabled", "true").lower() == "true",
            "scan_time": settings.get("train_track_time", "16:30"),
            "default_limit": int(settings.get("train_track_default_limit", "20")),
            "last_scan_at": log.get("last_scan_at"),
            "pick_count": log.get("pick_count"),
            "universe_count": log.get("universe_count"),
            "last_error": log.get("error_message"),
            "settings_meta": self.store.get_settings_meta(),
        }


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--date")
    ns = ap.parse_args()
    scanner = TrainTrackScanner(ROOT / "data" / "history.db")
    if ns.scan:
        print(json.dumps(scanner.scan(trade_date=ns.date), ensure_ascii=False))
