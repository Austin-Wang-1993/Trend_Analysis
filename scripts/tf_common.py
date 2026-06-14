"""TickFlow 共享工具：申万标的池映射、K 线时间范围、客户端初始化。"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from tickflow import TickFlow

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "data" / "cache"
MAPPING_CACHE = CACHE_DIR / "sw_mapping.json"
CST = ZoneInfo("Asia/Shanghai")

SW_UNIVERSE_PREFIX = "CN_Equity_SW"
SW_ID_RE = re.compile(r"^CN_Equity_SW(?P<level>[123])_(?P<code>\d+)$")

MAPPING_COLUMNS = [
    "trade_date",
    "stock_code",
    "stock_name",
    "industry_l1_code",
    "industry_l1_name",
    "industry_l2_code",
    "industry_l2_name",
    "industry_l3_code",
    "industry_l3_name",
    "industry_name",
]


def validate_api_key(api_key: str) -> str:
    """校验 API Key 格式，避免占位符或非 ASCII 字符导致 httpx 报错。"""
    if not api_key:
        return ""
    try:
        api_key.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError(
            "TICKFLOW_API_KEY 含非 ASCII 字符（常见原因：仍使用文档占位符「你的key」）。"
            "请到 https://tickflow.org 控制台复制真实 Key，执行："
            "export TICKFLOW_API_KEY=粘贴你的key"
        ) from exc
    placeholders = {"你的key", "your-api-key", "your-key", "your_api_key", "<your-api-key>"}
    if api_key.lower() in placeholders or "你的" in api_key:
        raise ValueError(
            "TICKFLOW_API_KEY 仍是占位符，请替换为 tickflow.org 控制台生成的真实 Key"
        )
    return api_key


def get_client() -> TickFlow:
    api_key = validate_api_key(os.environ.get("TICKFLOW_API_KEY", "").strip())
    if api_key:
        return TickFlow(api_key=api_key)
    return TickFlow.free()


def day_timestamp_range(trade_date: date) -> tuple[int, int]:
    start = datetime(trade_date.year, trade_date.month, trade_date.day, 0, 0, 0, tzinfo=CST)
    end = datetime(trade_date.year, trade_date.month, trade_date.day, 23, 59, 59, tzinfo=CST)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def parse_sw_universe(universe_id: str, universe_name: str) -> tuple[int, str, str] | None:
    match = SW_ID_RE.match(universe_id)
    if not match:
        return None
    level = int(match.group("level"))
    code = match.group("code")
    name = universe_name
    for prefix in ("SW1", "SW2", "SW3"):
        if name.startswith(prefix):
            name = name[len(prefix) :]
            break
    return level, code, name


def build_sw_mapping(tf: TickFlow, batch_size: int = 100) -> dict[str, dict[str, str]]:
    summaries = [u for u in tf.universes.list() if u["id"].startswith(SW_UNIVERSE_PREFIX)]
    stock_map: dict[str, dict[str, str]] = {}

    for i in range(0, len(summaries), batch_size):
        chunk = summaries[i : i + batch_size]
        details = tf.universes.batch([u["id"] for u in chunk])
        for summary in chunk:
            parsed = parse_sw_universe(summary["id"], summary["name"])
            if not parsed:
                continue
            level, code, name = parsed
            detail = details.get(summary["id"])
            if not detail:
                continue
            for symbol in detail.get("symbols", []):
                entry = stock_map.setdefault(symbol, {})
                if level == 1:
                    entry["industry_l1_code"] = code
                    entry["industry_l1_name"] = name
                elif level == 2:
                    entry["industry_l2_code"] = code
                    entry["industry_l2_name"] = name
                elif level == 3:
                    entry["industry_l3_code"] = code
                    entry["industry_l3_name"] = name

    for entry in stock_map.values():
        entry["industry_name"] = (
            entry.get("industry_l3_name")
            or entry.get("industry_l2_name")
            or entry.get("industry_l1_name")
            or ""
        )
    return stock_map


def load_or_build_mapping(tf: TickFlow, trade_date: date, refresh: bool = False) -> dict[str, dict[str, str]]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not refresh and MAPPING_CACHE.exists():
        cached = json.loads(MAPPING_CACHE.read_text(encoding="utf-8"))
        if cached.get("trade_date") == trade_date.isoformat() and cached.get("stocks"):
            return cached["stocks"]

    stocks = build_sw_mapping(tf)
    payload = {
        "trade_date": trade_date.isoformat(),
        "snapshot_time": datetime.now(CST).isoformat(),
        "source": "tickflow_sw_universes",
        "note": "申万标的池为当前成份快照，非逐日历史成份",
        "stock_count": len(stocks),
        "stocks": stocks,
    }
    MAPPING_CACHE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return stocks


def mapping_to_dataframe(stock_map: dict[str, dict[str, str]], trade_date: date) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for stock_code, info in stock_map.items():
        rows.append(
            {
                "trade_date": trade_date.isoformat(),
                "stock_code": stock_code,
                "stock_name": "",
                "industry_l1_code": info.get("industry_l1_code", ""),
                "industry_l1_name": info.get("industry_l1_name", ""),
                "industry_l2_code": info.get("industry_l2_code", ""),
                "industry_l2_name": info.get("industry_l2_name", ""),
                "industry_l3_code": info.get("industry_l3_code", ""),
                "industry_l3_name": info.get("industry_l3_name", ""),
                "industry_name": info.get("industry_name", ""),
            }
        )
    return pd.DataFrame(rows, columns=MAPPING_COLUMNS)


def fetch_turnover_klines(
    tf: TickFlow,
    symbols: list[str],
    trade_date: date,
    chunk_size: int = 200,
) -> pd.DataFrame:
    start_time, end_time = day_timestamp_range(trade_date)
    rows: list[dict[str, Any]] = []
    trade_date_str = trade_date.isoformat()

    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i : i + chunk_size]
        dfs = tf.klines.batch(
            chunk,
            period="1d",
            start_time=start_time,
            end_time=end_time,
            as_dataframe=True,
            show_progress=False,
        )
        for symbol, df in dfs.items():
            if df is None or df.empty:
                continue
            day_df = df[df["trade_date"].astype(str) == trade_date_str]
            if day_df.empty:
                continue
            row = day_df.iloc[-1]
            rows.append(
                {
                    "stock_code": symbol,
                    "stock_name": row.get("name", ""),
                    "turnover": float(row.get("amount", 0) or 0),
                    "volume": int(row.get("volume", 0) or 0),
                    "turnover_rate": row.get("turnover_rate"),
                    "pct_chg": row.get("change_pct"),
                }
            )

    return pd.DataFrame(rows)


def fetch_turnover_quotes(tf: TickFlow, trade_date: date) -> pd.DataFrame:
    quotes = tf.quotes.get(universes=["CN_Equity_A"], as_dataframe=True)
    if quotes.empty:
        return pd.DataFrame()

    trade_date_str = trade_date.isoformat()
    quotes = quotes[quotes["trade_date"].astype(str) == trade_date_str]
    if quotes.empty:
        quotes = tf.quotes.get(universes=["CN_Equity_A"], as_dataframe=True)

    rows = []
    for _, row in quotes.iterrows():
        name = row.get("ext.name") or row.get("name") or ""
        rows.append(
            {
                "stock_code": row["symbol"],
                "stock_name": name,
                "turnover": float(row.get("amount", 0) or 0),
                "volume": int(row.get("volume", 0) or 0),
                "turnover_rate": row.get("ext.turnover_rate"),
                "pct_chg": row.get("ext.change_pct"),
            }
        )
    return pd.DataFrame(rows)


def attach_industry(stock_df: pd.DataFrame, stock_map: dict[str, dict[str, str]]) -> pd.DataFrame:
    if stock_df.empty:
        return stock_df

    def lookup(code: str, field: str) -> str:
        return stock_map.get(code, {}).get(field, "")

    out = stock_df.copy()
    for field in (
        "industry_l1_code",
        "industry_l1_name",
        "industry_l2_code",
        "industry_l2_name",
        "industry_l3_code",
        "industry_l3_name",
        "industry_name",
    ):
        out[field] = out["stock_code"].map(lambda c, f=field: lookup(c, f))
    return out


def aggregate_industry_turnover(stock_df: pd.DataFrame, level: int) -> pd.DataFrame:
    """按申万指定层级汇总成交额。level=1/2/3，低层级字段一并保留供下钻。"""
    if level == 1:
        key_name, key_code = "industry_l1_name", "industry_l1_code"
        parent_cols: list[str] = []
    elif level == 2:
        key_name, key_code = "industry_l2_name", "industry_l2_code"
        parent_cols = ["industry_l1_code", "industry_l1_name"]
    elif level == 3:
        key_name, key_code = "industry_l3_name", "industry_l3_code"
        parent_cols = [
            "industry_l1_code",
            "industry_l1_name",
            "industry_l2_code",
            "industry_l2_name",
        ]
    else:
        raise ValueError("level must be 1, 2, or 3")

    mapped = stock_df[stock_df[key_name].astype(str).str.len() > 0].copy()
    grouped = (
        mapped.groupby(key_name, as_index=False)
        .agg(
            **{key_code: (key_code, "first")},
            **{c: (c, "first") for c in parent_cols},
            turnover=("turnover", "sum"),
            volume=("volume", "sum"),
            stock_count=("stock_code", "count"),
        )
        .sort_values("turnover", ascending=False)
    )
    return grouped


def infer_trade_date(snapshot_time: datetime) -> date:
    d = snapshot_time.date()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d
