"""signal_common 单元测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from signal_common import (  # noqa: E402
    SignalParams,
    check_engulf,
    classify_t1_shapes,
    evaluate_signal,
    is_main_board_code,
    is_st_name,
    pct_change,
)


def test_main_board_filter() -> None:
    assert is_main_board_code("600519")
    assert is_main_board_code("000001")
    assert not is_main_board_code("300750")
    assert not is_main_board_code("688981")
    assert is_st_name("*ST海华")
    assert not is_st_name("贵州茅台")


def test_t1_shapes() -> None:
    assert "yin" in classify_t1_shapes(10, 11, 9, 9.5)
    assert "cross" in classify_t1_shapes(10, 10.05, 9.95, 10.01)
    assert "long_upper" in classify_t1_shapes(10, 12, 9.9, 10.1)


def test_engulf_high() -> None:
    ok, typ = check_engulf("high", last_price=11, today_open=10, pre_open=10, pre_high=10.5, pre_close=9.8)
    assert ok and typ == "high"


def test_evaluate_full_hit() -> None:
    ev = evaluate_signal(
        last_price=11.0,
        pre_close=10.0,
        pre_open=10.5,
        pre_high=10.8,
        pre_low=9.5,
        pre_close_t1=9.8,
        today_open=10.2,
        up_limit=11.0,
        params=SignalParams(pct_threshold=9.8),
    )
    assert ev["hit_pct"] == 1
    assert ev["hit_pattern"] == 1
    assert ev["score"] == 2
    assert ev["signal_hit"] is True


def test_pct_change() -> None:
    assert pct_change(10.98, 10.0) == pytest.approx(9.8)
