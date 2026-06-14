#!/usr/bin/env python3
"""拉取当日行业成交额数据并输出 CSV。建议在交易日 17:00（CST）后于腾讯云国内节点执行。"""

from __future__ import annotations

import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from em_client import (
    fetch_a_share_spot,
    fetch_industry_constituents,
    fetch_industry_list,
    probe_eastmoney,
)
from tenacity import retry, stop_after_attempt, wait_exponential

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CST = ZoneInfo("Asia/Shanghai")

REQUEST_INTERVAL_SEC = 1.0
MAX_RETRIES = 6


def call_with_retry(func, *args, **kwargs):
    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    def _inner():
        return func(*args, **kwargs)

    return _inner()


def normalize_code(value) -> str:
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text.zfill(6)


def infer_trade_date(snapshot_time: datetime) -> date:
    d = snapshot_time.date()
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d - timedelta(days=2)
    return d


def main() -> int:
    snapshot_time = datetime.now(CST)
    trade_date = infer_trade_date(snapshot_time)

    if snapshot_time.hour < 17:
        print(
            f"警告: 当前 {snapshot_time.strftime('%H:%M')} CST，建议交易日 17:00 后采集收盘数据。",
            file=sys.stderr,
        )

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("探测东财接口...")
    ok, msg = probe_eastmoney()
    if not ok:
        print(f"东财接口不可达: {msg}", file=sys.stderr)
        return 1
    print(f"  {msg}")

    print("拉取行业列表...")
    industries = call_with_retry(fetch_industry_list)()
    print(f"  行业数: {len(industries)}")

    mapping_rows: list[dict] = []
    stock_rows: list[dict] = []
    failed: list[str] = []

    for idx, row in industries.iterrows():
        code = str(row["industry_code"])
        name = str(row["industry_name"])
        print(f"  [{idx + 1}/{len(industries)}] {name} ({code})")
        try:
            cons = call_with_retry(fetch_industry_constituents, code)()
            for _, s in cons.iterrows():
                stock_code = normalize_code(s["stock_code"])
                stock_name = str(s["stock_name"])
                turnover = pd.to_numeric(s.get("turnover"), errors="coerce")
                mapping_rows.append(
                    {
                        "industry_code": code,
                        "industry_name": name,
                        "stock_code": stock_code,
                        "stock_name": stock_name,
                    }
                )
                stock_rows.append(
                    {
                        "trade_date": trade_date.isoformat(),
                        "snapshot_time": snapshot_time.isoformat(),
                        "industry_code": code,
                        "industry_name": name,
                        "stock_code": stock_code,
                        "stock_name": stock_name,
                        "turnover": turnover,
                    }
                )
        except Exception as exc:
            failed.append(f"{code} {name}: {exc}")
            print(f"    失败: {exc}", file=sys.stderr)
        time.sleep(REQUEST_INTERVAL_SEC)

    if not stock_rows:
        print("错误: 未获取到任何成份股数据", file=sys.stderr)
        return 1

    mapping_df = pd.DataFrame(mapping_rows)
    stock_df = pd.DataFrame(stock_rows)

    industry_df = stock_df.groupby(["industry_code", "industry_name"], as_index=False).agg(
        turnover=("turnover", "sum"), stock_count=("stock_code", "count")
    )
    industry_df.insert(0, "trade_date", trade_date.isoformat())
    industry_df.insert(1, "snapshot_time", snapshot_time.isoformat())

    print("拉取全 A 成交额...")
    spot_df = call_with_retry(fetch_a_share_spot)()
    market_df = pd.DataFrame(
        [
            {
                "trade_date": trade_date.isoformat(),
                "snapshot_time": snapshot_time.isoformat(),
                "total_turnover": pd.to_numeric(spot_df["turnover"], errors="coerce").sum(),
                "stock_count": len(spot_df),
            }
        ]
    )

    mapping_df.to_csv(DATA_DIR / "industry_stock_mapping.csv", index=False, encoding="utf-8")
    stock_df.to_csv(DATA_DIR / "stock_turnover_daily.csv", index=False, encoding="utf-8")
    industry_df.to_csv(DATA_DIR / "industry_turnover_daily.csv", index=False, encoding="utf-8")
    market_df.to_csv(DATA_DIR / "market_turnover_daily.csv", index=False, encoding="utf-8")

    readme = f"""# 数据说明

- **trade_date**: {trade_date.isoformat()}
- **snapshot_time**: {snapshot_time.isoformat()}
- **数据源**: 东财 push2 API 直连（等价于 akshare 对应接口）

## 文件

| 文件 | 说明 |
|------|------|
| industry_stock_mapping.csv | 行业-个股映射 |
| market_turnover_daily.csv | 全 A 成交额 |
| industry_turnover_daily.csv | 行业成交额（成份股求和） |
| stock_turnover_daily.csv | 行业内个股成交额 |
"""
    (DATA_DIR / "README.md").write_text(readme, encoding="utf-8")

    market_total = market_df["total_turnover"].iloc[0]
    industry_sum = industry_df["turnover"].sum()
    print("\n========== 校验报告 ==========")
    print(f"trade_date:      {trade_date}")
    print(f"snapshot_time:   {snapshot_time.isoformat()}")
    print(f"映射行数:        {len(mapping_df)}")
    print(f"个股成交额行数:  {len(stock_df)}")
    print(f"行业数:          {len(industry_df)}")
    print(f"大盘成交额:      {market_total:,.0f} 元")
    print(f"行业成交额合计:  {industry_sum:,.0f} 元（成份股口径）")
    if failed:
        print(f"失败行业 ({len(failed)}):")
        for item in failed:
            print(f"  - {item}")
    print(f"\n数据已写入: {DATA_DIR}")
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
