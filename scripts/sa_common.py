"""StockAPI 共享工具：东财行业板块列表、成份映射、最近交易日成交额。"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests

BASE_URL = "https://www.stockapi.com.cn"
CST = ZoneInfo("Asia/Shanghai")
CODE6_RE = re.compile(r"^(\d{6})")


def get_token() -> str:
    token = os.environ.get("STOCKAPI_TOKEN", "").strip()
    if not token:
        raise ValueError(
            "未设置 STOCKAPI_TOKEN。请到 https://www.stockapi.com.cn 注册并在个人中心获取 Token，"
            "然后执行：export STOCKAPI_TOKEN=你的token"
        )
    placeholders = {"你的token", "your-token", "your_token", "<your-token>"}
    if token.lower() in placeholders or "你的" in token:
        raise ValueError("STOCKAPI_TOKEN 仍是占位符，请替换为官网个人中心的真实 Token")
    return token


def normalize_code6(code: str) -> str:
    text = str(code).strip().upper()
    match = CODE6_RE.match(text)
    if match:
        return match.group(1)
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 6:
        return digits[:6]
    raise ValueError(f"无法解析股票代码: {code}")


def to_exchange_code(code: str, jys: str | None = None) -> str:
    code6 = normalize_code6(code)
    if jys:
        suffix = jys.strip().upper()
        if suffix in {"SH", "SZ", "BJ"}:
            return f"{code6}.{suffix}"
    if code6.startswith(("6", "5", "9")):
        return f"{code6}.SH"
    if code6.startswith(("4", "8")):
        return f"{code6}.BJ"
    return f"{code6}.SZ"


def _api_get(path: str, token: str, params: dict[str, Any] | None = None) -> Any:
    query = {"token": token, **(params or {})}
    url = f"{BASE_URL}{path}"
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            resp = requests.get(url, params=query, timeout=60)
            resp.raise_for_status()
            payload = resp.json()
            code = payload.get("code")
            if code != 20000:
                raise RuntimeError(f"StockAPI 错误 [{code}]: {payload.get('msg')}")
            return payload.get("data")
        except Exception as exc:
            last_error = exc
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"请求失败 {path}: {last_error}") from last_error


def fetch_sectors(token: str) -> pd.DataFrame:
    """东财行业板块列表（menu/34 /v1/base/bk）。"""
    rows = _api_get("/v1/base/bk", token) or []
    if not rows:
        raise RuntimeError("板块列表为空，请确认 Token 权限或稍后在交易日 15:30 后重试")
    df = pd.DataFrame(rows)
    df = df.rename(columns={"plateCode": "sector_code", "name": "sector_name"})
    df = df[["sector_code", "sector_name"]].drop_duplicates().sort_values("sector_code")
    return df.reset_index(drop=True)


def fetch_sector_constituents(token: str, sector_code: str, page_size: int = 200) -> list[dict[str, str]]:
    """单个行业板块成份股（menu/33 /v1/base/bkList）。"""
    page_no = 1
    results: list[dict[str, str]] = []
    while True:
        data = _api_get(
            "/v1/base/bkList",
            token,
            {"bkCode": sector_code, "pageNo": str(page_no), "pageSize": str(page_size)},
        )
        if not data:
            break
        if not isinstance(data, list):
            raise RuntimeError(f"bkList 返回非列表: {sector_code}")
        for row in data:
            code6 = normalize_code6(row.get("f12", ""))
            results.append(
                {
                    "stock_code": to_exchange_code(code6),
                    "stock_name": str(row.get("f14", "")).strip(),
                }
            )
        if len(data) < page_size:
            break
        page_no += 1
        time.sleep(0.05)
    return results


def fetch_all_stocks(token: str) -> pd.DataFrame:
    """全 A 股列表（menu/10 /v1/base/all）。"""
    rows = _api_get("/v1/base/all", token) or []
    if not rows:
        raise RuntimeError("全 A 股列表为空，请确认 Token 权限")
    records = []
    for row in rows:
        code6 = normalize_code6(row.get("api_code", ""))
        records.append(
            {
                "stock_code": to_exchange_code(code6, row.get("jys")),
                "stock_name": str(row.get("name", "")).strip(),
            }
        )
    return pd.DataFrame(records).drop_duplicates("stock_code").reset_index(drop=True)


def fetch_day_all(token: str) -> pd.DataFrame:
    """最近一个交易日全市场日 K 成交额（menu/12 /v1/base/dayAll）。"""
    rows = _api_get("/v1/base/dayAll", token) or []
    if not rows:
        raise RuntimeError("dayAll 无数据，请在交易日 15:30 后重试")
    records = []
    for row in rows:
        raw_code = str(row.get("code", "")).strip()
        code6 = normalize_code6(raw_code.split(".")[0])
        records.append(
            {
                "stock_code": to_exchange_code(code6),
                "trade_date": str(row.get("time", "")).strip(),
                "turnover": float(row.get("amount", 0) or 0),
                "volume": float(row.get("volume", 0) or 0),
                "close": float(row.get("close", 0) or 0),
            }
        )
    df = pd.DataFrame(records)
    if df.empty:
        return df
    trade_date = df["trade_date"].mode().iloc[0]
    df = df[df["trade_date"] == trade_date].copy()
    return df.reset_index(drop=True)


def build_sector_stock_mapping(token: str, sectors_df: pd.DataFrame) -> pd.DataFrame:
    """遍历全部行业板块，构建板块-个股映射。"""
    rows: list[dict[str, str]] = []
    total = len(sectors_df)
    for idx, sector in sectors_df.iterrows():
        sector_code = sector["sector_code"]
        sector_name = sector["sector_name"]
        print(f"     [{idx + 1}/{total}] {sector_name} ({sector_code}) ...")
        for item in fetch_sector_constituents(token, sector_code):
            rows.append(
                {
                    "sector_code": sector_code,
                    "sector_name": sector_name,
                    "stock_code": item["stock_code"],
                    "stock_name": item["stock_name"],
                }
            )
        time.sleep(0.05)
    if not rows:
        raise RuntimeError("板块成份映射为空")
    return pd.DataFrame(rows)


def pick_primary_sector(mapping_df: pd.DataFrame) -> pd.DataFrame:
    """为每只股票选取一个主行业（成份股数最多的板块优先，否则按板块代码排序）。"""
    sector_sizes = mapping_df.groupby("sector_code").size().rename("sector_size")
    enriched = mapping_df.merge(sector_sizes, on="sector_code", how="left")
    enriched = enriched.sort_values(
        ["stock_code", "sector_size", "sector_code"],
        ascending=[True, False, True],
    )
    return enriched.drop_duplicates("stock_code", keep="first").reset_index(drop=True)


def infer_snapshot_time() -> datetime:
    return datetime.now(CST)
