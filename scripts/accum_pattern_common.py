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
    end, rise, peak, start_low, _, reason = _run_expand_phase_detail(
        t0_idx, dates, opens, closes, vols, params
    )
    if reason == "price_rise_low":
        return None, rise, peak, start_low
    if reason is not None:
        return None, 0.0, peak, start_low
    return end, rise, peak, start_low


def _run_expand_phase_detail(
    t0_idx: int,
    dates: list[str],
    opens: np.ndarray,
    closes: np.ndarray,
    vols: np.ndarray,
    params: AccumPatternParams,
) -> tuple[int | None, float, float, float, list[dict[str, Any]], str | None]:
    """返回 (expand_end, rise, peak, start_low, day_logs, fail_reason)。"""
    miss_consec = 0
    expand_end: int | None = None
    start_low = _body_low(float(opens[t0_idx]), float(closes[t0_idx]))
    peak_high = start_low
    day_logs: list[dict[str, Any]] = []
    fail_reason: str | None = None

    for i in range(t0_idx, len(dates)):
        k = i - t0_idx
        ma5 = _vol_ma5(vols, i)
        if ma5 is None:
            fail_reason = "ma5_unavailable"
            break
        vol = float(vols[i])
        is_t0 = i == t0_idx
        ok = _vol_expand_ok(vol, ma5, k=k, params=params, is_t0=is_t0)
        thr = (
            params.vol_expand_trigger
            if is_t0
            else _expand_threshold(params, k)
        )
        day_logs.append(
            {
                "trade_date": dates[i],
                "k": k,
                "vol": vol,
                "vol_ma5": ma5,
                "threshold_mult": thr,
                "need_vol": thr * ma5,
                "vol_ratio": vol / ma5 if ma5 > 0 else None,
                "passed": ok,
                "is_t0": is_t0,
            }
        )
        if not ok:
            miss_consec += 1
            if miss_consec >= params.vol_expand_max_consecutive_miss:
                expand_end = i - params.vol_expand_max_consecutive_miss
                fail_reason = "consecutive_miss"
                break
        else:
            miss_consec = 0
            expand_end = i
            bh = _body_high(float(opens[i]), float(closes[i]))
            if bh > peak_high:
                peak_high = bh

    if expand_end is None or expand_end < t0_idx:
        return None, 0.0, peak_high, start_low, day_logs, fail_reason or "no_expand_end"

    rise = (peak_high - start_low) / start_low if start_low > 0 else 0.0
    n_days = expand_end - t0_idx + 1
    if n_days < params.vol_min_days:
        return expand_end, rise, peak_high, start_low, day_logs, "n_too_short"
    if rise < params.price_rise_min:
        return expand_end, rise, peak_high, start_low, day_logs, "price_rise_low"
    return expand_end, rise, peak_high, start_low, day_logs, None


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


def _mk_step(
    step_id: str,
    name: str,
    status: str,
    message: str,
    **extra: Any,
) -> dict[str, Any]:
    return {"id": step_id, "name": name, "status": status, "message": message, **extra}


_EXPAND_FAIL_ZH: dict[str, str] = {
    "consecutive_miss": "放量期连续不达标达到上限，放量段结束",
    "ma5_unavailable": "MA5 数据不足，无法继续放量判定",
    "no_expand_end": "未形成有效放量段",
    "n_too_short": "放量天数 N 低于最短要求",
    "price_rise_low": "实体涨幅未达下限",
}

_WASH_FAIL_ZH: dict[str, str] = {
    "reset": "洗盘期再放量，形态应从此日重置",
    "consecutive_over": "洗盘期连续缩量超标",
    "over_days": "洗盘期缩量超标天数超过容忍",
    "no_wash_days": "截至扫描日尚未进入洗盘或洗盘无有效交易日",
    "before_wash": "扫描日仍在放量段内，洗盘尚未开始",
}


