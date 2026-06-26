"""神奇九转（TD Sequential 抄底）纯计算逻辑。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from train_track_common import is_st_name


@dataclass(frozen=True)
class TdSequentialParams:
    lookback_days: int = 20
    vol_shrink_ratio: float = 0.8
    vol_expand_ratio: float = 1.2
    shadow_lower_min: float = 0.5
    cross_body_max: float = 0.15
    bear_lower_max: float = 0.2
    vol_price_mode: str = "or"  # or | and
    countdown_near_min: int = 10
    countdown_near_max: int = 13
    countdown_after_setup_days: int = 5
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    macd_valley_close_pct: float = 0.10
    macd_ref_valley_max: int = 3
    macd_ref_valley_min: int = 1
    macd_div_ref: str = "hist"  # 保留兼容；列5判定已统一用 DIF
    stop_loss_pct: float = 0.03


@dataclass
class MacdValley:
    peak_idx: int
    trough_idx: int
    end_idx: int
    closed: bool
    death_cross_idx: int | None = None
    golden_cross_idx: int | None = None


@dataclass
class SetupBar:
    seq: int
    trade_date: str
    close: float
    ref_date: str
    ref_close: float
    passed: bool


@dataclass
class CountdownBar:
    seq: int
    trade_date: str
    close: float
    ref_date: str
    ref_low: float
    passed: bool
    extra_13v8: dict[str, Any] | None = None


@dataclass
class SetupCycle:
    setup_9_date: str
    setup_9_idx: int
    setup_bars: list[SetupBar] = field(default_factory=list)
    setup_9_close: float = 0.0
    setup_9_low: float = 0.0
    setup_9_open: float = 0.0
    setup_9_high: float = 0.0
    setup_9_vol: float | None = None
    setup_9_turnover_rate: float | None = None


@dataclass
class CountdownState:
    cd_count: int = 0
    cd_dates: list[str] = field(default_factory=list)
    countdown_bars: list[CountdownBar] = field(default_factory=list)
    countdown_13_date: str | None = None
    cd_last_date: str | None = None


def parse_td_params(settings: dict[str, str]) -> TdSequentialParams:
    return TdSequentialParams(
        lookback_days=int(settings.get("td_lookback_days", "20")),
        vol_shrink_ratio=float(settings.get("td_vol_shrink_ratio", "0.8")),
        vol_expand_ratio=float(settings.get("td_vol_expand_ratio", "1.2")),
        shadow_lower_min=float(settings.get("td_shadow_lower_min", "0.5")),
        cross_body_max=float(settings.get("td_cross_body_max", "0.15")),
        bear_lower_max=float(settings.get("td_bear_lower_max", "0.2")),
        vol_price_mode=str(settings.get("td_vol_price_mode", "or")).lower(),
        countdown_near_min=int(settings.get("td_countdown_near_min", "10")),
        countdown_near_max=int(settings.get("td_countdown_near_max", "13")),
        countdown_after_setup_days=int(settings.get("td_countdown_after_setup_days", "5")),
        macd_fast=int(settings.get("td_macd_fast", "12")),
        macd_slow=int(settings.get("td_macd_slow", "26")),
        macd_signal=int(settings.get("td_macd_signal", "9")),
        macd_valley_close_pct=float(settings.get("td_macd_valley_close_pct", "0.10")),
        macd_ref_valley_max=int(settings.get("td_macd_ref_valley_max", "3")),
        macd_ref_valley_min=int(settings.get("td_macd_ref_valley_min", "1")),
        macd_div_ref=str(settings.get("td_macd_div_ref", "hist")).lower(),
        stop_loss_pct=float(settings.get("td_stop_loss_pct", "0.03")),
    )


def min_bars_required() -> int:
    return 13


def cache_days_required(hist_days: int) -> int:
    return max(hist_days, min_bars_required() + 5)


def _candle_ratios(o: float, h: float, l: float, c: float) -> tuple[float, float, float]:
    rng = h - l
    if rng <= 0:
        return 1.0, 0.0, 0.0
    body = abs(c - o)
    lower = min(o, c) - l
    upper = h - max(o, c)
    return lower / rng, upper / rng, body / rng


def _vol_ma5(vols: pd.Series, idx: int) -> float | None:
    if idx < 5:
        return None
    window = vols.iloc[idx - 5 : idx]
    if window.isna().all():
        return None
    return float(window.mean())


def evaluate_vol_price(
    *,
    open_: float,
    high: float,
    low: float,
    close: float,
    vol: float | None,
    turnover_rate: float | None,
    vol_ma5: float | None,
    params: TdSequentialParams,
) -> dict[str, Any]:
    lower_r, upper_r, body_r = _candle_ratios(open_, high, low, close)
    shrink = expand = False
    if vol is not None and vol_ma5 is not None and vol_ma5 > 0:
        shrink = vol < vol_ma5 * params.vol_shrink_ratio
        expand = vol > vol_ma5 * params.vol_expand_ratio
    elif turnover_rate is not None and vol_ma5 is not None and vol_ma5 > 0:
        shrink = turnover_rate < vol_ma5 * params.vol_shrink_ratio
        expand = turnover_rate > vol_ma5 * params.vol_expand_ratio

    hammer = lower_r >= params.shadow_lower_min or body_r <= params.cross_body_max
    bear_reject = (
        expand
        and lower_r < params.bear_lower_max
        and (close - low) / max(high - low, 1e-9) < 0.1
    )
    if bear_reject:
        passed = False
    elif params.vol_price_mode == "and":
        passed = shrink and hammer
    else:
        passed = shrink or hammer

    if shrink:
        vol_tag = "缩量"
    elif expand:
        vol_tag = "放量"
    else:
        vol_tag = "中性"

    return {
        "passed": passed,
        "rejected_bear": bear_reject,
        "vol_tag": vol_tag,
        "lower_shadow_ratio": lower_r,
        "upper_shadow_ratio": upper_r,
        "body_ratio": body_r,
        "shrink": shrink,
        "expand": expand,
        "hammer_or_cross": hammer,
    }


def compute_macd_series(
    closes: pd.Series,
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = closes.ewm(span=fast, adjust=False).mean()
    ema_slow = closes.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = 2.0 * (dif - dea)
    return dif, dea, hist


def _dif_local_peaks(dif: np.ndarray, *, start: int, end: int) -> list[int]:
    peaks: list[int] = []
    for i in range(max(start, 1), min(end, len(dif) - 1)):
        if np.isnan(dif[i]) or np.isnan(dif[i - 1]) or np.isnan(dif[i + 1]):
            continue
        if dif[i] >= dif[i - 1] and dif[i] > dif[i + 1]:
            peaks.append(i)
        elif dif[i] > dif[i - 1] and dif[i] >= dif[i + 1]:
            peaks.append(i)
    return peaks


def _macd_cross_below(dif: float, dea: float, prev_dif: float, prev_dea: float) -> bool:
    return prev_dif >= prev_dea and dif < dea


def _macd_cross_above(dif: float, dea: float, prev_dif: float, prev_dea: float) -> bool:
    return prev_dif <= prev_dea and dif > dea


def enumerate_macd_valleys(
    dif: np.ndarray,
    dea: np.ndarray,
    *,
    end_idx: int,
) -> list[MacdValley]:
    """自序列起点至 end_idx 枚举 DIF 谷底区域。"""
    peaks = _dif_local_peaks(dif, start=1, end=end_idx - 1)
    if not peaks:
        return []
    valleys: list[MacdValley] = []
    for pi, peak_idx in enumerate(peaks):
        next_peak = peaks[pi + 1] if pi + 1 < len(peaks) else end_idx
        search_end = min(next_peak, end_idx)
        trough_idx = peak_idx
        min_dif = float(dif[peak_idx])
        death: int | None = None
        golden: int | None = None
        for i in range(peak_idx + 1, search_end + 1):
            if np.isnan(dif[i]):
                continue
            if float(dif[i]) < min_dif:
                min_dif = float(dif[i])
                trough_idx = i
            if i >= 1 and not np.isnan(dif[i - 1]) and not np.isnan(dea[i]) and not np.isnan(dea[i - 1]):
                if death is None and _macd_cross_below(
                    float(dif[i]), float(dea[i]), float(dif[i - 1]), float(dea[i - 1])
                ):
                    death = i
                if death is not None and golden is None and _macd_cross_above(
                    float(dif[i]), float(dea[i]), float(dif[i - 1]), float(dea[i - 1])
                ):
                    golden = i
                    break
        closed = death is not None and golden is not None
        valley_end = golden if closed and golden is not None else search_end
        valleys.append(
            MacdValley(
                peak_idx=peak_idx,
                trough_idx=trough_idx,
                end_idx=valley_end,
                closed=closed,
                death_cross_idx=death,
                golden_cross_idx=golden,
            )
        )
    return valleys


def _valley_closure_progress(
    dif: np.ndarray,
    peak_idx: int,
    trough_idx: int,
    eval_idx: int,
) -> float:
    peak_v = float(dif[peak_idx])
    trough_v = float(dif[trough_idx])
    eval_v = float(dif[eval_idx])
    depth = peak_v - trough_v
    if depth <= 1e-12:
        return 1.0 if eval_v >= trough_v else 0.0
    return max(0.0, (eval_v - trough_v) / depth)


def _valley_price_low_idx(lows: np.ndarray, valley: MacdValley) -> int:
    end = (
        valley.golden_cross_idx
        if valley.closed and valley.golden_cross_idx is not None
        else valley.end_idx
    )
    seg = lows[valley.peak_idx : end + 1]
    return valley.peak_idx + int(np.argmin(seg))


def _select_target_valley(
    valleys: list[MacdValley],
    anchor_idx: int,
    cd_start: int,
    cd_end: int,
) -> MacdValley | None:
    containing = [v for v in valleys if v.peak_idx <= anchor_idx <= v.end_idx]
    if containing:
        return max(containing, key=lambda v: v.peak_idx)
    overlapping = [
        v for v in valleys if not (v.end_idx < cd_start or v.peak_idx > cd_end)
    ]
    if not overlapping:
        return None
    return max(overlapping, key=lambda v: v.peak_idx)


def _refine_p0_idx(
    lows: np.ndarray,
    valley: MacdValley,
    cd_start: int,
    cd_end: int,
) -> int:
    a = max(valley.peak_idx, cd_start)
    b = min(valley.end_idx, cd_end)
    if a > b:
        return a
    return a + int(np.argmin(lows[a : b + 1]))


def _macd_valley_to_dict(dates: list[str], valley: MacdValley) -> dict[str, Any]:
    return {
        "peak_date": dates[valley.peak_idx],
        "trough_date": dates[valley.trough_idx],
        "end_date": dates[valley.end_idx],
        "closed": valley.closed,
        "death_cross_date": dates[valley.death_cross_idx] if valley.death_cross_idx is not None else None,
        "golden_cross_date": dates[valley.golden_cross_idx] if valley.golden_cross_idx is not None else None,
    }


def evaluate_macd_divergence(
    closes: pd.Series,
    lows: pd.Series,
    dates: list[str],
    cd_start_idx: int,
    cd13_idx: int | None,
    params: TdSequentialParams,
) -> dict[str, Any]:
    """跨谷底 MACD 底背离（列 5）；评估日 = countdown_13_date。"""
    empty: dict[str, Any] = {"passed": False}
    if cd13_idx is None or cd_start_idx > cd13_idx:
        return {**empty, "reason": "no_cd13"}
    dif_s, dea_s, hist_s = compute_macd_series(
        closes,
        fast=params.macd_fast,
        slow=params.macd_slow,
        signal=params.macd_signal,
    )
    dif = dif_s.to_numpy(dtype=float)
    dea = dea_s.to_numpy(dtype=float)
    hist = hist_s.to_numpy(dtype=float)
    low_arr = lows.to_numpy(dtype=float)

    if np.isnan(dif[cd13_idx]) or np.isnan(low_arr[cd_start_idx : cd13_idx + 1]).any():
        return {**empty, "reason": "macd_nan"}

    p0_interval_idx = cd_start_idx + int(np.argmin(low_arr[cd_start_idx : cd13_idx + 1]))
    valleys = enumerate_macd_valleys(dif, dea, end_idx=cd13_idx)
    target = _select_target_valley(valleys, p0_interval_idx, cd_start_idx, cd13_idx)
    if target is None:
        return {**empty, "reason": "no_target_valley", "p0_interval_date": dates[p0_interval_idx]}

    p0_idx = _refine_p0_idx(low_arr, target, cd_start_idx, cd13_idx)
    progress_eval = _valley_closure_progress(dif, target.peak_idx, target.trough_idx, cd13_idx)
    progress_p0 = _valley_closure_progress(dif, target.peak_idx, target.trough_idx, p0_idx)

    if progress_eval < params.macd_valley_close_pct:
        return {
            **empty,
            "reason": "not_converged",
            "p0_date": dates[p0_idx],
            "p0_low": float(low_arr[p0_idx]),
            "p0_dif": float(dif[p0_idx]),
            "eval_date": dates[cd13_idx],
            "closure_progress_eval": progress_eval,
            "closure_progress_p0": progress_p0,
            "target_valley": _macd_valley_to_dict(dates, target),
        }

    prior_closed = [
        v for v in valleys if v.closed and v.peak_idx < target.peak_idx
    ]
    prior_closed.sort(key=lambda v: v.peak_idx, reverse=True)
    refs = prior_closed[: params.macd_ref_valley_max]
    if len(refs) < params.macd_ref_valley_min:
        return {
            **empty,
            "reason": "insufficient_refs",
            "refs_found": len(refs),
            "p0_date": dates[p0_idx],
            "target_valley": _macd_valley_to_dict(dates, target),
            "closure_progress_eval": progress_eval,
        }

    ref_rows: list[dict[str, Any]] = []
    price_lower_all = True
    dif_higher_all = True
    p0_low = float(low_arr[p0_idx])
    p0_dif = float(dif[p0_idx])

    for rv in refs:
        r0_idx = _valley_price_low_idx(low_arr, rv)
        r0_low = float(low_arr[r0_idx])
        r0_dif = float(dif[r0_idx])
        pl = p0_low < r0_low
        dh = p0_dif > r0_dif
        price_lower_all = price_lower_all and pl
        dif_higher_all = dif_higher_all and dh
        ref_rows.append(
            {
                "peak_date": dates[rv.peak_idx],
                "golden_cross_date": dates[rv.golden_cross_idx] if rv.golden_cross_idx is not None else None,
                "p0_date": dates[r0_idx],
                "p0_low": r0_low,
                "p0_dif": r0_dif,
                "price_lower": pl,
                "dif_higher": dh,
            }
        )

    passed = price_lower_all and dif_higher_all
    return {
        "passed": passed,
        "reason": None if passed else "divergence_failed",
        "price_lower": price_lower_all,
        "macd_higher": dif_higher_all,
        "price_lower_all": price_lower_all,
        "dif_higher_all": dif_higher_all,
        "p0_date": dates[p0_idx],
        "p0_low": p0_low,
        "p0_dif": p0_dif,
        "eval_date": dates[cd13_idx],
        "closure_progress_eval": progress_eval,
        "closure_progress_p0": progress_p0,
        "target_valley": _macd_valley_to_dict(dates, target),
        "refs_found": len(ref_rows),
        "refs": ref_rows,
        "macd_hist_p0": float(hist[p0_idx]) if pd.notna(hist[p0_idx]) else None,
        "macd_hist_cd13": float(hist[cd13_idx]) if pd.notna(hist[cd13_idx]) else None,
        "macd_dif_p0": p0_dif,
        "macd_dif_cd13": float(dif[cd13_idx]),
        "macd_hist_setup9": float(hist[p0_idx]) if pd.notna(hist[p0_idx]) else None,
        "macd_dif_setup9": p0_dif,
        "macd_div_type": "dif_valley" if passed else None,
    }


def find_setup_cycles(
    dates: list[str],
    closes: np.ndarray,
    *,
    opens: np.ndarray | None = None,
    lows: np.ndarray | None = None,
    highs: np.ndarray | None = None,
    vols: np.ndarray | None = None,
    turnovers: np.ndarray | None = None,
) -> list[SetupCycle]:
    cycles: list[SetupCycle] = []
    setup_count = 0
    bar_buf: list[SetupBar] = []

    for i in range(len(dates)):
        if i < 4:
            continue
        ref_close = float(closes[i - 4])
        cur_close = float(closes[i])
        passed = cur_close < ref_close
        if passed:
            setup_count += 1
            bar_buf.append(
                SetupBar(
                    seq=setup_count,
                    trade_date=dates[i],
                    close=cur_close,
                    ref_date=dates[i - 4],
                    ref_close=ref_close,
                    passed=True,
                )
            )
            if setup_count == 9:
                cycles.append(
                    SetupCycle(
                        setup_9_date=dates[i],
                        setup_9_idx=i,
                        setup_bars=list(bar_buf),
                        setup_9_close=cur_close,
                        setup_9_low=float(lows[i]) if lows is not None else cur_close,
                        setup_9_open=float(opens[i]) if opens is not None else cur_close,
                        setup_9_high=float(highs[i]) if highs is not None else cur_close,
                        setup_9_vol=float(vols[i]) if vols is not None and not np.isnan(vols[i]) else None,
                        setup_9_turnover_rate=(
                            float(turnovers[i])
                            if turnovers is not None and not np.isnan(turnovers[i])
                            else None
                        ),
                    )
                )
                setup_count = 0
                bar_buf = []
        else:
            setup_count = 0
            bar_buf = []
    return cycles


def run_countdown(
    dates: list[str],
    closes: np.ndarray,
    lows: np.ndarray,
    *,
    start_idx: int,
    end_idx: int | None = None,
) -> CountdownState:
    """自 start_idx（九转次日）起至 end_idx（含）计算 Countdown。"""
    state = CountdownState()
    last = end_idx if end_idx is not None else len(dates) - 1
    for j in range(max(start_idx, 2), last + 1):
        if j < 2:
            continue
        ref_low = float(lows[j - 2])
        cur_close = float(closes[j])
        if cur_close > ref_low:
            continue
        extra: dict[str, Any] | None = None
        accepted = True
        if state.cd_count == 12:
            cd8_date = state.cd_dates[7]
            di8 = dates.index(cd8_date)
            c8_close = float(closes[di8])
            cur_low = float(lows[j])
            ok_13v8 = cur_low <= c8_close
            extra = {
                "c8_close": c8_close,
                "c8_date": cd8_date,
                "low_t13": cur_low,
                "passed": ok_13v8,
            }
            if not ok_13v8:
                accepted = False
        if not accepted:
            continue
        state.cd_count += 1
        state.cd_dates.append(dates[j])
        state.cd_last_date = dates[j]
        state.countdown_bars.append(
            CountdownBar(
                seq=state.cd_count,
                trade_date=dates[j],
                close=cur_close,
                ref_date=dates[j - 2],
                ref_low=ref_low,
                passed=True,
                extra_13v8=extra,
            )
        )
        if state.cd_count == 13:
            state.countdown_13_date = dates[j]
            break
    return state


def _date_in_window(d: str, window_start: str, scan_date: str) -> bool:
    return window_start <= d <= scan_date


def _trading_days_offset(dates: list[str], from_date: str, to_date: str) -> int | None:
    """两日在 dates 序列中的下标差 to_date − from_date（交易日历偏移）。"""
    try:
        i0 = dates.index(from_date)
        i1 = dates.index(to_date)
    except ValueError:
        return None
    return i1 - i0


def countdown_start_date(
    dates: list[str],
    setup_9_idx: int,
    cd_state: CountdownState,
) -> str | None:
    """十三转区间起始日：有计数取首次计数日，否则为九转完成次日（阶段起算日）。"""
    if cd_state.countdown_bars:
        return cd_state.countdown_bars[0].trade_date
    if setup_9_idx + 1 < len(dates):
        return dates[setup_9_idx + 1]
    return None


def select_active_setup(
    cycles: list[SetupCycle],
    *,
    window_start: str,
    scan_date: str,
) -> SetupCycle | None:
    in_window = [c for c in cycles if _date_in_window(c.setup_9_date, window_start, scan_date)]
    if not in_window:
        return None
    return max(in_window, key=lambda c: c.setup_9_date)


def evaluate_stock_td(
    df: pd.DataFrame,
    *,
    scan_date: str,
    window_start: str,
    params: TdSequentialParams | None = None,
) -> dict[str, Any] | None:
    """单股评估；无有效九转则返回 None。"""
    p = params or TdSequentialParams()
    df = df.sort_values("trade_date").reset_index(drop=True)
    dates = [str(d) for d in df["trade_date"]]
    if scan_date not in dates:
        return None
    scan_idx = dates.index(scan_date)

    closes = df["close"].astype(float).to_numpy()
    lows = df["low"].astype(float).to_numpy()
    highs = df["high"].astype(float).to_numpy()
    opens = df["open"].astype(float).to_numpy()
    vols = df["vol"].astype(float).to_numpy() if "vol" in df.columns else np.full(len(df), np.nan)
    turns = (
        df["turnover_rate"].astype(float).to_numpy()
        if "turnover_rate" in df.columns
        else np.full(len(df), np.nan)
    )

    cycles = find_setup_cycles(dates, closes, opens=opens, lows=lows, highs=highs, vols=vols, turnovers=turns)
    active = select_active_setup(cycles, window_start=window_start, scan_date=scan_date)
    if active is None:
        return None

    cd_state = run_countdown(
        dates,
        closes,
        lows,
        start_idx=active.setup_9_idx + 1,
        end_idx=scan_idx,
    )

    vol_series = pd.Series(vols)
    turn_series = pd.Series(turns)
    vol_ma5 = _vol_ma5(vol_series, active.setup_9_idx)
    if vol_ma5 is None:
        vol_ma5 = _vol_ma5(turn_series, active.setup_9_idx)

    vp = evaluate_vol_price(
        open_=active.setup_9_open,
        high=active.setup_9_high,
        low=active.setup_9_low,
        close=active.setup_9_close,
        vol=active.setup_9_vol,
        turnover_rate=active.setup_9_turnover_rate,
        vol_ma5=vol_ma5,
        params=p,
    )

    cd_start = countdown_start_date(dates, active.setup_9_idx, cd_state)
    gap_setup_to_cd = (
        _trading_days_offset(dates, active.setup_9_date, cd_start)
        if cd_start
        else None
    )
    if gap_setup_to_cd is None:
        gap_setup_to_cd = 9999
    near13 = (
        vp["passed"]
        and cd_state.cd_count >= p.countdown_near_min
        and cd_state.cd_count <= p.countdown_near_max
        and gap_setup_to_cd <= p.countdown_after_setup_days
    )

    cd13_in_window = (
        cd_state.countdown_13_date is not None
        and _date_in_window(cd_state.countdown_13_date, window_start, scan_date)
    )
    col4 = vp["passed"] and cd_state.cd_count == 13 and cd13_in_window

    closes_s = pd.Series(closes)
    cd13_idx = dates.index(cd_state.countdown_13_date) if cd_state.countdown_13_date else None
    cd_start_idx = (
        dates.index(cd_state.countdown_bars[0].trade_date)
        if cd_state.countdown_bars
        else active.setup_9_idx + 1
    )
    macd_div = evaluate_macd_divergence(
        closes_s,
        pd.Series(lows),
        dates,
        cd_start_idx,
        cd13_idx,
        p,
    ) if col4 else {"passed": False}

    col1 = True
    col2 = vp["passed"]
    col3 = near13
    col5 = col4 and macd_div.get("passed", False)

    max_col = 0
    if col1:
        max_col = 1
    if col2:
        max_col = 2
    if col3:
        max_col = 3
    if col4:
        max_col = 4
    if col5:
        max_col = 5

    bars_gap = None
    if cd13_idx is not None:
        bars_gap = cd13_idx - active.setup_9_idx

    stop_loss = active.setup_9_low * (1.0 - p.stop_loss_pct) if active.setup_9_low else None

    detail = build_detail_json(
        stock_code=str(df["stock_code"].iloc[0]) if "stock_code" in df.columns else "",
        stock_name=str(df["stock_name"].iloc[0]) if "stock_name" in df.columns else "",
        scan_date=scan_date,
        lookback_days=p.lookback_days,
        active=active,
        cd_state=cd_state,
        vp=vp,
        near13={
            "passed": near13,
            "cd_count": cd_state.cd_count,
            "gap_setup_to_cd_days": gap_setup_to_cd,
            "countdown_start_date": cd_start,
        },
        macd_div=macd_div,
        max_col=max_col,
        params=p,
        countdown_start_date=cd_start,
        gap_setup_to_cd_days=gap_setup_to_cd,
    )

    return {
        "setup_9_date": active.setup_9_date,
        "setup_9_close": active.setup_9_close,
        "setup_9_low": active.setup_9_low,
        "setup_9_vol": active.setup_9_vol,
        "setup_9_turnover_rate": active.setup_9_turnover_rate,
        "cd_count": cd_state.cd_count,
        "cd_last_date": cd_state.cd_last_date,
        "countdown_13_date": cd_state.countdown_13_date,
        "countdown_start_date": cd_start,
        "gap_setup_to_cd_days": gap_setup_to_cd,
        "col1_setup9": int(col1),
        "col2_vol_price": int(col2),
        "col3_near13": int(col3),
        "col4_cd13": int(col4),
        "col5_macd_div": int(col5),
        "max_col": max_col,
        "vol_tag": vp["vol_tag"],
        "lower_shadow_ratio": vp["lower_shadow_ratio"],
        "upper_shadow_ratio": vp["upper_shadow_ratio"],
        "body_ratio": vp["body_ratio"],
        "vol_price_rejected_bear": int(vp.get("rejected_bear", False)),
        "macd_hist_setup9": macd_div.get("macd_hist_setup9"),
        "macd_hist_cd13": macd_div.get("macd_hist_cd13"),
        "macd_div_type": macd_div.get("macd_div_type"),
        "bars_setup_to_cd13": bars_gap,
        "stop_loss_price": stop_loss,
        "days_since_setup": gap_setup_to_cd,
        "detail_json": json.dumps(detail, ensure_ascii=False),
        "detail": detail,
    }


def build_detail_json(
    *,
    stock_code: str,
    stock_name: str,
    scan_date: str,
    lookback_days: int,
    active: SetupCycle,
    cd_state: CountdownState,
    vp: dict[str, Any],
    near13: dict[str, Any],
    macd_div: dict[str, Any],
    max_col: int,
    params: TdSequentialParams,
    countdown_start_date: str | None = None,
    gap_setup_to_cd_days: int | None = None,
) -> dict[str, Any]:
    return {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "scan_trade_date": scan_date,
        "lookback_days": lookback_days,
        "active_setup_9_date": active.setup_9_date,
        "countdown_start_date": countdown_start_date,
        "gap_setup_to_cd_days": gap_setup_to_cd_days,
        "setup_bars": [
            {
                "seq": b.seq,
                "trade_date": b.trade_date,
                "close": b.close,
                "ref_date": b.ref_date,
                "ref_close": b.ref_close,
                "condition": "close < ref_close",
                "passed": b.passed,
            }
            for b in active.setup_bars
        ],
        "countdown_bars": [
            {
                "seq": b.seq,
                "trade_date": b.trade_date,
                "close": b.close,
                "ref_date": b.ref_date,
                "ref_low": b.ref_low,
                "condition": "close <= ref_low",
                "passed": b.passed,
                "extra_13v8": b.extra_13v8,
            }
            for b in cd_state.countdown_bars
        ],
        "filters": {
            "vol_price": {
                "passed": vp["passed"],
                "vol_tag": vp["vol_tag"],
                "lower_ratio": vp["lower_shadow_ratio"],
                "upper_ratio": vp["upper_shadow_ratio"],
                "body_ratio": vp["body_ratio"],
                "rejected_bear": vp.get("rejected_bear", False),
            },
            "near13": near13,
            "macd_div": macd_div,
        },
        "max_col": max_col,
        "stop_loss_price": active.setup_9_low * (1.0 - params.stop_loss_pct),
    }


def setup_bar_to_dict(b: SetupBar) -> dict[str, Any]:
    return {
        "seq": b.seq,
        "trade_date": b.trade_date,
        "close": b.close,
        "ref_date": b.ref_date,
        "ref_close": b.ref_close,
        "passed": b.passed,
    }
