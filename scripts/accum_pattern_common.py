"""量价吸筹形态纯计算逻辑（前复权实体价 + 原始成交量）。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class AccumPatternParams:
    history_days: int = 120
    vol_expand_trigger: float = 2.0
    vol_expand_start: float = 2.0
    vol_expand_decay: float = 0.1
    vol_expand_floor: float = 1.1
    vol_expand_max_consecutive_miss: int = 3
    vol_min_days: int = 3
    price_rise_min: float = 0.30
    wash_mult: float = 1.5
    vol_shrink_max: float = 1.1
    vol_wash_max_over_days: int = 1
    vol_wash_max_consecutive_over: int = 2
    vol_reset_trigger: float = 2.0
    drawdown_min: float = 0.60
    drawdown_max: float = 0.90


@dataclass
class PatternPhase:
    t0_idx: int
    t0_date: str
    expand_end_idx: int
    expand_end_date: str
    n_days: int
    m_target: int
    price_rise_pct: float
    peak_body_high: float
    start_body_low: float
    wash_start_idx: int
    wash_days_done: int
    wash_end_idx: int | None
    phase: str
    drawdown_ratio: float | None
    drawdown_ok: bool
    listed: bool
    bars: list[dict[str, Any]] = field(default_factory=list)


def parse_accum_params(settings: dict[str, str]) -> AccumPatternParams:
    return AccumPatternParams(
        history_days=int(settings.get("accum_history_days", "120")),
        vol_expand_trigger=float(settings.get("accum_vol_expand_trigger", "2.0")),
        vol_expand_start=float(settings.get("accum_vol_expand_start", "2.0")),
        vol_expand_decay=float(settings.get("accum_vol_expand_decay", "0.1")),
        vol_expand_floor=float(settings.get("accum_vol_expand_floor", "1.1")),
        vol_expand_max_consecutive_miss=int(
            settings.get("accum_vol_expand_max_consecutive_miss", "3")
        ),
        vol_min_days=int(settings.get("accum_vol_min_days", "3")),
        price_rise_min=float(settings.get("accum_price_rise_min", "0.30")),
        wash_mult=float(settings.get("accum_wash_mult", "1.5")),
        vol_shrink_max=float(settings.get("accum_vol_shrink_max", "1.1")),
        vol_wash_max_over_days=int(settings.get("accum_vol_wash_max_over_days", "1")),
        vol_wash_max_consecutive_over=int(
            settings.get("accum_vol_wash_max_consecutive_over", "2")
        ),
        vol_reset_trigger=float(settings.get("accum_vol_reset_trigger", "2.0")),
        drawdown_min=float(settings.get("accum_drawdown_min", "0.60")),
        drawdown_max=float(settings.get("accum_drawdown_max", "0.90")),
    )


def min_bars_required() -> int:
    return 10


def cache_days_required(hist_days: int) -> int:
    return max(hist_days, min_bars_required() + 5)


def _body_high(o: float, c: float) -> float:
    return max(o, c)


def _body_low(o: float, c: float) -> float:
    return min(o, c)


def _vol_ma5(vols: np.ndarray, idx: int) -> float | None:
    if idx < 5:
        return None
    window = vols[idx - 5 : idx]
    if np.isnan(window).all():
        return None
    return float(np.nanmean(window))


def _expand_threshold(params: AccumPatternParams, k: int) -> float:
    return max(params.vol_expand_start - params.vol_expand_decay * k, params.vol_expand_floor)


def _vol_expand_ok(
    vol: float,
    ma5: float,
    *,
    k: int,
    params: AccumPatternParams,
    is_t0: bool,
) -> bool:
    if ma5 <= 0 or np.isnan(vol) or np.isnan(ma5):
        return False
    if is_t0:
        return vol > params.vol_expand_trigger * ma5
    thr = _expand_threshold(params, k)
    return vol >= thr * ma5


def run_expand_phase(
    t0_idx: int,
    dates: list[str],
    opens: np.ndarray,
    closes: np.ndarray,
    vols: np.ndarray,
    params: AccumPatternParams,
) -> tuple[int | None, float, float, float]:
    n = len(dates)
    miss_consec = 0
    expand_end: int | None = None
    start_low = _body_low(float(opens[t0_idx]), float(closes[t0_idx]))
    peak_high = start_low

    for i in range(t0_idx, n):
        k = i - t0_idx
        ma5 = _vol_ma5(vols, i)
        if ma5 is None:
            break
        ok = _vol_expand_ok(
            float(vols[i]),
            ma5,
            k=k,
            params=params,
            is_t0=(i == t0_idx),
        )
        if not ok:
            miss_consec += 1
            if miss_consec >= params.vol_expand_max_consecutive_miss:
                expand_end = i - params.vol_expand_max_consecutive_miss
                break
        else:
            miss_consec = 0
            expand_end = i
            bh = _body_high(float(opens[i]), float(closes[i]))
            if bh > peak_high:
                peak_high = bh

    if expand_end is None or expand_end < t0_idx:
        return None, 0.0, peak_high, start_low
    if expand_end - t0_idx + 1 < params.vol_min_days:
        return None, 0.0, peak_high, start_low

    rise = (peak_high - start_low) / start_low if start_low > 0 else 0.0
    if rise < params.price_rise_min:
        return None, rise, peak_high, start_low
    return expand_end, rise, peak_high, start_low


def run_wash_phase(
    wash_start_idx: int,
    expand_end_idx: int,
    scan_idx: int,
    dates: list[str],
    opens: np.ndarray,
    closes: np.ndarray,
    vols: np.ndarray,
    params: AccumPatternParams,
    *,
    n_days: int,
    peak_body_high: float,
    start_body_low: float,
) -> tuple[PatternPhase | None, int | None]:
    m_target = int(params.wash_mult * n_days)
    if m_target < 1:
        m_target = 1

    rise_amp = peak_body_high - start_body_low
    wash_low = peak_body_high
    over_days = 0
    consec_over = 0
    wash_days_done = 0
    wash_end_idx: int | None = None
    bars: list[dict[str, Any]] = []

    last_idx = min(scan_idx, wash_start_idx + m_target - 1)
    for i in range(wash_start_idx, last_idx + 1):
        ma5 = _vol_ma5(vols, i)
        if ma5 is None:
            break
        vol = float(vols[i])
        if vol > params.vol_reset_trigger * ma5:
            return None, i

        over = vol >= params.vol_shrink_max * ma5
        if over:
            over_days += 1
            consec_over += 1
            if consec_over >= params.vol_wash_max_consecutive_over:
                return None, None
            if over_days > params.vol_wash_max_over_days:
                return None, None
        else:
            consec_over = 0

        bl = _body_low(float(opens[i]), float(closes[i]))
        if bl < wash_low:
            wash_low = bl
        wash_days_done += 1
        wash_end_idx = i
        bars.append(
            {
                "trade_date": dates[i],
                "vol": vol,
                "vol_ma5": ma5,
                "vol_ratio": vol / ma5 if ma5 > 0 else None,
                "body_low": bl,
                "over": over,
            }
        )

    if wash_days_done < 1:
        return None, None

    dd_ratio: float | None = None
    dd_ok = False
    if rise_amp > 0:
        dd_ratio = (peak_body_high - wash_low) / rise_amp
        dd_ok = params.drawdown_min <= dd_ratio <= params.drawdown_max

    complete = wash_days_done >= m_target
    if complete:
        phase = "wash_complete"
        listed = dd_ok
    else:
        phase = "wash_in_progress"
        listed = True

    pat = PatternPhase(
        t0_idx=wash_start_idx - 1,
        t0_date=dates[wash_start_idx - 1],
        expand_end_idx=expand_end_idx,
        expand_end_date=dates[expand_end_idx],
        n_days=n_days,
        m_target=m_target,
        price_rise_pct=(peak_body_high - start_body_low) / start_body_low
        if start_body_low > 0
        else 0.0,
        peak_body_high=peak_body_high,
        start_body_low=start_body_low,
        wash_start_idx=wash_start_idx,
        wash_days_done=wash_days_done,
        wash_end_idx=wash_end_idx,
        phase=phase,
        drawdown_ratio=dd_ratio,
        drawdown_ok=dd_ok,
        listed=listed,
        bars=bars,
    )
    return pat, None


def find_pattern_from_t0(
    t0_idx: int,
    scan_idx: int,
    dates: list[str],
    opens: np.ndarray,
    closes: np.ndarray,
    vols: np.ndarray,
    params: AccumPatternParams,
) -> PatternPhase | None:
    expand_end, rise, peak_high, start_low = run_expand_phase(
        t0_idx, dates, opens, closes, vols, params
    )
    if expand_end is None:
        return None

    n_days = expand_end - t0_idx + 1
    wash_start = expand_end + 1
    if wash_start > scan_idx:
        return None

    pat, reset_at = run_wash_phase(
        wash_start,
        expand_end,
        scan_idx,
        dates,
        opens,
        closes,
        vols,
        params,
        n_days=n_days,
        peak_body_high=peak_high,
        start_body_low=start_low,
    )
    if reset_at is not None:
        return find_pattern_from_t0(reset_at, scan_idx, dates, opens, closes, vols, params)
    if pat is None:
        return None
    pat.t0_idx = t0_idx
    pat.t0_date = dates[t0_idx]
    pat.price_rise_pct = rise
    return pat if pat.listed else None


def find_latest_pattern(
    dates: list[str],
    opens: np.ndarray,
    closes: np.ndarray,
    vols: np.ndarray,
    params: AccumPatternParams,
    scan_date: str,
) -> PatternPhase | None:
    if scan_date not in dates:
        return None
    scan_idx = dates.index(scan_date)
    best: PatternPhase | None = None
    for t0 in range(5, scan_idx + 1):
        ma5 = _vol_ma5(vols, t0)
        if ma5 is None:
            continue
        if float(vols[t0]) <= params.vol_expand_trigger * ma5:
            continue
        pat = find_pattern_from_t0(t0, scan_idx, dates, opens, closes, vols, params)
        if pat is not None and (best is None or pat.t0_idx > best.t0_idx):
            best = pat
    return best


def apply_qfq_panel(df: pd.DataFrame, ref_adj: float) -> pd.DataFrame:
    out = df.copy()
    if ref_adj <= 0 or np.isnan(ref_adj):
        return out
    factor = out["adj_factor"].astype(float) / ref_adj
    out["open"] = out["open"].astype(float) * factor
    out["close"] = out["close"].astype(float) * factor
    return out


def evaluate_stock_accum(
    df: pd.DataFrame,
    *,
    scan_date: str,
    params: AccumPatternParams,
) -> dict[str, Any] | None:
    if df.empty:
        return None
    sub = df.sort_values("trade_date").reset_index(drop=True)
    if scan_date not in sub["trade_date"].values:
        return None

    ref_row = sub[sub["trade_date"] == scan_date]
    ref_adj = float(ref_row.iloc[0]["adj_factor"]) if not ref_row.empty else float("nan")
    if np.isnan(ref_adj) or ref_adj <= 0:
        ref_adj = float(sub.iloc[-1]["adj_factor"])

    sub = apply_qfq_panel(sub, ref_adj)
    dates = sub["trade_date"].astype(str).tolist()
    opens = sub["open"].astype(float).values
    closes = sub["close"].astype(float).values
    vols = sub["vol"].astype(float).values

    pat = find_latest_pattern(dates, opens, closes, vols, params, scan_date)
    if pat is None:
        return None

    detail = {
        "t0_date": pat.t0_date,
        "expand_end_date": pat.expand_end_date,
        "n_days": pat.n_days,
        "m_target": pat.m_target,
        "wash_days_done": pat.wash_days_done,
        "phase": pat.phase,
        "price_rise_pct": round(pat.price_rise_pct * 100, 2),
        "drawdown_ratio": round(pat.drawdown_ratio * 100, 2) if pat.drawdown_ratio is not None else None,
        "drawdown_ok": pat.drawdown_ok,
        "peak_body_high": pat.peak_body_high,
        "start_body_low": pat.start_body_low,
        "wash_bars": pat.bars,
    }

    return {
        "t0_date": pat.t0_date,
        "expand_end_date": pat.expand_end_date,
        "n_days": pat.n_days,
        "m_target": pat.m_target,
        "wash_days_done": pat.wash_days_done,
        "phase": pat.phase,
        "price_rise_pct": round(pat.price_rise_pct * 100, 2),
        "drawdown_ratio": round(pat.drawdown_ratio * 100, 2) if pat.drawdown_ratio is not None else None,
        "drawdown_ok": 1 if pat.drawdown_ok else 0,
        "close": float(sub[sub["trade_date"] == scan_date].iloc[0]["close"]),
        "detail_json": json.dumps(detail, ensure_ascii=False),
        "detail": detail,
    }
