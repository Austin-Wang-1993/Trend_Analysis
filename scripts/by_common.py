"""必盈 API 共享工具：行业分类树、板块成份、实时成交额。"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests

API_BASE = "https://api.biyingapi.com"
ALL_BASE = "https://all.biyingapi.com"
CST = ZoneInfo("Asia/Shanghai")

# type2 含义（hszg/list 文档）
TYPE2_SW_L1 = 0  # A股-申万行业
TYPE2_SW_L2 = 1  # A股-申万二级


def normalize_code6(code: str) -> str:
    match = re.search(r"(\d{6})", str(code))
    if not match:
        raise ValueError(f"无法解析股票代码: {code!r}")
    return match.group(1)


def try_normalize_code6(code: str) -> str | None:
    try:
        return normalize_code6(code)
    except ValueError:
        return None


def get_licence() -> str:
    licence = os.environ.get("BIYING_LICENCE", "").strip()
    if not licence:
        raise ValueError(
            "未设置 BIYING_LICENCE。请到 https://www.biyingapi.com 注册获取证书，"
            "然后执行：export BIYING_LICENCE=你的licence"
        )
    placeholders = {"你的licence", "your-licence", "your_licence", "<your-licence>"}
    if licence.lower() in placeholders or "你的" in licence:
        raise ValueError("BIYING_LICENCE 仍是占位符，请替换为必盈个人中心的真实证书")
    return licence


def _get(url: str, params: dict[str, Any] | None = None, retries: int = 3) -> Any:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=60)
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError as exc:
                raise RuntimeError(f"非 JSON 响应 [{resp.status_code}]: {resp.text[:200]}") from exc
            if isinstance(data, dict) and data.get("code") not in (None, 0):
                raise RuntimeError(f"必盈 API 错误: {data}")
            return data
        except Exception as exc:
            last_error = exc
            time.sleep(0.3 * (attempt + 1))
    raise RuntimeError(f"请求失败 {url}: {last_error}") from last_error


def fetch_stock_list(licence: str) -> pd.DataFrame:
    """全 A 股列表 hslt/list。"""
    rows = _get(f"{API_BASE}/hslt/list/{licence}")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("股票列表为空")
    df = pd.DataFrame(rows)
    df = df.rename(columns={"dm": "stock_code", "mc": "stock_name", "jys": "exchange"})
    df["stock_code"] = df["stock_code"].map(normalize_code6)
    return df.drop_duplicates("stock_code").reset_index(drop=True)


def fetch_sector_tree(licence: str) -> pd.DataFrame:
    """指数/行业/概念树 hszg/list。"""
    rows = _get(f"{API_BASE}/hszg/list/{licence}")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("行业概念树为空")
    return pd.DataFrame(rows)


def filter_sectors(tree_df: pd.DataFrame, type2: int | None = TYPE2_SW_L1, leaves_only: bool = True) -> pd.DataFrame:
    df = tree_df.copy()
    if type2 is not None:
        df = df[df["type2"] == type2]
    if leaves_only:
        df = df[df["isleaf"] == 1]
    return df.reset_index(drop=True)


def fetch_sector_constituents(licence: str, sector_code: str) -> list[dict[str, str]]:
    """板块成份股 hszg/gg/{code}。"""
    rows = _get(f"{API_BASE}/hszg/gg/{sector_code}/{licence}")
    if not isinstance(rows, list):
        return []
    result = []
    for row in rows:
        if not row.get("jys"):
            continue
        code = normalize_code6(row.get("dm", ""))
        result.append(
            {
                "stock_code": code,
                "stock_name": str(row.get("mc", "")).strip(),
                "exchange": str(row.get("jys", "")).strip(),
            }
        )
    return result


def build_sector_mapping(licence: str, sectors_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    total = len(sectors_df)
    for idx, sector in sectors_df.iterrows():
        code = sector["code"]
        name = sector["name"]
        print(f"     [{idx + 1}/{total}] {name} ({code}) ...")
        for item in fetch_sector_constituents(licence, code):
            rows.append(
                {
                    "sector_code": code,
                    "sector_name": name,
                    "sector_type2": int(sector.get("type2", -1)),
                    "sector_level": int(sector.get("level", -1)),
                    "parent_code": sector.get("pcode", ""),
                    "parent_name": sector.get("pname", ""),
                    **item,
                }
            )
        time.sleep(0.05)
    if not rows:
        raise RuntimeError("板块成份映射为空")
    return pd.DataFrame(rows)


def fetch_turnover_all(licence: str) -> pd.DataFrame:
    """全市场实时成交（包年/白金）hsrl/ssjy/all。"""
    rows = _get(f"{ALL_BASE}/hsrl/ssjy/all/{licence}")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("全市场成交额为空（需包年/白金证书）")
    df = pd.DataFrame(rows)
    df["stock_code"] = df["dm"].map(normalize_code6)
    df["turnover"] = pd.to_numeric(df.get("cje", 0), errors="coerce").fillna(0.0)
    df["volume"] = pd.to_numeric(df.get("v", 0), errors="coerce").fillna(0).astype("int64")
    df["trade_time"] = df.get("t", "")
    if len(df) and "trade_time" in df.columns:
        trade_date = str(df["trade_time"].iloc[0])[:10]
    else:
        trade_date = datetime.now(CST).date().isoformat()
    df["trade_date"] = trade_date
    return df[["stock_code", "trade_date", "trade_time", "turnover", "volume", "p", "pc"]].rename(
        columns={"p": "close", "pc": "change_pct"}
    )


def fetch_turnover_batch(licence: str, stock_codes: list[str], batch_size: int = 20) -> pd.DataFrame:
    """多股实时成交 hsrl/ssjy_more，每批最多 20 只。"""
    codes = [c for c in {try_normalize_code6(x) for x in stock_codes} if c]
    if not codes:
        raise RuntimeError("无有效股票代码用于批量成交额查询")

    records: list[dict[str, Any]] = []
    total_batches = (len(codes) + batch_size - 1) // batch_size
    for batch_no, i in enumerate(range(0, len(codes), batch_size), start=1):
        batch = codes[i : i + batch_size]
        codes_param = ",".join(batch)
        print(f"     成交额批次 {batch_no}/{total_batches} ({len(batch)} 只)...")
        rows = _get(
            f"{API_BASE}/hsrl/ssjy_more/{licence}",
            params={"stock_codes": codes_param},
        )
        if isinstance(rows, dict):
            iterable = rows.values()
        elif isinstance(rows, list):
            iterable = rows
        else:
            iterable = []
        for row in iterable:
            if not isinstance(row, dict):
                continue
            code = try_normalize_code6(row.get("dm") or row.get("code") or "")
            if not code:
                continue
            records.append(
                {
                    "stock_code": code,
                    "trade_time": row.get("t", ""),
                    "turnover": float(row.get("cje", 0) or 0),
                    "volume": int(float(row.get("v", 0) or 0)),
                    "close": float(row.get("p", 0) or 0),
                    "change_pct": float(row.get("pc", 0) or 0),
                }
            )
        time.sleep(0.05)
    if not records:
        raise RuntimeError("批量成交额为空")
    df = pd.DataFrame(records).drop_duplicates("stock_code", keep="last")
    if len(df) and df["trade_time"].astype(str).str.len().gt(0).any():
        df["trade_date"] = df["trade_time"].astype(str).str[:10]
    else:
        df["trade_date"] = datetime.now(CST).date().isoformat()
    return df


def fetch_turnover(licence: str, stock_codes: list[str], prefer_all: bool = True) -> pd.DataFrame:
    if prefer_all:
        try:
            return fetch_turnover_all(licence)
        except Exception as exc:
            print(f"     全市场接口不可用，改用批量接口: {exc}")
    return fetch_turnover_batch(licence, stock_codes)


def pick_primary_sector(mapping_df: pd.DataFrame, type2: int = TYPE2_SW_L1) -> pd.DataFrame:
    """每只股票取指定层级申万行业作为主编行业。"""
    primary = mapping_df[mapping_df["sector_type2"] == type2].copy()
    if primary.empty:
        primary = mapping_df.copy()
    primary = primary.sort_values(["stock_code", "sector_code"])
    return primary.drop_duplicates("stock_code", keep="first").reset_index(drop=True)


def infer_snapshot_time() -> datetime:
    return datetime.now(CST)
