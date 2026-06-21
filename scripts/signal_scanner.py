"""反包打板信号扫描编排。"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

import ts_common as tc
from signal_common import SignalParams, evaluate_signal, is_main_board_code, is_st_name
from signal_feed import RtMinFeed, parse_settings_signal, quote_is_fresh, time_in_range
from signal_store import SignalStore
from trading_calendar import get_recent_trading_days, is_trading_day, today_cst

logger = logging.getLogger(__name__)
CST = ZoneInfo("Asia/Shanghai")
ROOT = Path(__file__).resolve().parents[1]


class SignalScanner:
    def __init__(
        self,
        db_path: str | Path,
        *,
        feed: RtMinFeed | None = None,
        get_settings: Any | None = None,
    ) -> None:
        self.store = SignalStore(db_path)
        self.feed = feed or RtMinFeed()
        self._get_settings = get_settings
        self._ctx_cache: dict[str, Any] = {}

    def _settings(self) -> dict[str, str]:
        if self._get_settings is None:
            from history_store import HistoryStore

            return HistoryStore(self.store.db_path).get_settings()
        return self._get_settings()

    def _trade_date(self) -> str:
        return today_cst()

    def _load_context(self, trade_date: str) -> dict[str, Any]:
        if self._ctx_cache.get("trade_date") == trade_date and self._ctx_cache.get("ready"):
            return self._ctx_cache

        days = get_recent_trading_days(2, end=trade_date)
        if len(days) < 2:
            raise RuntimeError("缺少上一交易日 daily，无法计算 T-1 形态")
        t1_date = days[-2] if days[-1] == trade_date else days[-1]
        t1_compact = t1_date.replace("-", "")

        basic = tc.call_api(
            "stock_basic",
            exchange="",
            list_status="L",
            fields="ts_code,name",
        )
        names: dict[str, str] = {}
        universe: set[str] = set()
        if basic is not None and not basic.empty:
            for _, r in basic.iterrows():
                code = tc.ts_code_to_code6(str(r["ts_code"]))
                if not is_main_board_code(code) or is_st_name(r.get("name")):
                    continue
                universe.add(code)
                names[code] = str(r.get("name") or "")

        suspended: set[str] = set()
        susp = tc.call_api("suspend_d", trade_date=trade_date.replace("-", ""))
        if susp is not None and not susp.empty:
            suspended = {tc.ts_code_to_code6(str(x)) for x in susp["ts_code"]}

        daily = tc.call_api(
            "daily",
            trade_date=t1_compact,
            fields="ts_code,open,high,low,close,pre_close",
        )
        t1_map: dict[str, dict[str, float]] = {}
        if daily is not None and not daily.empty:
            for _, r in daily.iterrows():
                code = tc.ts_code_to_code6(str(r["ts_code"]))
                if code not in universe:
                    continue
                t1_map[code] = {
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                    "pre_close": float(r["pre_close"]) if pd.notna(r.get("pre_close")) else float(r["close"]),
                }

        limits = tc.call_api(
            "stk_limit",
            trade_date=trade_date.replace("-", ""),
            fields="ts_code,up_limit",
        )
        up_limits: dict[str, float] = {}
        if limits is not None and not limits.empty:
            for _, r in limits.iterrows():
                code = tc.ts_code_to_code6(str(r["ts_code"]))
                if pd.notna(r.get("up_limit")):
                    up_limits[code] = float(r["up_limit"])

        # 昨收：用 T-1 的 close 作为今日 pre_close 基准（与 rt_min 涨幅字段一致化）
        pre_close_map = {c: v["close"] for c, v in t1_map.items()}

        self._ctx_cache = {
            "trade_date": trade_date,
            "ready": True,
            "universe": universe,
            "suspended": suspended,
            "names": names,
            "t1_map": t1_map,
            "pre_close_map": pre_close_map,
            "up_limits": up_limits,
            "today_opens": {},
        }
        return self._ctx_cache

    def scan_once(self, *, force: bool = False) -> dict[str, Any]:
        cfg = parse_settings_signal(self._settings())
        now = datetime.now(CST)
        trade_date = self._trade_date()

        if not force and not cfg["enabled"]:
            return {"skipped": True, "reason": "disabled"}
        if not is_trading_day(trade_date):
            return {"skipped": True, "reason": "non_trading_day"}
        if not force and not time_in_range(now, cfg["sched_start"], cfg["sched_end"]):
            return {"skipped": True, "reason": "outside_sched"}

        allow_insert = time_in_range(now, cfg["window_start"], cfg["window_end"]) or force
        frozen_new = not time_in_range(now, cfg["window_start"], cfg["window_end"]) and not force

        try:
            ctx = self._load_context(trade_date)
        except Exception as exc:
            self.store.set_scan_meta(trade_date, scanned_count=0, hit_count=0, error=str(exc))
            raise

        quotes = self.feed.fetch_quotes()
        params = SignalParams(
            pct_threshold=cfg["pct_threshold"],
            engulf_mode=cfg["engulf_mode"],
            cross_body_ratio=cfg["cross_body_ratio"],
            long_upper_ratio=cfg["long_upper_ratio"],
        )

        scanned = 0
        written = 0
        for _, q in quotes.iterrows():
            code = str(q["stock_code"])
            if code not in ctx["universe"] or code in ctx["suspended"]:
                continue
            if code not in ctx["t1_map"] or code not in ctx["pre_close_map"]:
                continue
            if not force and not quote_is_fresh(str(q.get("quote_time", "")), stale_sec=cfg["data_stale_sec"], now=now):
                continue

            scanned += 1
            last_price = float(q["last_price"])
            if last_price <= 0:
                continue

            pre_close = float(ctx["pre_close_map"][code])
            t1 = ctx["t1_map"][code]
            today_open = q.get("today_open")
            if pd.notna(today_open):
                ctx["today_opens"].setdefault(code, float(today_open))
            open_cached = ctx["today_opens"].get(code)

            ev = evaluate_signal(
                last_price=last_price,
                pre_close=pre_close,
                pre_open=t1["open"],
                pre_high=t1["high"],
                pre_low=t1["low"],
                pre_close_t1=t1["close"],
                today_open=open_cached,
                up_limit=ctx["up_limits"].get(code),
                params=params,
            )
            if ev["score"] < 1:
                continue

            row = {
                "stock_code": code,
                "stock_name": ctx["names"].get(code, ""),
                "last_price": last_price,
                "pre_close": pre_close,
                "pre_high": t1["high"],
                "pre_open": t1["open"],
                "today_open": open_cached,
                **ev,
            }
            if frozen_new:
                if self.store.upsert_hit(trade_date, row, allow_insert=False):
                    written += 1
            else:
                if self.store.upsert_hit(trade_date, row, allow_insert=allow_insert):
                    written += 1

        hits = self.store.list_hits(trade_date, min_score=1)
        self.store.set_scan_meta(
            trade_date,
            scanned_count=scanned,
            hit_count=len(hits),
            error=None,
        )
        return {
            "skipped": False,
            "trade_date": trade_date,
            "scanned": scanned,
            "written": written,
            "hit_count": len(hits),
            "allow_insert": allow_insert,
            "frozen_new": frozen_new,
        }

    def get_meta(self) -> dict[str, Any]:
        cfg = parse_settings_signal(self._settings())
        now = datetime.now(CST)
        trade_date = self._trade_date()
        meta = self.store.get_scan_meta(trade_date) or {}
        in_sched = time_in_range(now, cfg["sched_start"], cfg["sched_end"])
        in_window = time_in_range(now, cfg["window_start"], cfg["window_end"])
        return {
            "trade_date": trade_date,
            "is_trading_day": is_trading_day(trade_date),
            "enabled": cfg["enabled"],
            "in_sched": in_sched,
            "in_signal_window": in_window,
            "frozen_new": is_trading_day(trade_date) and not in_window,
            "poll_interval_sec": cfg["poll_interval_sec"],
            "window_start": cfg["window_start"],
            "window_end": cfg["window_end"],
            "sched_start": cfg["sched_start"],
            "sched_end": cfg["sched_end"],
            "last_scan_at": meta.get("last_scan_at"),
            "last_error": meta.get("last_error"),
            "scanned_count": meta.get("scanned_count"),
            "hit_count": meta.get("hit_count"),
            "now": now.isoformat(),
        }
