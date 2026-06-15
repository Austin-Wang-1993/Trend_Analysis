"""必盈 API 共享工具：行业分类树、板块成份、实时成交额、资金流向、ETF。"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pandas as pd
import requests

API_BASE = "https://api.biyingapi.com"
ALL_BASE = "https://all.biyingapi.com"
CST = ZoneInfo("Asia/Shanghai")

# hszg/list type2 含义（备用）
TYPE2_SW_L1 = 0  # A股-申万行业
TYPE2_SW_L2 = 1  # A股-申万二级

# hslt/primarylist 申万一级行业名称前缀（中证1000成份的申万一级）
HSLT_SW_L1_PREFIX = "1000SW1"


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


def ensure_stock_codes(df: pd.DataFrame, column: str = "stock_code") -> pd.DataFrame:
    """统一代码列为 6 位字符串，避免 merge 时 int/str 冲突。"""
    if column not in df.columns:
        return df
    out = df.copy()
    out[column] = out[column].map(lambda x: try_normalize_code6(x) or str(x).strip())
    return out


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


def _get(url: str, params: dict[str, Any] | None = None, retries: int = 5) -> Any:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=60)
            try:
                data = resp.json()
            except ValueError as exc:
                raise RuntimeError(f"非 JSON 响应 [{resp.status_code}]: {resp.text[:200]}") from exc

            if isinstance(data, dict) and data.get("code") not in (None, 0):
                code = data.get("code")
                message = data.get("message") or data.get("msg") or data
                raise RuntimeError(f"必盈 API 错误 [{code}]: {message}")

            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")

            return data
        except Exception as exc:
            last_error = exc
            time.sleep(0.5 * (attempt + 1))
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


def fetch_primary_list(licence: str) -> pd.DataFrame:
    """一级市场板块列表 hslt/primarylist（券商数据）。"""
    rows = _get(f"{API_BASE}/hslt/primarylist/{licence}")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("一级市场板块列表为空")
    df = pd.DataFrame(rows)
    if "mc" not in df.columns:
        raise RuntimeError("primarylist 缺少 mc 字段")
    return df.drop_duplicates("mc").reset_index(drop=True)


def filter_hslt_sectors(primary_df: pd.DataFrame, level: str = "l1") -> pd.DataFrame:
    """从 primarylist 筛出申万行业板块名称。"""
    if level == "l1":
        prefix = HSLT_SW_L1_PREFIX
        type2 = TYPE2_SW_L1
    elif level == "l2":
        raise ValueError("hslt/primarylist 暂不支持申万二级（无稳定 SW2 前缀），请使用 level=l1")
    elif level == "both":
        return filter_hslt_sectors(primary_df, "l1")
    else:
        raise ValueError(f"未知 level: {level}")

    df = primary_df[primary_df["mc"].astype(str).str.startswith(prefix)].copy()
    if df.empty:
        raise RuntimeError(f"primarylist 中未找到前缀为 {prefix} 的申万行业")
    df["code"] = df["mc"]
    df["name"] = df["mc"].str[len(prefix) :]
    df["type1"] = 0
    df["type2"] = type2
    df["level"] = 2
    df["pcode"] = "swhy"
    df["pname"] = "A股-申万行业"
    df["isleaf"] = 1
    return df.reset_index(drop=True)


def fetch_hslt_sector_stocks(licence: str, sector_name: str) -> list[dict[str, str]]:
    """板块成份股 hslt/sectors/{板块名称}/{licence}。"""
    encoded = quote(sector_name, safe="")
    data = _get(f"{API_BASE}/hslt/sectors/{encoded}/{licence}")
    if not isinstance(data, dict):
        raise RuntimeError(f"hslt/sectors 返回非对象: {sector_name}")
    if data.get("detail"):
        raise RuntimeError(f"hslt/sectors 无数据 [{sector_name}]: {data.get('detail')}")
    stocks = data.get("stocks") or []
    if not isinstance(stocks, list):
        return []
    result: list[dict[str, str]] = []
    for row in stocks:
        if not isinstance(row, dict):
            continue
        dm = row.get("dm", "")
        if not dm:
            continue
        try:
            code = normalize_code6(dm)
        except ValueError:
            continue
        result.append(
            {
                "stock_code": code,
                "stock_name": str(row.get("mc", "")).strip(),
                "exchange": str(row.get("jys", "")).strip(),
            }
        )
    return result


def build_hslt_sector_mapping(licence: str, sectors_df: pd.DataFrame) -> pd.DataFrame:
    """逐板块拉取 hslt/sectors 构建映射表。"""
    rows: list[dict[str, Any]] = []
    total = len(sectors_df)
    for idx, sector in sectors_df.iterrows():
        sector_name = str(sector["code"])
        display_name = str(sector["name"])
        print(f"     [{idx + 1}/{total}] {display_name} ({sector_name}) ...")
        constituents = fetch_hslt_sector_stocks(licence, sector_name)
        print(f"         成份: {len(constituents)}")
        for item in constituents:
            rows.append(
                {
                    "sector_code": sector_name,
                    "sector_name": display_name,
                    "sector_type2": int(sector.get("type2", TYPE2_SW_L1)),
                    "sector_level": int(sector.get("level", 2)),
                    "parent_code": sector.get("pcode", ""),
                    "parent_name": sector.get("pname", ""),
                    **item,
                }
            )
        time.sleep(0.05)
    if not rows:
        raise RuntimeError("hslt 板块成份映射为空")
    return pd.DataFrame(rows)


def fetch_hslt_sector_tree(licence: str, level: str = "l1") -> pd.DataFrame:
    """hslt/primarylist → 申万行业 sectors 表。"""
    primary_df = fetch_primary_list(licence)
    return filter_hslt_sectors(primary_df, level)


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


# --- 资金流向（日级主买/主卖）---

FUND_FLOW_BUY_FIELDS = ("zmbtdcje", "zmbddcje", "zmbzdcje", "zmbxdcje")
FUND_FLOW_SELL_FIELDS = ("zmstdcje", "zmsddcje", "zmszdcje", "zmsxdcje")
FUND_FLOW_PASSIVE_BUY_FIELDS = ("bdmbtdcje", "bdmbddcje", "bdmbzdcje", "bdmbxdcje")
FUND_FLOW_PASSIVE_SELL_FIELDS = ("bdmstdcje", "bdmsddcje", "bdmszdcje", "bdmsxdcje")
FUND_FLOW_LARGE_BUY_FIELDS = ("zmbtdcje", "zmbddcje")
FUND_FLOW_LARGE_SELL_FIELDS = ("zmstdcje", "zmsddcje")


def _sum_fields(row: dict[str, Any], fields: tuple[str, ...]) -> float:
    total = 0.0
    for key in fields:
        total += float(row.get(key, 0) or 0)
    return total


def parse_fund_flow_row(row: dict[str, Any], stock_code: str) -> dict[str, Any]:
    """将 history/transaction 单条记录解析为买卖汇总字段。"""
    trade_time = str(row.get("t", ""))
    trade_date = trade_time[:10] if trade_time else datetime.now(CST).date().isoformat()
    active_buy = _sum_fields(row, FUND_FLOW_BUY_FIELDS)
    active_sell = _sum_fields(row, FUND_FLOW_SELL_FIELDS)
    passive_buy = _sum_fields(row, FUND_FLOW_PASSIVE_BUY_FIELDS)
    passive_sell = _sum_fields(row, FUND_FLOW_PASSIVE_SELL_FIELDS)
    large_buy = _sum_fields(row, FUND_FLOW_LARGE_BUY_FIELDS)
    large_sell = _sum_fields(row, FUND_FLOW_LARGE_SELL_FIELDS)
    return {
        "stock_code": stock_code,
        "trade_date": trade_date,
        "active_buy": active_buy,
        "active_sell": active_sell,
        "net_active": active_buy - active_sell,
        "passive_buy": passive_buy,
        "passive_sell": passive_sell,
        "large_buy": large_buy,
        "large_sell": large_sell,
        "net_large": large_buy - large_sell,
        "dddx": float(row.get("dddx", 0) or 0),
        "zddy": float(row.get("zddy", 0) or 0),
        "ddcf": float(row.get("ddcf", 0) or 0),
    }


def _exchange_suffix(stock_code: str) -> str:
    code = normalize_code6(stock_code)
    return "SH" if code.startswith(("5", "6", "9")) else "SZ"


def fetch_fund_flow_single(licence: str, stock_code: str, lt: int = 1) -> dict[str, Any] | None:
    """单股日级资金流向 hsstock/history/transaction（lt=1 返回最近一条）。"""
    rows = fetch_fund_flow_history(licence, stock_code, lt=lt)
    return rows[0] if rows else None


def fetch_fund_flow_history(licence: str, stock_code: str, *, lt: int = 1) -> list[dict[str, Any]]:
    """单股近 lt 日资金流向，按 trade_date 降序（API 返回顺序）。"""
    code = normalize_code6(stock_code)
    rows = _get(
        f"{API_BASE}/hsstock/history/transaction/{code}/{licence}",
        params={"lt": lt},
    )
    if not isinstance(rows, list) or not rows:
        return []
    return [parse_fund_flow_row(row, code) for row in rows if isinstance(row, dict)]


def fetch_stock_kline_daily(
    licence: str,
    stock_code: str,
    start: str,
    end: str,
) -> list[dict[str, Any]]:
    """日 K 线成交额 hsstock/history/{code}.SZ/d/n。"""
    code = normalize_code6(stock_code)
    suffix = _exchange_suffix(code)
    st = start.replace("-", "")
    et = end.replace("-", "")
    rows = _get(
        f"{API_BASE}/hsstock/history/{code}.{suffix}/d/n/{licence}",
        params={"st": st, "et": et},
    )
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        trade_time = str(row.get("t", ""))
        trade_date = trade_time[:10] if trade_time else ""
        if not trade_date:
            continue
        out.append(
            {
                "stock_code": code,
                "trade_date": trade_date,
                "turnover": float(row.get("cje", row.get("a", 0)) or 0),
                "volume": int(float(row.get("v", 0) or 0)),
                "close": float(row.get("c", row.get("pc", 0)) or 0),
            }
        )
    return out


def fetch_fund_flow_batch(
    licence: str,
    stock_codes: list[str],
    *,
    lt: int = 1,
    sleep_sec: float = 0.21,
    progress_every: int = 100,
) -> pd.DataFrame:
    """逐股拉取资金流向（无批量接口）。"""
    codes = [c for c in {try_normalize_code6(x) for x in stock_codes} if c]
    if not codes:
        raise RuntimeError("无有效股票代码用于资金流向查询")

    records: list[dict[str, Any]] = []
    missing = 0
    total = len(codes)
    for idx, code in enumerate(codes, start=1):
        if idx == 1 or idx % progress_every == 0 or idx == total:
            print(f"     资金流 {idx}/{total}...", flush=True)
        try:
            row = fetch_fund_flow_single(licence, code, lt=lt)
            if row:
                records.append(row)
            else:
                missing += 1
        except Exception as exc:
            missing += 1
            if idx <= 3:
                print(f"         警告 [{code}]: {exc}")
        time.sleep(sleep_sec)

    if not records:
        raise RuntimeError(f"资金流向为空（请求 {total} 只，无数据 {missing} 只）")
    if missing:
        print(f"     资金流无数据: {missing}/{total} 只")
    return pd.DataFrame(records)


def aggregate_sector_fund_flow(stock_df: pd.DataFrame) -> pd.DataFrame:
    """按板块汇总买卖字段（与 aggregate_sector_turnover 同口径）。"""
    metrics = [
        "turnover",
        "active_buy",
        "active_sell",
        "net_active",
        "passive_buy",
        "passive_sell",
        "large_buy",
        "large_sell",
        "net_large",
    ]
    present = [m for m in metrics if m in stock_df.columns]
    grouped = stock_df.groupby(["sector_code", "sector_name"], dropna=False)
    out = grouped[present].sum().reset_index()
    if "stock_code" in stock_df.columns:
        out["stock_count"] = grouped["stock_code"].count().values
    out = out[out["sector_code"].astype(str).str.len() > 0]
    sort_col = "turnover" if "turnover" in out.columns else "net_active"
    return out.sort_values(sort_col, ascending=False).reset_index(drop=True)


def aggregate_market_summary(stock_df: pd.DataFrame) -> dict[str, Any]:
    """全 A 汇总（单行指标）。"""
    metrics = [
        "turnover",
        "active_buy",
        "active_sell",
        "net_active",
        "passive_buy",
        "passive_sell",
        "large_buy",
        "large_sell",
        "net_large",
    ]
    summary: dict[str, Any] = {"market_type": "a_share", "stock_count": len(stock_df)}
    if "trade_date" in stock_df.columns and len(stock_df):
        summary["trade_date"] = str(stock_df["trade_date"].iloc[0])
    for metric in metrics:
        if metric in stock_df.columns:
            summary[metric] = float(stock_df[metric].sum())
    return summary


# --- ETF ---

def fetch_etf_list(licence: str) -> pd.DataFrame:
    """ETF 列表 fd/list/etf。"""
    rows = _get(f"{API_BASE}/fd/list/etf/{licence}")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("ETF 列表为空")
    df = pd.DataFrame(rows)
    df = df.rename(columns={"dm": "etf_code_raw", "mc": "etf_name", "jys": "exchange"})
    df["etf_code"] = df["etf_code_raw"].map(normalize_code6)
    return df.drop_duplicates("etf_code").reset_index(drop=True)


def fetch_etf_turnover_batch(
    licence: str,
    etf_codes: list[str],
    *,
    sleep_sec: float = 0.05,
    progress_every: int = 50,
) -> pd.DataFrame:
    """逐只 ETF 实时成交 fd/real/time（无批量接口、无买卖拆分）。"""
    codes = [c for c in {try_normalize_code6(x) for x in etf_codes} if c]
    if not codes:
        raise RuntimeError("无有效 ETF 代码")

    records: list[dict[str, Any]] = []
    missing = 0
    total = len(codes)
    for idx, code in enumerate(codes, start=1):
        if idx == 1 or idx % progress_every == 0 or idx == total:
            print(f"     ETF 成交 {idx}/{total}...")
        try:
            row = _get(f"{API_BASE}/fd/real/time/{code}/{licence}")
            if not isinstance(row, dict) or "cje" not in row:
                missing += 1
                continue
            trade_time = str(row.get("t", ""))
            records.append(
                {
                    "etf_code": code,
                    "trade_time": trade_time,
                    "trade_date": trade_time[:10] if trade_time else datetime.now(CST).date().isoformat(),
                    "turnover": float(row.get("cje", 0) or 0),
                    "volume": int(float(row.get("v", 0) or 0)),
                    "close": float(row.get("p", 0) or 0),
                    "change_pct": float(row.get("pc", 0) or 0),
                }
            )
        except Exception as exc:
            missing += 1
            if idx <= 3:
                print(f"         警告 [ETF {code}]: {exc}")
        time.sleep(sleep_sec)

    if not records:
        raise RuntimeError(f"ETF 成交额为空（请求 {total} 只，失败 {missing} 只）")
    if missing:
        print(f"     ETF 无行情: {missing}/{total} 只")
    return pd.DataFrame(records)

