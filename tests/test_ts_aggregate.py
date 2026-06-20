"""ts_aggregate 聚合纯函数离线测试。

运行：python3 tests/test_ts_aggregate.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import ts_aggregate as agg  # noqa: E402


def _stocks() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"stock_code": "000001", "turnover": 100.0, "active_buy": 60.0, "active_sell": 40.0,
             "net_active": 20.0, "main_buy": 30.0, "main_sell": 20.0, "pct_chg": 1.5},
            {"stock_code": "000002", "turnover": 200.0, "active_buy": 90.0, "active_sell": 110.0,
             "net_active": -20.0, "main_buy": 50.0, "main_sell": 70.0, "pct_chg": -2.0},
            {"stock_code": "000003", "turnover": 300.0, "active_buy": 150.0, "active_sell": 150.0,
             "net_active": 0.0, "main_buy": 80.0, "main_sell": 80.0, "pct_chg": 0.0},
        ]
    )


def _mapping() -> pd.DataFrame:
    # 000001,000002 → 行业A；000003 未在映射（→ 未分类）
    return pd.DataFrame(
        [
            {"sector_code": "A", "sector_name": "行业A", "sector_path": "L1 > L2 > 行业A", "stock_code": "000001"},
            {"sector_code": "A", "sector_name": "行业A", "sector_path": "L1 > L2 > 行业A", "stock_code": "000002"},
        ]
    )


def test_market_totals() -> None:
    m = agg.aggregate_market(_stocks())
    assert m["turnover"] == 600.0
    assert m["active_buy"] == 300.0
    assert m["active_sell"] == 300.0
    assert m["main_buy"] == 160.0
    assert m["stock_count"] == 3


def test_sector_sums_and_counts() -> None:
    out = agg.aggregate_sector(_stocks(), _mapping())
    a = out[out["sector_code"] == "A"].iloc[0]
    assert a["turnover"] == 300.0          # 100+200
    assert a["active_buy"] == 150.0
    assert a["main_buy"] == 80.0
    assert a["stock_count"] == 2
    assert a["up_count"] == 1              # 000001 涨
    assert a["down_count"] == 1            # 000002 跌
    assert a["flat_count"] == 0
    assert abs(a["up_ratio"] - 0.5) < 1e-9


def test_unmapped_row() -> None:
    out = agg.aggregate_sector(_stocks(), _mapping())
    u = out[out["sector_code"] == agg.UNMAPPED_CODE]
    assert len(u) == 1
    assert u.iloc[0]["turnover"] == 300.0  # 000003
    assert u.iloc[0]["flat_count"] == 1    # pct_chg=0


def test_turnover_pct_uses_market() -> None:
    out = agg.aggregate_sector(_stocks(), _mapping())
    a = out[out["sector_code"] == "A"].iloc[0]
    assert abs(a["turnover_pct"] - 300.0 / 600.0) < 1e-9
    assert abs(a["buy_pct"] - 150.0 / 300.0) < 1e-9


def test_catalog_zero_member() -> None:
    catalog = pd.DataFrame(
        [
            {"sector_code": "A", "sector_name": "行业A", "sector_path": "L1 > L2 > 行业A"},
            {"sector_code": "Z", "sector_name": "冷门行业", "sector_path": "L1 > L2 > 冷门行业"},
        ]
    )
    out = agg.aggregate_sector(_stocks(), _mapping(), catalog_df=catalog)
    z = out[out["sector_code"] == "Z"]
    assert len(z) == 1
    assert z.iloc[0]["turnover"] == 0.0
    assert z.iloc[0]["stock_count"] == 0
    assert z.iloc[0]["turnover_pct"] == 0.0


def test_exclude_unmapped() -> None:
    out = agg.aggregate_sector(_stocks(), _mapping(), include_unmapped=False)
    assert agg.UNMAPPED_CODE not in set(out["sector_code"])


def test_empty_mapping_all_unmapped() -> None:
    out = agg.aggregate_sector(_stocks(), pd.DataFrame(columns=["sector_code", "sector_name", "sector_path", "stock_code"]))
    assert len(out) == 1
    assert out.iloc[0]["sector_code"] == agg.UNMAPPED_CODE
    assert out.iloc[0]["turnover"] == 600.0


def test_columns_complete() -> None:
    out = agg.aggregate_sector(_stocks(), _mapping())
    assert list(out.columns) == agg.SECTOR_COLUMNS


def _run_all() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
