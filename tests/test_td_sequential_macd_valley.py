"""跨谷底 MACD 底背离单测。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from td_sequential_common import (
    TdSequentialParams,
    _valley_closure_progress,
    enumerate_macd_valleys,
    evaluate_macd_divergence,
)


def test_valley_closure_progress_half_rebound():
    dif = np.array([0.0, 1.0, 0.0, 0.5, 0.8])
    assert _valley_closure_progress(dif, peak_idx=1, trough_idx=2, eval_idx=3) == 0.5


def test_enumerate_macd_valley_detects_death_golden_pair():
  # 构造 DIF 峰后死叉再金叉
    dif = np.array(
        [0.0, 0.5, 1.0, 0.6, 0.2, -0.1, 0.0, 0.2, 0.4, 0.3],
        dtype=float,
    )
    dea = np.array(
        [0.0, 0.2, 0.4, 0.45, 0.4, 0.35, 0.3, 0.28, 0.3, 0.32],
        dtype=float,
    )
    valleys = enumerate_macd_valleys(dif, dea, end_idx=len(dif) - 1)
    closed = [v for v in valleys if v.closed]
    assert len(closed) >= 1
    assert closed[0].death_cross_idx is not None
    assert closed[0].golden_cross_idx is not None


def test_evaluate_macd_divergence_no_cd13():
    dates = [f"2026-01-{i:02d}" for i in range(1, 41)]
    closes = pd.Series(np.linspace(20, 10, 40))
    lows = pd.Series(closes - 0.5)
    r = evaluate_macd_divergence(closes, lows, dates, 10, None, TdSequentialParams())
    assert r["passed"] is False
    assert r["reason"] == "no_cd13"


def test_evaluate_macd_divergence_runs_on_declining_series():
    """长跌后反弹序列应能跑通流程（未必通过，但不应异常）。"""
    from datetime import date, timedelta

    base = date(2025, 1, 1)
    dates = [(base + timedelta(days=i)).isoformat() for i in range(90)]
    closes = np.concatenate(
        [
            np.linspace(30, 15, 60),
            np.linspace(15, 12, 20),
            np.linspace(12, 13, 10),
        ]
    )
    lows = closes - 0.3
    cd_start = 55
    cd13 = 79
    r = evaluate_macd_divergence(
        pd.Series(closes),
        pd.Series(lows),
        dates,
        cd_start,
        cd13,
        TdSequentialParams(),
    )
    assert "passed" in r
    assert r.get("reason") is not None or r["passed"]
