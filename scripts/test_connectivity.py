#!/usr/bin/env python3
"""检测腾讯云到东财 / akshare 接口的连通性。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from em_client import patch_akshare_requests, probe_eastmoney


def main() -> int:
    print("=== 1. 直连东财 push2（带浏览器请求头）===")
    ok, msg = probe_eastmoney()
    print(f"  {'✓' if ok else '✗'} {msg}")

    print("\n=== 2. akshare stock_board_industry_name_em ===")
    patch_akshare_requests()
    try:
        import akshare as ak

        df = ak.stock_board_industry_name_em()
        print(f"  ✓ 成功，行业数: {len(df)}")
        print(df[["板块代码", "板块名称"]].head(3).to_string(index=False))
    except Exception as exc:
        print(f"  ✗ 失败: {exc}")
        return 1

    print("\n=== 3. akshare stock_zh_a_spot_em（仅测前 1 页逻辑）===")
    try:
        import akshare as ak

        df = ak.stock_zh_a_spot_em()
        print(f"  ✓ 成功，个股数: {len(df)}，成交额合计: {df['成交额'].sum():,.0f}")
    except Exception as exc:
        print(f"  ✗ 失败: {exc}")
        return 1

    print("\n全部检测通过，可执行: python scripts/fetch_daily_data.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
