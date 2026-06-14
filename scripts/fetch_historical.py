#!/usr/bin/env python3
"""回填申万 2021 完整历史成份及成交额（按交易日点-in-time JOIN）。

cn_stock_industry_component 为日频表，每个交易日一条成份记录；
历史成交额汇总必须与当日成份 JOIN，不能用最新成份回算历史。

认证：bq auth --apikey <AK.SK>
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bq_common import (
    MAPPING_MIN_DATE,
    fetch_industry_range,
    fetch_mapping_range,
    fetch_market_range,
    fetch_stock_range,
    month_chunks,
)

ROOT = Path(__file__).resolve().parents[1]
HISTORY_DIR = ROOT / "data" / "history"
CST = ZoneInfo("Asia/Shanghai")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="回填申万 2021 历史成份与成交额（BigQuant DAI）"
    )
    parser.add_argument("--start-date", metavar="YYYY-MM-DD", help="起始交易日")
    parser.add_argument("--end-date", metavar="YYYY-MM-DD", help="结束交易日")
    parser.add_argument(
        "--mode",
        choices=["mapping", "turnover", "all"],
        default="all",
        help="mapping=仅成份映射; turnover=大盘+行业成交额; all=全部（默认）",
    )
    parser.add_argument(
        "--include-stocks",
        action="store_true",
        help="同时拉取个股级历史成交额（数据量大，慎用）",
    )
    parser.add_argument(
        "--skip-stock-name",
        action="store_true",
        help="映射表不 JOIN 行情取简称（更快）",
    )
    return parser.parse_args()


def infer_end_date() -> date:
    d = datetime.now(CST).date()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def resolve_range(args: argparse.Namespace) -> tuple[date, date]:
    end_date = date.fromisoformat(args.end_date) if args.end_date else infer_end_date()
    start_date = (
        date.fromisoformat(args.start_date) if args.start_date else MAPPING_MIN_DATE
    )
    if start_date < MAPPING_MIN_DATE:
        print(
            f"警告: start_date 早于成份表可用日 {MAPPING_MIN_DATE}，已自动调整",
            file=sys.stderr,
        )
        start_date = MAPPING_MIN_DATE
    if start_date > end_date:
        raise ValueError(f"start_date ({start_date}) 不能晚于 end_date ({end_date})")
    return start_date, end_date


def append_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    df.to_csv(path, mode="a", header=write_header, index=False, encoding="utf-8")


def fetch_chunked(
    label: str,
    fetcher,
    start_date: date,
    end_date: date,
    output_path: Path,
    **kwargs,
) -> int:
    total_rows = 0
    chunks = list(month_chunks(start_date, end_date))
    print(f"  {label}: {start_date} ~ {end_date}，分 {len(chunks)} 个月拉取")
    if output_path.exists():
        output_path.unlink()

    for idx, (chunk_start, chunk_end) in enumerate(chunks, start=1):
        print(f"    [{idx}/{len(chunks)}] {chunk_start} ~ {chunk_end}")
        df = fetcher(chunk_start, chunk_end, **kwargs)
        if df.empty:
            continue
        append_csv(df, output_path)
        total_rows += len(df)
    print(f"     合计 {total_rows:,} 行 -> {output_path.name}")
    return total_rows


def write_readme(
    start_date: date,
    end_date: date,
    snapshot_time: datetime,
    mode: str,
    include_stocks: bool,
    stats: dict[str, int],
) -> None:
    readme = f"""# 历史数据说明

- **date_range**: {start_date.isoformat()} ~ {end_date.isoformat()}
- **snapshot_time**: {snapshot_time.isoformat()}
- **行业体系**: 申万 2021（`industry = sw2021`）
- **成份口径**: 每个交易日使用 `cn_stock_industry_component` 当日记录（完整历史成份）
- **成交额 JOIN**: `b.date = c.date AND b.instrument = c.instrument`（点-in-time）
- **mode**: {mode}
- **include_stocks**: {include_stocks}

## 文件

| 文件 | 行数 | 说明 |
|------|------|------|
| industry_stock_mapping_history.csv | {stats.get("mapping", 0):,} | 每日申万成份映射（L1/L2/L3） |
| market_turnover_history.csv | {stats.get("market", 0):,} | 每日全 A 成交额 |
| industry_turnover_history.csv | {stats.get("industry", 0):,} | 每日一级行业成交额 |
| stock_turnover_history.csv | {stats.get("stock", 0):,} | 每日个股成交额（可选） |

## 说明

- 成份表 `cn_stock_industry_component` 自 **{MAPPING_MIN_DATE}** 起有完整日频数据
- 行业调整、上市退市会导致历史成份逐日变化，**禁止**用最新成份回算历史成交额
- 行业进出事件可参考 BigQuant `cn_stock_industry_change`（事件表，非日频）
"""
    (HISTORY_DIR / "README.md").write_text(readme, encoding="utf-8")


def main() -> int:
    args = parse_args()
    snapshot_time = datetime.now(CST)
    start_date, end_date = resolve_range(args)
    stats: dict[str, int] = {}

    print(f"回填申万历史成份: {start_date} ~ {end_date}，mode={args.mode}")

    if args.mode in ("mapping", "all"):
        stats["mapping"] = fetch_chunked(
            "历史成份映射",
            fetch_mapping_range,
            start_date,
            end_date,
            HISTORY_DIR / "industry_stock_mapping_history.csv",
            with_stock_name=not args.skip_stock_name,
        )

    if args.mode in ("turnover", "all"):
        stats["market"] = fetch_chunked(
            "大盘成交额",
            fetch_market_range,
            start_date,
            end_date,
            HISTORY_DIR / "market_turnover_history.csv",
        )
        industry_fetcher = fetch_industry_range
        stats["industry"] = fetch_chunked(
            "行业成交额",
            industry_fetcher,
            start_date,
            end_date,
            HISTORY_DIR / "industry_turnover_history.csv",
        )

    if args.include_stocks and args.mode in ("turnover", "all"):
        stats["stock"] = fetch_chunked(
            "个股成交额",
            fetch_stock_range,
            start_date,
            end_date,
            HISTORY_DIR / "stock_turnover_history.csv",
        )

    write_readme(
        start_date,
        end_date,
        snapshot_time,
        args.mode,
        args.include_stocks,
        stats,
    )

    print(f"\n历史数据已写入: {HISTORY_DIR}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        sys.exit(1)
