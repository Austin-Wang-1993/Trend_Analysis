"""ts_common 纯函数离线测试（无需 TUSHARE_TOKEN / 网络）。

运行：python3 tests/test_ts_common.py   或   pytest tests/test_ts_common.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import ts_common as tc  # noqa: E402


def test_unit_constants() -> None:
    assert tc.QIAN_TO_YUAN == 1000.0
    assert tc.WAN_TO_YUAN == 10000.0


def test_ts_code_to_code6() -> None:
    assert tc.ts_code_to_code6("000001.SZ") == "000001"
    assert tc.ts_code_to_code6("600519.SH") == "600519"
    assert tc.ts_code_to_code6("430047.BJ") == "430047"


def test_code6_to_ts_code() -> None:
    assert tc.code6_to_ts_code("000001") == "000001.SZ"
    assert tc.code6_to_ts_code("600519") == "600519.SH"
    assert tc.code6_to_ts_code("688981") == "688981.SH"
    assert tc.code6_to_ts_code("000001", "SZSE") == "000001.SZ"
    assert tc.code6_to_ts_code("600519.SH") == "600519.SH"  # 已带后缀原样返回


def test_moneyflow_aggregation() -> None:
    # 单位万元；active_buy = (1+2+3+4)*1e4=1e5；main_buy=(3+4)*1e4=7e4
    df = pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ", "trade_date": "20250613",
                "buy_sm_amount": 1, "buy_md_amount": 2, "buy_lg_amount": 3, "buy_elg_amount": 4,
                "sell_sm_amount": 5, "sell_md_amount": 6, "sell_lg_amount": 7, "sell_elg_amount": 8,
                "net_mf_amount": -2.5,
            }
        ]
    )
    out = tc.moneyflow_to_stock_flow(df)
    row = out.iloc[0]
    assert row["stock_code"] == "000001"
    assert row["active_buy"] == 10 * tc.WAN_TO_YUAN
    assert row["active_sell"] == 26 * tc.WAN_TO_YUAN
    # 净流入取 net_mf_amount（不是 buy-sell，那个恒为 0）
    assert row["net_active"] == -2.5 * tc.WAN_TO_YUAN
    assert row["main_buy"] == 7 * tc.WAN_TO_YUAN
    assert row["main_sell"] == 15 * tc.WAN_TO_YUAN
    assert row["main_net"] == (7 - 15) * tc.WAN_TO_YUAN
    # 8 档原子字段：特大单买 = buy_elg=4 万 → 4e4
    assert row["zmbtdcje"] == 4 * tc.WAN_TO_YUAN
    assert row["zmbxdcje"] == 1 * tc.WAN_TO_YUAN
    assert row["zmstdcje"] == 8 * tc.WAN_TO_YUAN


def test_moneyflow_empty() -> None:
    out = tc.moneyflow_to_stock_flow(pd.DataFrame())
    assert out.empty
    assert "active_buy" in out.columns


def test_daily_to_turnover() -> None:
    df = pd.DataFrame(
        [
            {"ts_code": "600519.SH", "trade_date": "20250613", "amount": 1234.5, "pct_chg": 1.23},
            {"ts_code": "000001.SZ", "trade_date": "20250613", "amount": None, "pct_chg": -0.5},
        ]
    )
    out = tc.daily_to_turnover(df)
    assert out.iloc[0]["turnover"] == 1234.5 * tc.QIAN_TO_YUAN
    assert out.iloc[0]["stock_code"] == "600519"
    assert pd.isna(out.iloc[1]["turnover"])  # amount 缺失 → NaN


def test_fund_daily_to_turnover() -> None:
    df = pd.DataFrame([{"ts_code": "510300.SH", "trade_date": "20250613", "amount": 100.0, "pct_chg": 0.4}])
    out = tc.fund_daily_to_turnover(df)
    assert out.iloc[0]["etf_code"] == "510300"
    assert out.iloc[0]["exchange"] == "SH"
    assert out.iloc[0]["turnover"] == 100.0 * tc.QIAN_TO_YUAN


def test_daily_basic_to_metrics() -> None:
    df = pd.DataFrame([
        {"ts_code": "600519.SH", "trade_date": "20250613", "close": 1500.0,
         "total_mv": 18000000.0, "pe": 22.5, "pe_ttm": 21.0, "pb": 8.1, "dv_ratio": 3.2, "dv_ttm": 3.5},
        {"ts_code": "000001.SZ", "trade_date": "20250613", "close": 11.2,
         "total_mv": 21700000.0, "pe": None, "pe_ttm": 4.8, "pb": 0.6, "dv_ratio": 5.1, "dv_ttm": 5.1},
    ])
    out = tc.daily_basic_to_metrics(df)
    r = out[out["stock_code"] == "600519"].iloc[0]
    assert r["close"] == 1500.0
    assert r["total_mv"] == 18000000.0 * tc.WAN_TO_YUAN  # 万元 → 元
    assert r["pe_ttm"] == 21.0
    assert pd.isna(out[out["stock_code"] == "000001"].iloc[0]["pe"])  # 亏损 PE 为空


def test_latest_holder_numbers() -> None:
    df = pd.DataFrame([
        {"ts_code": "300199.SZ", "ann_date": "20180808", "end_date": "20180630", "holder_num": 25785},
        {"ts_code": "300199.SZ", "ann_date": "20181025", "end_date": "20180930", "holder_num": 25135},
        {"ts_code": "600519.SH", "ann_date": "20180426", "end_date": "20180331", "holder_num": 99999},
    ])
    out = tc.latest_holder_numbers(df)
    a = out[out["stock_code"] == "300199"].iloc[0]
    assert a["holder_num"] == 25135           # 取 end_date 最大（20180930）
    assert a["holder_end_date"] == "20180930"
    assert len(out) == 2


def test_recent_dividends() -> None:
    df = pd.DataFrame([
        {"ts_code": "600519.SH", "div_proc": "实施", "end_date": "20231231", "ex_date": "20240612", "cash_div_tax": 0.32},
        {"ts_code": "600519.SH", "div_proc": "实施", "end_date": "20231231", "ex_date": "20240612", "cash_div_tax": 0.32},  # 重复
        {"ts_code": "600519.SH", "div_proc": "实施", "end_date": "20221231", "ex_date": "20230621", "cash_div_tax": 0.06},
        {"ts_code": "600519.SH", "div_proc": "实施", "end_date": "20141231", "ex_date": "20150413", "cash_div_tax": 0.0},   # 纯送转(0现金)
        {"ts_code": "600519.SH", "div_proc": "预案", "end_date": "20251231", "ex_date": None, "cash_div_tax": 0.5},          # 未实施
        {"ts_code": "000001.SZ", "div_proc": "实施", "end_date": "20121231", "ex_date": "20130506", "cash_div_tax": 0.2},   # 太老（>3年）
    ])
    out = tc.recent_dividends(df, years=3, ref_year=2024)
    codes = list(out["stock_code"])
    assert codes == ["600519", "600519"]          # 000001 太老被剔除；茅台两条
    assert out.iloc[0]["ex_date"] == "20240612"   # 倒序
    assert out.iloc[0]["cash_div_tax"] == 0.32
    assert out.iloc[1]["end_date"] == "20221231"
    assert (out["cash_div_tax"] > 0).all()        # 0 现金(送转)被排除
    assert len(out) == 2                           # 去重生效


def test_count_up_down() -> None:
    s = pd.Series([1.0, -2.0, 0.0, 3.0, None])
    up, down, flat = tc.count_up_down(s)
    assert up == 2
    assert down == 1
    assert flat == 2  # 0.0 与 None 均计平盘


def test_load_dotenv(tmp_path: Path = None) -> None:  # type: ignore[assignment]
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        env = Path(d) / ".env"
        env.write_text('export FOO_TS_TEST="bar baz"  # comment\nBAZ_TS_TEST=qux\n', encoding="utf-8")
        os.environ.pop("FOO_TS_TEST", None)
        os.environ.pop("BAZ_TS_TEST", None)
        tc.load_dotenv(env)
        assert os.environ["FOO_TS_TEST"] == "bar baz"
        assert os.environ["BAZ_TS_TEST"] == "qux"


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