def diagnose_pattern_from_t0(
    dates: list[str],
    opens: np.ndarray,
    closes: np.ndarray,
    vols: np.ndarray,
    params: AccumPatternParams,
    *,
    t0_date: str,
    scan_date: str,
) -> dict[str, Any]:
    """对指定 T₀ 与扫描日逐步诊断，返回每步通过/失败及扫描器对比。"""
    steps: list[dict[str, Any]] = []
    failed_at: str | None = None

    if scan_date not in dates:
        steps.append(_mk_step("scan_date", "扫描日有效", "fail", f"扫描日 {scan_date} 不在 K 线窗口内"))
        return _diagnose_report(steps, failed_at="scan_date", t0_date=t0_date, scan_date=scan_date)
    if t0_date not in dates:
        steps.append(_mk_step("t0_date", "T₀ 在窗口内", "fail", f"T₀ {t0_date} 不在 K 线窗口内"))
        return _diagnose_report(steps, failed_at="t0_date", t0_date=t0_date, scan_date=scan_date)

    t0_idx = dates.index(t0_date)
    scan_idx = dates.index(scan_date)
    if t0_idx > scan_idx:
        steps.append(_mk_step("t0_order", "T₀ 不晚于扫描日", "fail", "T₀ 不能晚于扫描日"))
        return _diagnose_report(steps, failed_at="t0_order", t0_date=t0_date, scan_date=scan_date)

    if t0_idx < 5:
        steps.append(
            _mk_step(
                "history",
                "T₀ 前历史充足",
                "fail",
                f"T₀ 前不足 5 日 K 线（无法算 MA5），当前 idx={t0_idx}",
            )
        )
        return _diagnose_report(steps, failed_at="history", t0_date=t0_date, scan_date=scan_date)
    steps.append(_mk_step("history", "T₀ 前历史充足", "pass", "T₀ 前至少有 5 日 K 线"))

    ma5_t0 = _vol_ma5(vols, t0_idx)
    vol_t0 = float(vols[t0_idx])
    thr_t0 = params.vol_expand_trigger * (ma5_t0 or 0)
    t0_ok = ma5_t0 is not None and vol_t0 > thr_t0
    steps.append(
        _mk_step(
            "t0_trigger",
            "T₀ 放量触发",
            "pass" if t0_ok else "fail",
            (
                f"量 {vol_t0:.0f} {'>' if t0_ok else '≤'} "
                f"{params.vol_expand_trigger}×MA5={thr_t0:.0f}（MA5={ma5_t0:.0f}）"
            ),
            vol=vol_t0,
            vol_ma5=ma5_t0,
            threshold_mult=params.vol_expand_trigger,
        )
    )
    if not t0_ok:
        return _diagnose_report(steps, failed_at="t0_trigger", t0_date=t0_date, scan_date=scan_date)

    expand_end, rise, peak_high, start_low, expand_days, expand_fail = _run_expand_phase_detail(
        t0_idx, dates, opens, closes, vols, params
    )
    n_days = (expand_end - t0_idx + 1) if expand_end is not None and expand_end >= t0_idx else 0
    expand_pass = expand_fail is None
    steps.append(
        _mk_step(
            "expand_volume",
            "T₁ 放量延续",
            "pass" if expand_pass else "fail",
            (
                "放量段内逐日量能达标"
                if expand_pass
                else _EXPAND_FAIL_ZH.get(expand_fail or "", expand_fail or "放量段失败")
            ),
            expand_end_date=dates[expand_end] if expand_end is not None and expand_end >= 0 else None,
            n_days=n_days,
            days=expand_days,
        )
    )
    if not expand_pass:
        return _diagnose_report(
            steps,
            failed_at="expand_volume",
            t0_date=t0_date,
            scan_date=scan_date,
            expand_days=expand_days,
        )

    steps.append(
        _mk_step(
            "expand_n",
            f"T₁ 最短放量 N≥{params.vol_min_days}",
            "pass",
            f"N={n_days}",
            n_days=n_days,
        )
    )
    rise_pct = round(rise * 100, 2)
    rise_ok = rise >= params.price_rise_min
    steps.append(
        _mk_step(
            "expand_price",
            f"T₁ 实体涨幅≥{params.price_rise_min * 100:.0f}%",
            "pass" if rise_ok else "fail",
            f"实体涨幅 {rise_pct}%（峰值实体 {peak_high:.3f} / 起点低 {start_low:.3f}）",
            price_rise_pct=rise_pct,
        )
    )
    if not rise_ok:
        return _diagnose_report(
            steps,
            failed_at="expand_price",
            t0_date=t0_date,
            scan_date=scan_date,
            expand_days=expand_days,
        )

    wash_start = expand_end + 1
    if wash_start > scan_idx:
        steps.append(
            _mk_step(
                "wash_start",
                "T₂ 洗盘已开始",
                "fail",
                f"放量结束于 {dates[expand_end]}，扫描日 {scan_date} 仍在放量段或刚结束",
            )
        )
        return _diagnose_report(
            steps,
            failed_at="wash_start",
            t0_date=t0_date,
            scan_date=scan_date,
            expand_days=expand_days,
        )
    steps.append(
        _mk_step(
            "wash_start",
            "T₂ 洗盘已开始",
            "pass",
            f"洗盘自 {dates[wash_start]} 起（放量结束 {dates[expand_end]}）",
        )
    )

    m_target = max(1, int(params.wash_mult * n_days))
    wash_days: list[dict[str, Any]] = []
    over_days = 0
    consec_over = 0
    wash_fail: str | None = None
    fail_date: str | None = None
    wash_low = peak_high
    last_idx = min(scan_idx, wash_start + m_target - 1)

    for i in range(wash_start, last_idx + 1):
        ma5 = _vol_ma5(vols, i)
        if ma5 is None:
            wash_fail = "ma5_unavailable"
            fail_date = dates[i]
            break
        vol = float(vols[i])
        if vol > params.vol_reset_trigger * ma5:
            wash_fail = "reset"
            fail_date = dates[i]
            wash_days.append(
                {
                    "trade_date": dates[i],
                    "vol": vol,
                    "vol_ma5": ma5,
                    "vol_ratio": vol / ma5,
                    "passed": False,
                    "reason": "reset",
                }
            )
            break
        over = vol >= params.vol_shrink_max * ma5
        passed = not over
        if over:
            over_days += 1
            consec_over += 1
            reason = None
            if consec_over >= params.vol_wash_max_consecutive_over:
                wash_fail = "consecutive_over"
                fail_date = dates[i]
                reason = "consecutive_over"
            elif over_days > params.vol_wash_max_over_days:
                wash_fail = "over_days"
                fail_date = dates[i]
                reason = "over_days"
        else:
            consec_over = 0
            reason = None
        bl = _body_low(float(opens[i]), float(closes[i]))
        if bl < wash_low:
            wash_low = bl
        wash_days.append(
            {
                "trade_date": dates[i],
                "vol": vol,
                "vol_ma5": ma5,
                "vol_ratio": vol / ma5 if ma5 > 0 else None,
                "shrink_max": params.vol_shrink_max * ma5,
                "passed": passed and wash_fail is None,
                "over": over,
                "reason": reason,
            }
        )
        if wash_fail:
            break

    wash_days_done = len([d for d in wash_days if d.get("passed")])
    if wash_days_done < 1 and wash_fail is None:
        wash_fail = "no_wash_days"

    wash_pass = wash_fail is None and wash_days_done >= 1
    steps.append(
        _mk_step(
            "wash_volume",
            "T₂ 缩量洗盘",
            "pass" if wash_pass else "fail",
            (
                f"已洗盘 {wash_days_done}/{m_target} 日"
                if wash_pass
                else _WASH_FAIL_ZH.get(wash_fail or "", wash_fail or "洗盘失败")
                + (f"（{fail_date}）" if fail_date else "")
            ),
            m_target=m_target,
            wash_days_done=wash_days_done,
            days=wash_days,
        )
    )
    if not wash_pass:
        return _diagnose_report(
            steps,
            failed_at="wash_volume",
            t0_date=t0_date,
            scan_date=scan_date,
            expand_days=expand_days,
            wash_days=wash_days,
        )

    rise_amp = peak_high - start_low
    dd_ratio = (peak_high - wash_low) / rise_amp if rise_amp > 0 else None
    dd_pct = round(dd_ratio * 100, 2) if dd_ratio is not None else None
    complete = wash_days_done >= m_target
    if complete:
        dd_ok = dd_ratio is not None and params.drawdown_min <= dd_ratio <= params.drawdown_max
        steps.append(
            _mk_step(
                "drawdown",
                f"洗盘回撤 {params.drawdown_min*100:.0f}%–{params.drawdown_max*100:.0f}%",
                "pass" if dd_ok else "fail",
                f"回撤 {dd_pct}%（洗盘完成需落入区间；进行中不要求）",
                drawdown_ratio=dd_pct,
            )
        )
        listed = dd_ok
        phase = "wash_complete"
        if not dd_ok:
            return _diagnose_report(
                steps,
                failed_at="drawdown",
                t0_date=t0_date,
                scan_date=scan_date,
                expand_days=expand_days,
                wash_days=wash_days,
                listed=False,
                phase=phase,
            )
    else:
        steps.append(
            _mk_step(
                "drawdown",
                "洗盘回撤（进行中）",
                "skip",
                f"洗盘未走完（{wash_days_done}/{m_target}），暂不考核回撤区间；当前回撤约 {dd_pct}%",
                drawdown_ratio=dd_pct,
            )
        )
        listed = True
        phase = "wash_in_progress"

    steps.append(
        _mk_step(
            "list_rule",
            "入选规则（锚点 B）",
            "pass" if listed else "fail",
            "洗盘进行中即入选" if phase == "wash_in_progress" else "洗盘完成且回撤达标才入选",
            phase=phase,
            listed=listed,
        )
    )

    pat_this = find_pattern_from_t0(t0_idx, scan_idx, dates, opens, closes, vols, params)
    pat_scanner = find_latest_pattern(dates, opens, closes, vols, params, scan_date)
    scanner_listed = pat_scanner is not None
    scanner_t0 = pat_scanner.t0_date if pat_scanner else None

    if pat_this and listed:
        if pat_scanner and pat_scanner.t0_idx != t0_idx:
            steps.append(
                _mk_step(
                    "scanner_compare",
                    "扫描器实际采用形态",
                    "warn",
                    f"您指定的 T₀={t0_date} 本身{'可入选' if listed else '不可入选'}，"
                    f"但全窗最近有效形态 T₀={scanner_t0}（更晚），扫描结果以它为准",
                    scanner_t0=scanner_t0,
                    scanner_listed=scanner_listed,
                )
            )
        else:
            steps.append(
                _mk_step(
                    "scanner_compare",
                    "扫描器实际采用形态",
                    "pass",
                    f"与扫描器一致，T₀={t0_date}，阶段 {phase}",
                    scanner_t0=scanner_t0,
                    scanner_listed=scanner_listed,
                )
            )
    elif listed and not scanner_listed:
        steps.append(
            _mk_step(
                "scanner_compare",
                "扫描器实际采用形态",
                "warn",
                "指定 T₀ 形态可入选，但扫描器未找到任何入选形态（请检查是否有更晚 T₀ 重置）",
                scanner_t0=None,
                scanner_listed=False,
            )
        )
    else:
        steps.append(
            _mk_step(
                "scanner_compare",
                "扫描器实际采用形态",
                "fail" if not scanner_listed else "warn",
                (
                    f"指定 T₀ 未入选；扫描器{'也未入选' if not scanner_listed else f'入选 T₀={scanner_t0}'}"
                ),
                scanner_t0=scanner_t0,
                scanner_listed=scanner_listed,
            )
        )

    return _diagnose_report(
        steps,
        failed_at=None,
        t0_date=t0_date,
        scan_date=scan_date,
        expand_days=expand_days,
        wash_days=wash_days,
        listed=listed and (pat_scanner is None or pat_scanner.t0_idx == t0_idx),
        phase=phase,
        n_days=n_days,
        m_target=m_target,
        wash_days_done=wash_days_done,
        price_rise_pct=rise_pct,
        drawdown_ratio=dd_pct,
        scanner_t0=scanner_t0,
        scanner_listed=scanner_listed,
    )


