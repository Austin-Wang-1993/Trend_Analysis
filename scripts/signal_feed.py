"""信号数据馈送：Tushare rt_min（可替换实现）。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

import ts_common as tc

CST = ZoneInfo("Asia/Shanghai")


class RealtimeQuoteFeed(ABC):
    @abstractmethod
    def fetch_quotes(self) -> pd.DataFrame:
        """返回列：stock_code, last_price, today_open, quote_time (iso str)"""


class RtMinFeed(RealtimeQuoteFeed):
    """Tushare rt_min 全市场分批拉取。"""

    BATCHES = ("6*.SH", "0*.SZ")

    def fetch_quotes(self) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for pattern in self.BATCHES:
            df = tc.call_api("rt_min", ts_code=pattern, freq="1MIN")
            if df is None or df.empty:
                continue
            part = df.copy()
            code_col = "ts_code" if "ts_code" in part.columns else "code"
            if code_col not in part.columns:
                continue
            part["stock_code"] = part[code_col].astype(str).map(tc.ts_code_to_code6)
            time_col = "time" if "time" in part.columns else "trade_time"
            part["quote_time"] = part[time_col].astype(str) if time_col in part.columns else ""
            part["last_price"] = pd.to_numeric(part.get("close"), errors="coerce")
            part["today_open"] = pd.to_numeric(part.get("open"), errors="coerce")
            frames.append(part[["stock_code", "last_price", "today_open", "quote_time"]])
        if not frames:
            return pd.DataFrame(columns=["stock_code", "last_price", "today_open", "quote_time"])
        out = pd.concat(frames, ignore_index=True)
        out = out.drop_duplicates(subset=["stock_code"], keep="last")
        return out.reset_index(drop=True)


def quote_is_fresh(quote_time: str, *, stale_sec: int, now: datetime | None = None) -> bool:
    if not quote_time or stale_sec <= 0:
        return True
    now = now or datetime.now(CST)
    try:
        raw = quote_time.strip()
        if len(raw) >= 19:
            qt = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=CST)
        else:
            return False
    except ValueError:
        return False
    return (now - qt).total_seconds() <= stale_sec


def parse_settings_signal(settings: dict[str, str]) -> dict[str, Any]:
    return {
        "enabled": settings.get("signal_enabled", "true").lower() == "true",
        "poll_interval_sec": int(settings.get("signal_poll_interval_sec", "15")),
        "sched_start": settings.get("signal_sched_start", "09:25"),
        "sched_end": settings.get("signal_sched_end", "09:45"),
        "window_start": settings.get("signal_window_start", "09:30"),
        "window_end": settings.get("signal_window_end", "09:40"),
        "pct_threshold": float(settings.get("signal_pct_threshold", "9.8")),
        "engulf_mode": settings.get("signal_engulf_mode", "high"),
        "cross_body_ratio": float(settings.get("signal_cross_body_ratio", "0.1")),
        "long_upper_ratio": float(settings.get("signal_long_upper_ratio", "1.0")),
        "data_stale_sec": int(settings.get("signal_data_stale_sec", "120")),
    }


def time_in_range(now: datetime, start_hhmm: str, end_hhmm: str) -> bool:
    sh, sm = map(int, start_hhmm.split(":"))
    eh, em = map(int, end_hhmm.split(":"))
    cur = now.hour * 60 + now.minute
    return sh * 60 + sm <= cur <= eh * 60 + em
