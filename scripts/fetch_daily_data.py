#!/usr/bin/env python3
"""拉取当日行业成交额数据并输出 CSV。建议在交易日 17:00（CST）后于腾讯云国内节点执行。"""

from __future__ import annotations

import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import akshare as ak
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_fixed

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CST = ZoneInfo("Asia/Shanghai")

REQUEST_INTERVAL_SEC = 0.8
MAX_RETRIES = 3
RETRY_WAIT_SEC = 3


def call_with_retry(func, *args, **kwargs):
    @retry(stop=stop_after_attempt(MAX_RETRIES), wait=wait_fixed(RETRY_WAIT_SEC), reraise=True)
    def _inner():
        return func(*args, **kwargs)

    return _inner()


def normalize_code(value) -> str:
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text.zfill(6)


def infer_trade_date(snapshot_time: datetime) -> date:
    """采集时刻最近交易日：周末回退到周五。"""
    d = snapshot_time.date()
    weekday = d.weekday()
    if weekday == 5:
        return d - timedelta(days=1)
    if weekday == 6:
        return d - timedelta(days=2)
    return d


def fetch_industries() -> pd.DataFrame:
    df = call_with_retry(ak.stock_board_industry_name_em)()
    return df.rename(columns={"板块代码": "industry_code", "板块名称": "industry_name"})[
        ["industry_code", "industry_name"]
    ]


def fetch_market_turnover(trade_date: date, snapshot_time: datetime) -> pd.DataFrame:
    df = call_with_retry(ak.stock_zh_a_spot_em)()
    total = pd.to_numeric(df["成交额"], errors="coerce").sum()
    return pd.DataFrame(
        [
            {
                "trade_date": trade_date.isoformat(),
                "snapshot_time": snapshot_time.isoformat(),
                "total_turnover": total,
                "stock_count": len(df),
            }
        ]
    )


def main() -> int:
    snapshot_time = datetime.now(CST)
    trade_date = infer_trade_date(snapshot_time)

    if snapshot_time.hour < 17:
        print(
            f"警告: 当前 {snapshot_time.strftime('%H:%M')} CST，建议交易日 17:00 后采集收盘数据。",
            file=sys.stderr,
        )

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("拉取行业列表...")
    industries = fetch_industries()
    print(f"  行业数: {len(industries)}")

    mapping_rows: list[dict] = []
    stock_rows: list[dict] = []
    failed: list[str] = []

    for idx, row in industries.iterrows():
        code = str(row["industry_code"])
        name = str(row["industry_name"])
        print(f"  [{idx + 1}/{len(industries)}] {name} ({code})")
        try:
            cons = call_with_retry(ak.stock_board_industry_cons_em, symbol=code)()
            for _, s in cons.iterrows():
                stock_code = normalize_code(s["代码"])
                stock_name = str(s["名称"])
                turnover = pd.to_numeric(s.get("成交额"), errors="coerce")
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

    industry_df = (
        stock_df.groupby(["industry_code", "industry_name"], as_index=False)
        .agg(turnover=("turnover", "sum"), stock_count=("stock_code", "count"))
    )
    industry_df.insert(0, "trade_date", trade_date.isoformat())
    industry_df.insert(1, "snapshot_time", snapshot_time.isoformat())

    print("拉取全 A 成交额...")
    market_df = fetch_market_turnover(trade_date, snapshot_time)

    mapping_df.to_csv(DATA_DIR / "industry_stock_mapping.csv", index=False, encoding="utf-8")
    stock_df.to_csv(DATA_DIR / "stock_turnover_daily.csv", index=False, encoding="utf-8")
    industry_df.to_csv(DATA_DIR / "industry_turnover_daily.csv", index=False, encoding="utf-8")
    market_df.to_csv(DATA_DIR / "market_turnover_daily.csv", index=False, encoding="utf-8")

    readme = f"""# 数据说明

- **trade_date**: {trade_date.isoformat()}
- **snapshot_time**: {snapshot_time.isoformat()}
- **采集环境**: 请在腾讯云国内节点、交易日 17:00 后执行

## 文件

| 文件 | 说明 |
|------|------|
| industry_stock_mapping.csv | 行业-个股映射 |
| market_turnover_daily.csv | 全 A 成交额（stock_zh_a_spot_em 求和） |
| industry_turnover_daily.csv | 行业成交额（成份股成交额求和） |
| stock_turnover_daily.csv | 行业内个股成交额 |

## 备注

- 未使用 `stock_board_industry_spot_em`，行业成交额由成份股汇总。
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
    print(f"行业成交额合计:  {industry_sum:,.0f} 元（成份股口径，不与大盘直接对比）")
    if failed:
        print(f"失败行业 ({len(failed)}):")
        for item in failed:
            print(f"  - {item}")
    print(f"\n数据已写入: {DATA_DIR}")
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
