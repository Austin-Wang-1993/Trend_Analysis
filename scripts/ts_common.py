"""Tushare Pro 共享工具（v4.0 主数据源）。"""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

CST = ZoneInfo("Asia/Shanghai")

ROOT = Path(__file__).resolve().parents[1]

_MONEYFLOW_BUY = ("buy_sm_amount", "buy_md_amount", "buy_lg_amount", "buy_elg_amount")
_MONEYFLOW_SELL = ("sell_sm_amount", "sell_md_amount", "sell_lg_amount", "sell_elg_amount")
_MAIN_BUY = ("buy_lg_amount", "buy_elg_amount")
_MAIN_SELL = ("sell_lg_amount", "sell_elg_amount")


def load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


def get_token() -> str:
    load_dotenv()
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        raise ValueError("请设置环境变量 TUSHARE_TOKEN（见 .env.example）")
    return token


def get_pro():
    import tushare as ts

    return ts.pro_api(get_token())


def infer_snapshot_time() -> datetime:
    return datetime.now(CST)


def yyyymmdd(trade_date: str) -> str:
    return trade_date.replace("-", "")


def normalize_ts_code(code: str) -> str:
    c = str(code).strip().upper()
    if not c:
        return ""
    if "." in c:
        return c
    digits = "".join(ch for ch in c if ch.isdigit())
    if len(digits) != 6:
        return c
    if digits.startswith(("5", "6", "9")):
        return f"{digits}.SH"
    if digits.startswith(("4", "8")):
        return f"{digits}.BJ"
    return f"{digits}.SZ"


def code6(ts_code: str) -> str:
    return str(ts_code).split(".")[0].zfill(6)


def _call(pro, api: str, *, sleep: float = 0.12, **kwargs) -> pd.DataFrame:
    fn = getattr(pro, api)
    df = fn(**kwargs)
    if df is None or not isinstance(df, pd.DataFrame):
        return pd.DataFrame()
    time.sleep(sleep)
    return df


def fetch_stock_basic(pro=None) -> pd.DataFrame:
    pro = pro or get_pro()
    df = _call(pro, "stock_basic", exchange="", list_status="L", fields="ts_code,name")
    if df.empty:
        return df
    df["stock_code"] = df["ts_code"].map(normalize_ts_code)
    return df


def fetch_daily(trade_date: str, pro=None) -> pd.DataFrame:
    pro = pro or get_pro()
    td = yyyymmdd(trade_date)
    df = _call(pro, "daily", trade_date=td, fields="ts_code,trade_date,amount,pct_chg")
    if df.empty:
        return df
    df["stock_code"] = df["ts_code"].map(normalize_ts_code)
    df["turnover"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0) * 1000.0
    df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")
    df["trade_date"] = trade_date
    return df


def fetch_moneyflow(trade_date: str, pro=None) -> pd.DataFrame:
    pro = pro or get_pro()
    td = yyyymmdd(trade_date)
    df = _call(pro, "moneyflow", trade_date=td)
    if df.empty:
        return df
    df["stock_code"] = df["ts_code"].map(normalize_ts_code)
    for col in _MONEYFLOW_BUY + _MONEYFLOW_SELL:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    df["active_buy"] = df[list(_MONEYFLOW_BUY)].sum(axis=1) * 10000.0
    df["active_sell"] = df[list(_MONEYFLOW_SELL)].sum(axis=1) * 10000.0
    df["main_buy"] = df[list(_MAIN_BUY)].sum(axis=1) * 10000.0
    df["main_sell"] = df[list(_MAIN_SELL)].sum(axis=1) * 10000.0
    df["net_active"] = df["active_buy"] - df["active_sell"]
    for i, (bp, sp) in enumerate(
        zip(
            ("zmbtdcje", "zmbddcje", "zmbzdcje", "zmbxdcje"),
            ("zmstdcje", "zmsddcje", "zmszdcje", "zmsxdcje"),
        )
    ):
        bcol = _MONEYFLOW_BUY[i]
        scol = _MONEYFLOW_SELL[i]
        df[bp] = df[bcol] * 10000.0
        df[sp] = df[scol] * 10000.0
    df["trade_date"] = trade_date
    return df


