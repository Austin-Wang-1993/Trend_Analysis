"""火车轨 SXHCG / RPS 单元测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from train_track_common import (  # noqa: E402
    TrainTrackParams,
    evaluate_sxhcg,
    is_st_name,
    ma_touch_tag,
    parse_train_track_params,
)


def _rising_closes(n: int, start: float = 10.0, step: float = 0.05) -> pd.Series:
    vals = [start + i * step for i in range(n)]
    return pd.Series(vals)


def test_is_st_name() -> None:
    assert is_st_name("*ST海华")
    assert is_st_name("ST某某")
    assert not is_st_name("贵州茅台")


def test_ma_touch_tag() -> None:
    assert ma_touch_tag(1.0, None, 2.0) == "ma5"
    assert ma_touch_tag(None, -1.5, 2.0) == "ma10"
    assert ma_touch_tag(3.0, 3.0, 2.0) == ""


def test_parse_train_track_params() -> None:
    p = parse_train_track_params({"train_track_rps_sum_min": "190", "train_track_recent_20d_pct_max": "25"})
    assert p.rps_sum_min == 190
    assert p.recent_20d_pct_max == 25


def test_evaluate_sxhcg_pass() -> None:
    closes = _rising_closes(260)
    highs = closes + 0.1
    ev = evaluate_sxhcg(
        closes,
        highs,
        turnover=5.0,
        rps120=95.0,
        rps250=92.0,
        params=TrainTrackParams(count_ma250_30_min=10),
    )
    assert ev["hit_sxhcg1"] == 1
    assert ev["sxhcg_pass"] == 1
    assert ev["pass"] is True


def test_evaluate_sxhcg_fail_rps() -> None:
    closes = _rising_closes(260)
    highs = closes + 0.1
    ev = evaluate_sxhcg(
        closes,
        highs,
        turnover=5.0,
        rps120=80.0,
        rps250=80.0,
        params=TrainTrackParams(rps_sum_min=185),
    )
    assert ev["hit_sxhcg1"] == 0
    assert ev["pass"] == 0


def test_recent_calm_filter() -> None:
    closes = _rising_closes(260, step=0.5)
    highs = closes + 0.1
    ev = evaluate_sxhcg(
        closes,
        highs,
        turnover=5.0,
        rps120=95.0,
        rps250=92.0,
        params=TrainTrackParams(recent_20d_pct_max=5),
    )
    assert ev["hit_recent_calm"] == 0
    assert ev["pass"] == 0
