"""ts_store 写入/读取 round-trip 离线测试（临时 SQLite，无需 token）。

运行：python3 tests/test_ts_store.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import ts_aggregate as agg  # noqa: E402
from ts_store import TsStore  # noqa: E402


def _stocks():
    return pd.DataFrame([
        {"stock_code": "000001", "stock_name": "平安银行", "turnover": 100.0, "pct_chg": 1.5,
         "active_buy": 60.0, "active_sell": 40.0, "net_active": 20.0, "main_buy": 30.0, "main_sell": 20.0},
        {"stock_code": "000002", "stock_name": "万科A", "turnover": 200.0, "pct_chg": -2.0,
         "active_buy": 90.0, "active_sell": 110.0, "net_active": -20.0, "main_buy": 50.0, "main_sell": 70.0},
    ])


def _mapping():
    return pd.DataFrame([
        {"sector_code": "A", "sector_name": "行业A", "sector_path": "L1 > L2 > 行业A", "stock_code": "000001"},
        {"sector_code": "A", "sector_name": "行业A", "sector_path": "L1 > L2 > 行业A", "stock_code": "000002"},
    ])


def _seed(store: TsStore, date: str):
    stocks = _stocks()
    market = agg.aggregate_market(stocks)
    market.update({"up_count": 1, "down_count": 1, "flat_count": 0})
    store.upsert_mapping("sw_l3", _mapping(), _mapping()[["sector_code", "sector_name", "sector_path"]].drop_duplicates())
    store.upsert_stocks(date, stocks)
    store.upsert_market(date, market)
    sec = agg.aggregate_sector(stocks, _mapping(), None, market)
    store.upsert_sectors(date, "sw_l3", sec)


def test_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        store = TsStore(Path(d) / "h.db")
        _seed(store, "20250613")

        assert store.list_trading_days(5) == ["20250613"]

        tbl = store.get_sector_table(days=5, kind="sw_l3")
        assert tbl["kind"] == "sw_l3"
        assert len(tbl["columns"]) == 1
        sectors = tbl["columns"][0]["sectors"]
        a = [s for s in sectors if s["sector_code"] == "A"][0]
        assert a["turnover"] == 300.0
        assert a["sector_path"] == "L1 > L2 > 行业A"
        assert a["up_count"] == 1 and a["down_count"] == 1
        assert a["main_net"] == (30 + 50) - (20 + 70)  # = -10

        market = store.get_market_series(5)
        assert market["turnover_series"][0]["value"] == 300.0

        stocks_view = store.get_sector_stocks("A", days=5, kind="sw_l3")
        assert len(stocks_view["columns"][0]["stocks"]) == 2

        ind = store.get_stock_industries("000001")
        assert ind["sw_l3"]["sector_code"] == "A"
        assert ind["ci_l3"] is None  # 未灌入中信映射

        series = store.get_stock_series("000001", days=5)
        assert series["stock_name"] == "平安银行"
        assert series["industries"]["sw_l3"]["sector_name"] == "行业A"
        assert len(series["series"]) == 1


def test_etf_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        store = TsStore(Path(d) / "h.db")
        store.upsert_market("20250613", {"turnover": 1000.0})
        etf = pd.DataFrame([
            {"etf_code": "510300", "etf_name": "沪深300ETF", "exchange": "SH",
             "turnover": 50.0, "turnover_pct": 0.05, "pct_chg": 0.4, "fd_share": 12345.6},
        ])
        store.upsert_etfs("20250613", etf)
        tbl = store.get_etf_table(days=5)
        it = tbl["columns"][0]["etfs"][0]
        assert it["etf_code"] == "510300"
        assert it["fd_share"] == 12345.6
        ser = store.get_etf_series("510300", days=5)
        assert ser["series"][0]["turnover"] == 50.0


def test_sort_net():
    with tempfile.TemporaryDirectory() as d:
        store = TsStore(Path(d) / "h.db")
        _seed(store, "20250613")
        # 加一个净流入更高的行业
        store.upsert_mapping(
            "sw_l3",
            pd.concat([_mapping(), pd.DataFrame([{"sector_code": "B", "sector_name": "行业B", "sector_path": "x", "stock_code": "000001"}])], ignore_index=True),
            _mapping()[["sector_code", "sector_name", "sector_path"]],
        )
        tbl = store.get_sector_table(days=5, kind="sw_l3", sort="net_desc")
        sectors = tbl["columns"][0]["sectors"]
        nets = [s["net_active"] for s in sectors if s["net_active"] is not None]
        assert nets == sorted(nets, reverse=True)


def _run_all() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1; print(f"FAIL {fn.__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