def merge_stock_day(trade_date: str, pro=None) -> pd.DataFrame:
    pro = pro or get_pro()
    daily = fetch_daily(trade_date, pro=pro)
    flow = fetch_moneyflow(trade_date, pro=pro)
    if daily.empty and flow.empty:
        return pd.DataFrame()
    if daily.empty:
        out = flow.copy()
        out["turnover"] = 0.0
        out["pct_chg"] = None
    elif flow.empty:
        out = daily.copy()
        for col in ("active_buy", "active_sell", "main_buy", "main_sell", "net_active", *_MONEYFLOW_BUY):
            out[col] = None
    else:
        out = daily.merge(
            flow[
                [
                    "stock_code",
                    "active_buy",
                    "active_sell",
                    "main_buy",
                    "main_sell",
                    "net_active",
                    "zmbtdcje",
                    "zmbddcje",
                    "zmbzdcje",
                    "zmbxdcje",
                    "zmstdcje",
                    "zmsddcje",
                    "zmszdcje",
                    "zmsxdcje",
                ]
            ],
            on="stock_code",
            how="outer",
        )
    names = fetch_stock_basic(pro=pro)
    if not names.empty:
        out = out.merge(names[["stock_code", "name"]], on="stock_code", how="left")
    out["trade_date"] = trade_date
    out["stock_name"] = out.get("name", out.get("stock_name"))
    return out


def fetch_fund_daily(trade_date: str, pro=None) -> pd.DataFrame:
    pro = pro or get_pro()
    td = yyyymmdd(trade_date)
    df = _call(pro, "fund_daily", trade_date=td, fields="ts_code,trade_date,amount,pct_chg,vol")
    if df.empty:
        return df
    df["etf_code"] = df["ts_code"].map(normalize_ts_code)
    df["turnover"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0) * 1000.0
    df["pct_chg"] = pd.to_numeric(df.get("pct_chg"), errors="coerce")
    df["trade_date"] = trade_date
    return df


def fetch_etf_basic(pro=None) -> pd.DataFrame:
    pro = pro or get_pro()
    df = _call(pro, "fund_basic", market="E", fields="ts_code,name,market")
    if df.empty:
        return df
    df["etf_code"] = df["ts_code"].map(normalize_ts_code)
    df["etf_name"] = df["name"]
    df["exchange"] = df["market"].map({"E": "SH", "O": "SZ"}).fillna(df["market"])
    return df


def fetch_etf_share_size(trade_date: str, pro=None) -> pd.DataFrame:
    pro = pro or get_pro()
    td = yyyymmdd(trade_date)
    try:
        df = _call(pro, "etf_share_size", trade_date=td, fields="ts_code,trade_date,total_share,total_size,etf_name")
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return df
    df["etf_code"] = df["ts_code"].map(normalize_ts_code)
    df["total_share"] = pd.to_numeric(df["total_share"], errors="coerce")
    return df


def merge_etf_day(
    trade_date: str,
    pro=None,
    *,
    prev_shares: dict[str, float] | None = None,
) -> pd.DataFrame:
    """合并 ETF 日 K、基本信息与份额。"""
    pro = pro or get_pro()
    daily = fetch_fund_daily(trade_date, pro=pro)
    if daily.empty:
        return pd.DataFrame()
    basic = fetch_etf_basic(pro=pro)
    share = fetch_etf_share_size(trade_date, pro=pro)
    out = daily.merge(basic[["etf_code", "etf_name", "exchange"]], on="etf_code", how="left")
    if not share.empty:
        out = out.merge(share[["etf_code", "total_share"]], on="etf_code", how="left")
    else:
        out["total_share"] = None
    if prev_shares:
        out["share_change"] = out.apply(
            lambda r: (
                float(r["total_share"]) - float(prev_shares.get(str(r["etf_code"]), r["total_share"] or 0))
                if pd.notna(r.get("total_share"))
                else None
            ),
            axis=1,
        )
    else:
        out["share_change"] = None
    return out
