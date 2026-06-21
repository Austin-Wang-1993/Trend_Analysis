"""顺向火车轨 SXHCG + RPS 纯计算逻辑。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class TrainTrackParams:
    rps_sum_min: float = 185.0
    near_high_250_min: float = 0.8
    drawdown_20_max: float = 0.25
    turnover_max: float = 10.0
    count_ma250_30_min: int = 25
    count_ma200_30_min: int = 25
    count_ma20_10_min: int = 9
    count_ma10_4_min: int = 3
    count_ma20_4_min: int = 3
    ma_rise_days: int = 5
    recent_20d_pct_max: float = 30.0
    ma_touch_band_pct: float = 2.0


def is_st_name(name: str | None) -> bool:
    if not name:
        return False
    return "ST" in str(name).upper()


def rolling_ma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).mean()


def compute_rps_panel(close_panel: pd.DataFrame, windows: tuple[int, ...] = (120, 250)) -> pd.DataFrame:
    """close_panel: index=trade_date, columns=stock_code。返回同结构 RPS（0–99）。"""
    out: dict[str, pd.Series] = {}
    for w in windows:
        ret = close_panel / close_panel.shift(w) - 1.0
        # 每个交易日横截面百分位
        rps = ret.rank(axis=1, pct=True, method="average") * 99.0
        out[f"rps{w}"] = rps
    # 合并为 MultiIndex columns 不方便，返回 dict of DataFrames
    return out  # type: ignore[return-value]


def compute_rps_for_day(close_series: pd.Series, close_panel: pd.DataFrame, day_idx: int, windows: tuple[int, int] = (120, 250)) -> tuple[float | None, float | None]:
    """单日单股 RPS（close_panel 已按日期排序）。"""
    rps_vals: list[float | None] = []
    for w in windows:
        if day_idx < w:
            rps_vals.append(None)
            continue
        row = close_panel.iloc[day_idx]
        prev = close_panel.iloc[day_idx - w]
        ret = row / prev - 1.0
        valid = ret.notna()
        if not valid.any():
            rps_vals.append(None)
            continue
        ranks = ret[valid].rank(pct=True, method="average") * 99.0
        code = close_series.name
        rps_vals.append(float(ranks.get(code)) if code in ranks.index else None)
    return rps_vals[0], rps_vals[1]


def ma_touch_tag(dist_ma5: float | None, dist_ma10: float | None, band: float) -> str:
    tags: list[str] = []
    if dist_ma5 is not None and abs(dist_ma5) <= band:
        tags.append("ma5")
    if dist_ma10 is not None and abs(dist_ma10) <= band:
        tags.append("ma10")
    return ",".join(tags)


def evaluate_sxhcg(
    closes: pd.Series,
    highs: pd.Series,
    turnover: float | None,
    *,
    rps120: float | None,
    rps250: float | None,
    params: TrainTrackParams | None = None,
) -> dict[str, Any]:
    """closes/highs: 按日期升序，最后一行为扫描日。"""
    p = params or TrainTrackParams()
    n = len(closes)
    if n < 250:
        return {"pass": False, "reason": "insufficient_bars"}

    c = closes.astype(float)
    h = highs.astype(float)
    last = float(c.iloc[-1])

    ma10 = rolling_ma(c, 10)
    ma20 = rolling_ma(c, 20)
    ma200 = rolling_ma(c, 200)
    ma250 = rolling_ma(c, 250)

    # SXHCG1
    hit1 = (
        rps120 is not None
        and rps250 is not None
        and (rps120 + rps250) > p.rps_sum_min
    )

    # SXHCG2
    hit20 = last > float(ma20.iloc[-1])
    last30 = c.iloc[-30:]
    ma250_30 = ma250.iloc[-30:]
    ma200_30 = ma200.iloc[-30:]
    hit21 = int((last30 > ma250_30).sum()) >= p.count_ma250_30_min
    hit22 = int((last30 > ma200_30).sum()) >= p.count_ma200_30_min
    hit23 = int((c.iloc[-10:] > ma20.iloc[-10:]).sum()) >= p.count_ma20_10_min
    hit24 = (
        int((c.iloc[-4:] > rolling_ma(c, 10).iloc[-4:]).sum()) >= p.count_ma10_4_min
        and int((c.iloc[-4:] > ma20.iloc[-4:]).sum()) >= p.count_ma20_4_min
    )
    hit2 = hit20 and hit21 and hit22 and (hit23 or hit24)

    # SXHCG3
    hhv20 = float(c.iloc[-20:].max())
    hhv250 = float(c.iloc[-250:].max())
    hit31 = last / hhv20 >= (1.0 - p.drawdown_20_max) if hhv20 > 0 else False
    hit32 = last / hhv250 > p.near_high_250_min if hhv250 > 0 else False
    hit3 = hit31 and hit32

    # SXHCG4
    ma20_s = ma20.iloc[-p.ma_rise_days :]
    ma10_s = ma10.iloc[-p.ma_rise_days :]
    rise20 = bool((ma20_s.diff().dropna() >= 0).all()) if len(ma20_s) > 1 else False
    rise10 = bool((ma10_s.diff().dropna() >= 0).all()) if len(ma10_s) > 1 else False
    above = bool((ma10_s > ma20_s).all())
    hit41 = rise20 and above
    hit42 = rise10 and rise20 and float(ma10.iloc[-1]) > float(ma20.iloc[-1])
    hit4 = hit41 or hit42

    # SXHCG5
    hit5 = turnover is not None and turnover < p.turnover_max

    pct_20d = None
    if n >= 21:
        base = float(c.iloc[-21])
        if base > 0:
            pct_20d = (last / base - 1.0) * 100.0

    dist_ma10 = None
    ma5 = rolling_ma(c, 5)
    dist_ma5_pct = None
    if not np.isnan(ma5.iloc[-1]) and ma5.iloc[-1] > 0:
        dist_ma5_pct = (last - float(ma5.iloc[-1])) / float(ma5.iloc[-1]) * 100.0
    if not np.isnan(ma10.iloc[-1]) and ma10.iloc[-1] > 0:
        dist_ma10 = (last - float(ma10.iloc[-1])) / float(ma10.iloc[-1]) * 100.0

    hit_recent = pct_20d is not None and pct_20d < p.recent_20d_pct_max
    touch = ma_touch_tag(dist_ma5_pct, dist_ma10, p.ma_touch_band_pct)

    sx_pass = hit1 and hit2 and hit3 and hit4 and hit5
    full_pass = sx_pass and hit_recent

    return {
        "hit_sxhcg1": int(hit1),
        "hit_sxhcg2": int(hit2),
        "hit_sxhcg3": int(hit3),
        "hit_sxhcg4": int(hit4),
        "hit_sxhcg5": int(hit5),
        "hit_recent_calm": int(hit_recent),
        "sxhcg_pass": int(sx_pass),
        "pass": full_pass,
        "rps120": rps120,
        "rps250": rps250,
        "rps_sum": (rps120 + rps250) if rps120 is not None and rps250 is not None else None,
        "close": last,
        "pct_20d": pct_20d,
        "dist_ma5_pct": dist_ma5_pct,
        "dist_ma10_pct": dist_ma10,
        "ma_touch_tag": touch,
        "turnover_rate": turnover,
        "near_high_250_pct": last / hhv250 * 100.0 if hhv250 > 0 else None,
        "near_high_20_pct": last / hhv20 * 100.0 if hhv20 > 0 else None,
    }


def parse_train_track_params(settings: dict[str, str]) -> TrainTrackParams:
    return TrainTrackParams(
        rps_sum_min=float(settings.get("train_track_rps_sum_min", "185")),
        near_high_250_min=float(settings.get("train_track_near_high_250_min", "0.8")),
        drawdown_20_max=float(settings.get("train_track_drawdown_20_max", "0.25")),
        turnover_max=float(settings.get("train_track_turnover_max", "10")),
        count_ma250_30_min=int(settings.get("train_track_count_ma250_30_min", "25")),
        count_ma200_30_min=int(settings.get("train_track_count_ma200_30_min", "25")),
        count_ma20_10_min=int(settings.get("train_track_count_ma20_10_min", "9")),
        count_ma10_4_min=int(settings.get("train_track_count_ma10_4_min", "3")),
        count_ma20_4_min=int(settings.get("train_track_count_ma20_4_min", "3")),
        ma_rise_days=int(settings.get("train_track_ma_rise_days", "5")),
        recent_20d_pct_max=float(settings.get("train_track_recent_20d_pct_max", "30")),
        ma_touch_band_pct=float(settings.get("train_track_ma_touch_band_pct", "2")),
    )
