"""量价吸筹计算单测。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from accum_pattern_common import (
    AccumPatternParams,
    _expand_polyline_rise,
    apply_qfq_panel,
    diagnose_pattern_from_t0,
    diagnose_stock_accum,
    evaluate_stock_accum,
    find_latest_pattern,
    run_expand_phase,
)


def _dates(n: int, start: str = "2026-01-01") -> list[str]:
    base = pd.Timestamp(start)
    return [(base + pd.Timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]


def test_expand_polyline_rise_connection_points():
    """折线涨幅：阳线收盘、阴线开盘连接；非 T₀ 实体低起点。"""
    dates = _dates(12)
    opens = np.full(12, 10.0)
    closes = np.full(12, 10.5)
    vols = np.full(12, 50.0)
    # T₀ 阳线，实体低 11；后续阴线连接点更低
    opens[5] = 11.0
    closes[5] = 12.0
    opens[6] = 9.5
    closes[6] = 10.0
    opens[7] = 10.5
    closes[7] = 13.2
    vols[5:8] = 500.0

    rise, poly_high, poly_low = _expand_polyline_rise(5, 7, opens, closes)
    # 连接点 12, 10, 13.2 → 最低 10，最高 13.2 → 32%
    assert poly_low == 10.0
    assert poly_high == 13.2
    assert abs(rise - 0.32) < 0.001

    params = AccumPatternParams(vol_min_days=3, price_rise_min=0.30)
    end, rise_out, _, _ = run_expand_phase(5, dates, opens, closes, vols, params)
    assert end == 7
    assert rise_out >= 0.30


def test_diagnose_price_fail_separate_from_volume():
    """涨幅失败应落在 expand_price，而非 expand_volume。"""
    dates = _dates(12)
    opens = np.full(12, 10.0)
    closes = np.full(12, 10.5)
    vols = np.full(12, 50.0)
    opens[5] = 11.0
    closes[5] = 11.2
    opens[6] = 11.1
    closes[6] = 11.0
    opens[7] = 11.0
    closes[7] = 11.3
    vols[5:8] = 500.0

    r = diagnose_pattern_from_t0(
        dates,
        opens,
        closes,
        vols,
        AccumPatternParams(vol_min_days=3, price_rise_min=0.30),
        t0_date=dates[5],
        scan_date=dates[10],
    )
    assert r["failed_at"] == "expand_price"
    vol_step = next(s for s in r["steps"] if s["id"] == "expand_volume")
    assert vol_step["status"] == "pass"


def test_expand_min_days_and_price_rise():
    dates = _dates(20)
    opens = np.full(20, 10.0)
    closes = np.full(20, 10.5)
    vols = np.full(20, 50.0)
    vols[5:9] = 500.0
    closes[7] = 14.0
    vols[9:] = 30.0

    params = AccumPatternParams(vol_min_days=3, price_rise_min=0.30)
    end, rise, peak, start_low = run_expand_phase(5, dates, opens, closes, vols, params)
    assert end is not None
    assert end - 5 + 1 >= 3
    assert rise >= 0.30


def test_wash_in_progress_listed():
    """锚点 B：洗盘进行中应入选。"""
    dates = _dates(30)
    n = len(dates)
    opens = np.full(n, 10.0)
    closes = np.full(n, 10.5)
    vols = np.full(n, 50.0)
    vols[5:9] = 500.0
    closes[7] = 14.0
    vols[9:12] = 30.0
    closes[9:12] = 13.0

    params = AccumPatternParams(wash_mult=1.5, vol_min_days=3, price_rise_min=0.25)
    scan_date = dates[10]
    pat = find_latest_pattern(dates, opens, closes, vols, params, scan_date)
    assert pat is not None
    assert pat.phase == "wash_in_progress"
    assert pat.listed is True


def test_wash_non_consecutive_over_allowed():
    """洗盘期分散超标日不失败，仅连续超标才失败。"""
    dates = _dates(20)
    opens = np.full(20, 10.0)
    closes = np.full(20, 10.5)
    vols = np.full(20, 50.0)
    vols[5:8] = 500.0
    closes[7] = 14.0
    # wash: low vol with two single-day overs separated by ok days
    vols[8:14] = 40.0
    vols[9] = 120.0   # over at wash day 2
    vols[11] = 120.0  # over again after reset, not consecutive

    params = AccumPatternParams(vol_min_days=3, price_rise_min=0.25, wash_mult=1.0)
    pat = find_latest_pattern(dates, opens, closes, vols, params, dates[9])
    assert pat is not None
    assert pat.phase in ("wash_in_progress", "wash_complete")


def test_wash_consecutive_over_fails():
    dates = _dates(18)
    opens = np.full(18, 10.0)
    closes = np.full(18, 10.5)
    vols = np.full(18, 50.0)
    vols[5:8] = 500.0
    closes[7] = 14.0
    vols[8:12] = 40.0
    vols[9] = 120.0
    vols[10] = 120.0  # consecutive over

    pat = find_latest_pattern(dates, opens, closes, vols, AccumPatternParams(price_rise_min=0.25), dates[11])
    assert pat is None


def test_wash_reset_restarts():
    dates = _dates(25)
    opens = np.full(25, 10.0)
    closes = np.full(25, 10.5)
    vols = np.full(25, 80.0)
    vols[5:9] = [250, 220, 200, 180]
    closes[8] = 14.0
    vols[9] = 50.0
    vols[10] = 250.0  # 重置触发

    params = AccumPatternParams()
    pat = find_latest_pattern(dates, opens, closes, vols, params, dates[11])
    # 重置后若尚未形成新形态则可能 None
    assert pat is None or pat.t0_idx >= 10


def test_apply_qfq_panel():
    df = pd.DataFrame(
        {
            "trade_date": ["2026-01-01", "2026-01-02"],
            "open": [10.0, 10.0],
            "close": [10.0, 10.0],
            "vol": [100.0, 100.0],
            "adj_factor": [2.0, 1.0],
        }
    )
    out = apply_qfq_panel(df, ref_adj=1.0)
    assert out.iloc[0]["close"] == 20.0
    assert out.iloc[1]["close"] == 10.0


def test_evaluate_stock_accum_df():
    rows = []
    for i in range(20):
        rows.append(
            {
                "trade_date": f"2026-01-{i+1:02d}",
                "open": 10.0,
                "close": 10.5,
                "vol": 50.0 if i < 5 or i >= 9 else 500.0,
                "adj_factor": 1.0,
            }
        )
    rows[7]["close"] = 14.0
    for j in range(9, 12):
        rows[j]["vol"] = 30.0
        rows[j]["close"] = 13.0
    df = pd.DataFrame(rows)
    ev = evaluate_stock_accum(df, scan_date="2026-01-11", params=AccumPatternParams(price_rise_min=0.25))
    assert ev is not None
    assert ev["phase"] in ("wash_in_progress", "wash_complete")


def test_diagnose_t0_trigger_fail():
    dates = _dates(15)
    opens = np.full(15, 10.0)
    closes = np.full(15, 10.5)
    vols = np.full(15, 50.0)
    r = diagnose_pattern_from_t0(
        dates,
        opens,
        closes,
        vols,
        AccumPatternParams(),
        t0_date=dates[8],
        scan_date=dates[12],
    )
    assert r["failed_at"] == "t0_trigger"
    assert r["overall"] in ("fail", "partial")


def test_diagnose_wash_in_progress_pass():
    dates = _dates(30)
    opens = np.full(30, 10.0)
    closes = np.full(30, 10.5)
    vols = np.full(30, 50.0)
    vols[5:9] = 500.0
    closes[7] = 14.0
    vols[9:12] = 30.0
    closes[9:12] = 13.0
    r = diagnose_pattern_from_t0(
        dates,
        opens,
        closes,
        vols,
        AccumPatternParams(price_rise_min=0.25),
        t0_date=dates[5],
        scan_date=dates[10],
    )
    assert r["failed_at"] is None
    assert r["overall"] == "pass"
    assert any(s["id"] == "wash_volume" and s["status"] == "pass" for s in r["steps"])


def test_diagnose_stock_accum_df():
    rows = []
    for i in range(20):
        rows.append(
            {
                "trade_date": f"2026-01-{i+1:02d}",
                "open": 10.0,
                "close": 10.5,
                "vol": 50.0 if i < 5 or i >= 9 else 500.0,
                "adj_factor": 1.0,
            }
        )
    rows[7]["close"] = 14.0
    for j in range(9, 12):
        rows[j]["vol"] = 30.0
        rows[j]["close"] = 13.0
    df = pd.DataFrame(rows)
    r = diagnose_stock_accum(
        df,
        t0_date="2026-01-06",
        scan_date="2026-01-11",
        params=AccumPatternParams(price_rise_min=0.25),
    )
    assert "steps" in r
    assert len(r["steps"]) >= 5
