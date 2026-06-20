"""ts_sectors 归一化纯函数离线测试（无需 token / 网络）。

运行：python3 tests/test_ts_sectors.py   或   pytest tests/test_ts_sectors.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import ts_sectors as ts  # noqa: E402


def test_normalize_sw_member() -> None:
    df = pd.DataFrame(
        [
            {"l1_code": "801080.SI", "l1_name": "电子", "l2_code": "801081.SI", "l2_name": "半导体",
             "l3_code": "850831.SI", "l3_name": "集成电路", "ts_code": "688981.SH", "name": "中芯国际"},
            {"l1_code": "801080.SI", "l1_name": "电子", "l2_code": "801081.SI", "l2_name": "半导体",
             "l3_code": "850831.SI", "l3_name": "集成电路", "ts_code": "002049.SZ", "name": "紫光国微"},
        ]
    )
    mapping, catalog = ts.normalize_sw_member(df)
    assert set(mapping.columns) == {"sector_code", "sector_name", "sector_path", "stock_code"}
    assert len(mapping) == 2
    row = mapping[mapping["stock_code"] == "688981"].iloc[0]
    assert row["sector_code"] == "850831.SI"
    assert row["sector_path"] == "电子 > 半导体 > 集成电路"
    assert len(catalog) == 1  # 同一 L3 仅一条 catalog


def test_normalize_sw_with_classify_adds_zero_member() -> None:
    df = pd.DataFrame(
        [{"l1_code": "801080.SI", "l1_name": "电子", "l2_code": "801081.SI", "l2_name": "半导体",
          "l3_code": "850831.SI", "l3_name": "集成电路", "ts_code": "688981.SH", "name": "中芯国际"}]
    )
    classify = pd.DataFrame(
        [
            {"index_code": "850831.SI", "industry_name": "集成电路"},
            {"index_code": "850999.SI", "industry_name": "冷门行业"},  # 零成份
        ]
    )
    _, catalog = ts.normalize_sw_member(df, classify)
    codes = set(catalog["sector_code"])
    assert "850831.SI" in codes
    assert "850999.SI" in codes  # 零成份行业被 catalog 补入


def test_normalize_ci_member() -> None:
    df = pd.DataFrame(
        [{"l1_code": "CI005001.CI", "l1_name": "石油石化", "l2_code": "CI005002.CI", "l2_name": "石油开采",
          "l3_code": "CI005003.CI", "l3_name": "油田服务", "ts_code": "601857.SH", "name": "中国石油"}]
    )
    mapping, catalog = ts.normalize_ci_member(df)
    assert mapping.iloc[0]["stock_code"] == "601857"
    assert mapping.iloc[0]["sector_path"] == "石油石化 > 石油开采 > 油田服务"


def test_normalize_board_members_dc() -> None:
    index_df = pd.DataFrame(
        [
            {"ts_code": "BK1031.DC", "name": "半导体"},
            {"ts_code": "BK1032.DC", "name": "银行"},
        ]
    )
    members = {
        "BK1031.DC": pd.DataFrame({"con_code": ["688981.SH", "002049.SZ"]}),
        "BK1032.DC": pd.DataFrame({"con_code": ["601398.SH"]}),
    }
    mapping, catalog = ts.normalize_board_members(index_df, members)
    assert len(catalog) == 2
    assert len(mapping) == 3
    bank = mapping[mapping["stock_code"] == "601398"].iloc[0]
    assert bank["sector_code"] == "BK1032.DC"
    assert bank["sector_name"] == "银行"
    assert bank["sector_path"] == "银行"  # 单层，path=name


def test_normalize_board_members_empty() -> None:
    mapping, catalog = ts.normalize_board_members(pd.DataFrame(), {})
    assert mapping.empty and catalog.empty


def test_board_one_stock_one_sector() -> None:
    # 同一股票出现在两个板块，归一化只保留首个（一股一行主板块）
    index_df = pd.DataFrame([{"ts_code": "BK1.DC", "name": "A"}, {"ts_code": "BK2.DC", "name": "B"}])
    members = {
        "BK1.DC": pd.DataFrame({"con_code": ["000001.SZ"]}),
        "BK2.DC": pd.DataFrame({"con_code": ["000001.SZ"]}),
    }
    mapping, _ = ts.normalize_board_members(index_df, members)
    assert len(mapping) == 1


def test_kinds_constant() -> None:
    assert ts.KINDS == ("sw_l3", "ci_l3", "dc_ind", "ths_ind")


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