def _diagnose_report(
    steps: list[dict[str, Any]],
    *,
    failed_at: str | None,
    t0_date: str,
    scan_date: str,
    **extra: Any,
) -> dict[str, Any]:
    if failed_at is None:
        overall = "pass"
    elif any(s["status"] == "pass" for s in steps):
        overall = "partial"
    else:
        overall = "fail"
    return {
        "t0_date": t0_date,
        "scan_date": scan_date,
        "overall": overall,
        "failed_at": failed_at,
        "steps": steps,
        **extra,
    }


def diagnose_stock_accum(
    df: pd.DataFrame,
    *,
    t0_date: str,
    scan_date: str,
    params: AccumPatternParams,
) -> dict[str, Any]:
    if df.empty:
        return _diagnose_report(
            [_mk_step("data", "K 线数据", "fail", "无日线缓存")],
            failed_at="data",
            t0_date=t0_date,
            scan_date=scan_date,
        )
    sub = df.sort_values("trade_date").reset_index(drop=True)
    if scan_date not in sub["trade_date"].values:
        return _diagnose_report(
            [_mk_step("data", "K 线数据", "fail", f"扫描日 {scan_date} 无缓存")],
            failed_at="data",
            t0_date=t0_date,
            scan_date=scan_date,
        )
    ref_row = sub[sub["trade_date"] == scan_date]
    ref_adj = float(ref_row.iloc[0]["adj_factor"]) if not ref_row.empty else float("nan")
    if np.isnan(ref_adj) or ref_adj <= 0:
        ref_adj = float(sub.iloc[-1]["adj_factor"])
    sub = apply_qfq_panel(sub, ref_adj)
    dates = sub["trade_date"].astype(str).tolist()
    opens = sub["open"].astype(float).values
    closes = sub["close"].astype(float).values
    vols = sub["vol"].astype(float).values
    report = diagnose_pattern_from_t0(
        dates, opens, closes, vols, params, t0_date=t0_date, scan_date=scan_date
    )
    report["params"] = {
        "vol_expand_trigger": params.vol_expand_trigger,
        "vol_min_days": params.vol_min_days,
        "price_rise_min": params.price_rise_min,
        "wash_mult": params.wash_mult,
        "vol_shrink_max": params.vol_shrink_max,
        "drawdown_min": params.drawdown_min,
        "drawdown_max": params.drawdown_max,
    }
    return report


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
