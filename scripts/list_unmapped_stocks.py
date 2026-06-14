#!/usr/bin/env python3
"""从 stock_turnover_latest.csv 列出未归入行业的股票。"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STOCK_CSV = ROOT / "data" / "stock_turnover_latest.csv"
FALLBACK_STOCK_CSV = ROOT / "data" / "stock_turnover_daily.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="查看未归类行业的股票")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_STOCK_CSV,
        help="stock_turnover_daily.csv 路径",
    )
    parser.add_argument("--top", type=int, default=30, help="终端展示前 N 只（按成交额）")
    parser.add_argument("--export", type=Path, help="另存 CSV 路径（默认不写）")
    return parser.parse_args()


def is_unmapped(df: pd.DataFrame) -> pd.Series:
    name = df["industry_l1_name"].fillna("").astype(str).str.strip()
    code = df.get("industry_l1_code", pd.Series([""] * len(df))).fillna("").astype(str).str.strip()
    return (name == "") & (code == "")


def main() -> int:
    args = parse_args()
    if not args.input.exists():
        fallback = FALLBACK_STOCK_CSV if args.input == DEFAULT_STOCK_CSV else None
        if fallback and fallback.exists():
            args.input = fallback
        else:
            print(
                f"错误: 找不到 {args.input}，请先运行 fetch_bq_daily.py",
                flush=True,
            )
            return 1

    stock_df = pd.read_csv(args.input)
    unmapped = stock_df[is_unmapped(stock_df)].copy()
    unmapped = unmapped.sort_values("turnover", ascending=False)

    total_turnover = stock_df["turnover"].sum()
    unmapped_turnover = unmapped["turnover"].sum()
    ratio = unmapped_turnover / total_turnover if total_turnover else 0.0

    print(f"有行情股票:     {len(stock_df)}")
    print(f"未归类股票:     {len(unmapped)}")
    print(f"未归类成交额:   {unmapped_turnover:,.0f} 元 ({ratio:.2%} 占大盘)")

    if unmapped.empty:
        print("全部股票均有行业归属。")
        return 0

    cols = [c for c in ["trade_date", "stock_code", "stock_name", "turnover", "volume"] if c in unmapped.columns]
    print(f"\n成交额 Top {args.top} 未归类股票:")
    print(unmapped[cols].head(args.top).to_string(index=False))

    if args.export:
        unmapped[cols].to_csv(args.export, index=False, encoding="utf-8")
        print(f"\n已导出: {args.export}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
