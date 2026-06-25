"""神奇九转计算单测。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from td_sequential_common import (
    TdSequentialParams,
    evaluate_stock_td,
    evaluate_vol_price,
    find_setup_cycles,
    run_countdown,
    select_active_setup,
)


def _make_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_setup_interrupt_resets():
    dates = [f"2026-01-{i:02d}" for i in range(1, 16)]
    closes = np.array([10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 2, 1, 0.9, 0.8, 0.7], dtype=float)
    cycles = find_setup_cycles(dates, closes)
    assert len(cycles) >= 1


def test_setup_nine_consecutive():
    dates = [f"2026-01-{i:02d}" for i in range(1, 20)]
    closes = np.linspace(20, 10, 19)
    lows = closes - 0.5
    cycles = find_setup_cycles(dates, closes, lows=lows)
    assert len(cycles) == 1
    assert cycles[0].setup_9_date == dates[12]


def test_select_latest_setup_in_window():
    c1 = type("C", (), {"setup_9_date": "2026-01-10"})()
    c2 = type("C", (), {"setup_9_date": "2026-01-15"})()
    active = select_active_setup([c1, c2], window_start="2026-01-01", scan_date="2026-01-20")
    assert active.setup_9_date == "2026-01-15"


def test_countdown_non_consecutive():
    dates = [f"2026-01-{i:02d}" for i in range(1, 25)]
    closes = np.array([10.0] * 24)
    lows = np.array([10.0] * 24)
  # 从 idx=10 起每隔几天满足 close<=low[i-2]
    lows[12] = 11.0
    lows[15] = 11.0
    closes[12] = 10.5
    closes[15] = 10.5
    state = run_countdown(dates, closes, lows, start_idx=10, end_idx=20)
    assert state.cd_count >= 1


def test_vol_price_shrink_or_hammer():
    vp = evaluate_vol_price(
        open_=10.0,
        high=10.5,
        low=9.0,
        close=10.2,
        vol=79.0,
        turnover_rate=None,
        vol_ma5=100.0,
        params=TdSequentialParams(),
    )
    assert vp["passed"] is True
    assert vp["vol_tag"] == "shrink"


def test_vol_price_reject_bear():
    vp = evaluate_vol_price(
        open_=10.0,
        high=10.1,
        low=9.0,
        close=9.05,
        vol=150.0,
        turnover_rate=None,
        vol_ma5=100.0,
        params=TdSequentialParams(),
    )
    assert vp["passed"] is False
    assert vp["rejected_bear"] is True


def test_evaluate_stock_td_col1():
    dates = [f"2026-01-{i:02d}" for i in range(1, 25)]
    n = len(dates)
    closes = np.linspace(30, 10, n)
    lows = closes - 1
    highs = closes + 1
    opens = closes
    vols = np.full(n, 1000.0)
    df = _make_df(
        [
            {
                "trade_date": d,
                "stock_code": "600000",
                "open": opens[i],
                "high": highs[i],
                "low": lows[i],
                "close": closes[i],
                "vol": vols[i],
            }
            for i, d in enumerate(dates)
        ]
    )
    scan = dates[-1]
    window_start = dates[0]
    ev = evaluate_stock_td(df, scan_date=scan, window_start=window_start)
    assert ev is not None
    assert ev["col1_setup9"] == 1
    assert ev["max_col"] >= 1
