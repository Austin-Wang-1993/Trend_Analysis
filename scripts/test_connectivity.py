#!/usr/bin/env python3
"""检测东财 API 连通性（直连，不经过 akshare）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from em_client import (
    HAS_CURL_CFFI,
    fetch_a_share_spot,
    fetch_industry_constituents,
    fetch_industry_list,
    probe_eastmoney,
    probe_hosts,
)


def main() -> int:
    print(f"HTTP 客户端: {'curl_cffi (chrome TLS)' if HAS_CURL_CFFI else 'requests（建议 pip install curl_cffi）'}")

    print("\n=== 1. 各 push2 节点探测 ===")
    for host, ok, msg in probe_hosts():
        print(f"  {'✓' if ok else '✗'} {host}: {msg}")

    print("\n=== 2. 汇总探测 ===")
    ok, msg = probe_eastmoney()
    print(f"  {'✓' if ok else '✗'} {msg}")
    if not ok:
        print("\n建议: pip install curl_cffi && 交易日 17:00 后重试；或等待 30 分钟再试（可能临时限流）")
        return 1

    print("\n=== 3. 行业列表 ===")
    try:
        industries = fetch_industry_list()
        print(f"  ✓ 成功，行业数: {len(industries)}")
        print(industries.head(3).to_string(index=False))
    except Exception as exc:
        print(f"  ✗ 失败: {exc}")
        return 1

    print("\n=== 4. 行业成份股（取第一个行业） ===")
    try:
        code = industries.iloc[0]["industry_code"]
        name = industries.iloc[0]["industry_name"]
        cons = fetch_industry_constituents(code)
        print(f"  ✓ {name}({code}) 成份股: {len(cons)}")
        print(cons.head(3).to_string(index=False))
    except Exception as exc:
        print(f"  ✗ 失败: {exc}")
        return 1

    print("\n=== 5. 全 A 成交额汇总 ===")
    try:
        spot = fetch_a_share_spot()
        total = spot["turnover"].sum()
        print(f"  ✓ 个股数: {len(spot)}，成交额合计: {total:,.0f} 元")
    except Exception as exc:
        print(f"  ✗ 失败: {exc}")
        return 1

    print("\n全部通过。执行: python scripts/fetch_daily_data.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
