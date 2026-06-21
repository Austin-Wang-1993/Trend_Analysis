"""反包打板信号：纯计算逻辑（无 I/O）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SignalParams:
    pct_threshold: float = 9.8
    engulf_mode: str = "high"  # high | body
    cross_body_ratio: float = 0.1
    long_upper_ratio: float = 1.0


def classify_t1_shapes(
    open_: float,
    high: float,
    low: float,
    close: float,
    *,
    cross_body_ratio: float = 0.1,
    long_upper_ratio: float = 1.0,
) -> list[str]:
    """T-1 K 线形态标签。"""
    tags: list[str] = []
    if close < open_:
        tags.append("yin")
    body = abs(close - open_)
    amplitude = high - low
    if amplitude > 0 and body / amplitude <= cross_body_ratio:
        tags.append("cross")
    upper = high - max(open_, close)
    if body > 0 and upper / body >= long_upper_ratio:
        tags.append("long_upper")
    return tags


def is_weak_t1(shapes: list[str]) -> bool:
    return bool(shapes)


def pct_change(last_price: float, pre_close: float) -> float | None:
    if pre_close is None or pre_close <= 0 or last_price is None:
        return None
    return (last_price - pre_close) / pre_close * 100.0


def check_engulf(
    mode: str,
    *,
    last_price: float,
    today_open: float | None,
    pre_open: float,
    pre_high: float,
    pre_close: float,
) -> tuple[bool, str | None]:
    if mode == "body":
        if today_open is None:
            return False, None
        ok = today_open <= pre_close and last_price >= pre_open
        return ok, "body" if ok else None
    ok = last_price > pre_high
    return ok, "high" if ok else None


def is_limit_up_price(last_price: float, up_limit: float | None) -> bool:
    if up_limit is None or last_price is None:
        return False
    return last_price >= up_limit - 1e-4


def evaluate_signal(
    *,
    last_price: float,
    pre_close: float,
    pre_open: float,
    pre_high: float,
    pre_low: float,
    pre_close_t1: float,
    today_open: float | None,
    up_limit: float | None,
    params: SignalParams | None = None,
) -> dict[str, Any]:
    """单票信号评估。pre_* 为 T-1 日 K（open/high/low/close）。"""
    p = params or SignalParams()
    shapes = classify_t1_shapes(
        pre_open,
        pre_high,
        pre_low,
        pre_close_t1,
        cross_body_ratio=p.cross_body_ratio,
        long_upper_ratio=p.long_upper_ratio,
    )
    weak = is_weak_t1(shapes)
    engulf_ok, engulf_type = check_engulf(
        p.engulf_mode,
        last_price=last_price,
        today_open=today_open,
        pre_open=pre_open,
        pre_high=pre_high,
        pre_close=pre_close_t1,
    )
    hit_pattern = bool(weak and engulf_ok)
    pct = pct_change(last_price, pre_close)
    hit_pct = pct is not None and pct >= p.pct_threshold
    score = int(hit_pct) + int(hit_pattern)
    return {
        "pct_change": pct,
        "t1_shape": ",".join(shapes) if shapes else "",
        "is_weak_t1": weak,
        "is_engulf": engulf_ok,
        "engulf_type": engulf_type,
        "hit_pct": int(hit_pct),
        "hit_pattern": int(hit_pattern),
        "score": score,
        "signal_hit": score >= 2,
        "is_limit_up": is_limit_up_price(last_price, up_limit),
    }


def is_main_board_code(stock_code: str) -> bool:
    code = str(stock_code).split(".")[0]
    if len(code) != 6 or not code.isdigit():
        return False
    return code.startswith("60") or code.startswith("00")


def is_st_name(name: str | None) -> bool:
    if not name:
        return False
    n = str(name).upper()
    return "ST" in n
