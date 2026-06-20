"""Tushare Pro 共享工具（v4.0 主数据源）。

职责：
- `.env` / 环境变量读取 `TUSHARE_TOKEN`
- `pro_api` 懒加载封装 + 限频 + 重试（`call_api`）
- 单位换算与 `moneyflow` 四档买卖聚合（纯函数，可离线单测）
- `ts_code` ↔ 6 位代码互转

字段口径（见 docs/TUSHARE_API.md）：
- `daily.amount` 千元 → 元（×1000）
- `moneyflow.buy_*_amount / sell_*_amount` 万元 → 元（×10000）
- 主动买入 = 四档买入之和；主力买入 = 大单 + 特大单
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

QIAN_TO_YUAN = 1000.0  # 千元 → 元（daily.amount / fund_daily.amount）
WAN_TO_YUAN = 10000.0  # 万元 → 元（moneyflow 各档金额）

# moneyflow 四档买/卖金额字段（单位：万元）
MONEYFLOW_BUY_FIELDS = ("buy_sm_amount", "buy_md_amount", "buy_lg_amount", "buy_elg_amount")
MONEYFLOW_SELL_FIELDS = ("sell_sm_amount", "sell_md_amount", "sell_lg_amount", "sell_elg_amount")
MAIN_BUY_FIELDS = ("buy_lg_amount", "buy_elg_amount")  # 主力 = 大单 + 特大单
MAIN_SELL_FIELDS = ("sell_lg_amount", "sell_elg_amount")

# 8 档原子字段（沿用 v3.6 schema）← Tushare 四档买卖映射（已 ×10000 转元）
#   特大/大/中/小 对应 elg/lg/md/sm
ATOMIC_FROM_MONEYFLOW: dict[str, str] = {
    "zmbtdcje": "buy_elg_amount",
    "zmbddcje": "buy_lg_amount",
    "zmbzdcje": "buy_md_amount",
    "zmbxdcje": "buy_sm_amount",
    "zmstdcje": "sell_elg_amount",
    "zmsddcje": "sell_lg_amount",
    "zmszdcje": "sell_md_amount",
    "zmsxdcje": "sell_sm_amount",
}


# --------------------------------------------------------------------------- #
# .env 与 Token
# --------------------------------------------------------------------------- #
def load_dotenv(path: str | Path | None = None) -> None:
    """轻量 .env 加载：仅在变量未设置时注入；支持 `export KEY=VALUE`、引号、行内注释。

    统一替代分散在多个脚本里的重复实现。
    """
    env_path = Path(path) if path else ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if value and value[0] in {'"', "'"}:
            # 引号包裹：取首尾引号之间内容，忽略其后的行内注释
            quote = value[0]
            end = value.find(quote, 1)
            value = value[1:end] if end != -1 else value[1:]
        elif "#" in value:
            value = value.split("#", 1)[0].strip()
        if key and key not in os.environ:
            os.environ[key] = value


def get_tushare_token() -> str:
    load_dotenv()
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        raise ValueError(
            "未设置 TUSHARE_TOKEN。请到 https://tushare.pro 个人中心获取 token，"
            "写入 .env：TUSHARE_TOKEN=你的token"
        )
    if "你的" in token or token.lower() in {"你的token", "your-token", "<token>"}:
        raise ValueError("TUSHARE_TOKEN 仍是占位符，请替换为 Tushare 个人中心的真实 token")
    return token


# --------------------------------------------------------------------------- #
# 限频请求封装
# --------------------------------------------------------------------------- #
class RateLimiter:
    """简单最小间隔限频（线程安全）。Tushare 按积分限制每分钟调用次数。"""

    def __init__(self, min_interval_sec: float = 0.0) -> None:
        self.min_interval = max(0.0, min_interval_sec)
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            delta = now - self._last
            if delta < self.min_interval:
                time.sleep(self.min_interval - delta)
            self._last = time.monotonic()


_pro: Any = None
_rate = RateLimiter(min_interval_sec=float(os.environ.get("TUSHARE_MIN_INTERVAL", "0.35")))


def get_pro(token: str | None = None) -> Any:
    """懒加载 tushare.pro_api（仅在真正调用时 import，便于离线单测）。"""
    global _pro
    if _pro is None:
        import tushare as ts  # noqa: PLC0415  延迟导入

        _pro = ts.pro_api(token or get_tushare_token())
    return _pro


def call_api(api_name: str, *, retries: int = 5, **kwargs: Any) -> pd.DataFrame:
    """调用 Tushare 接口，带限频与指数退避重试。返回 DataFrame。"""
    pro = get_pro()
    last_error: Exception | None = None
    for attempt in range(retries):
        _rate.wait()
        try:
            df = getattr(pro, api_name)(**kwargs)
            if df is None:
                return pd.DataFrame()
            return df
        except Exception as exc:  # noqa: BLE001  Tushare 抛通用 Exception
            last_error = exc
            msg = str(exc)
            # 触发每分钟限频时退避更久
            backoff = (2.0 if ("每分钟" in msg or "minute" in msg.lower()) else 0.6) * (attempt + 1)
            time.sleep(backoff)
    raise RuntimeError(f"Tushare 接口 {api_name} 调用失败：{last_error}") from last_error


# --------------------------------------------------------------------------- #
# 代码互转
# --------------------------------------------------------------------------- #
def ts_code_to_code6(ts_code: str) -> str:
    """`000001.SZ` → `000001`。"""
    return str(ts_code).split(".")[0].strip()


def code6_to_ts_code(code6: str, exchange: str | None = None) -> str:
    """6 位代码 → Tushare `ts_code`。exchange 可显式给出（SH/SZ/BJ），否则按规则推断。"""
    c = str(code6).strip()
    if "." in c:
        return c
    if exchange:
        ex = exchange.upper()
        suffix = {"SH": "SH", "SSE": "SH", "SZ": "SZ", "SZSE": "SZ", "BJ": "BJ", "BSE": "BJ"}.get(ex, ex)
        return f"{c}.{suffix}"
    if c.startswith(("60", "68", "5", "11", "9")):
        return f"{c}.SH"
    if c.startswith(("4", "8", "92")):
        return f"{c}.BJ"
    return f"{c}.SZ"


# --------------------------------------------------------------------------- #
# 单位换算与聚合（纯函数）
# --------------------------------------------------------------------------- #
def _row_sum(row: pd.Series, fields: tuple[str, ...]) -> float:
    total = 0.0
    for f in fields:
        v = row.get(f)
        if v is not None and pd.notna(v):
            total += float(v)
    return total


def moneyflow_to_stock_flow(df: pd.DataFrame) -> pd.DataFrame:
    """`moneyflow` 原始 DataFrame → 个股资金流（单位元）。

    输出列：stock_code, trade_date(若有), active_buy, active_sell, net_active,
    main_buy, main_sell + 8 档原子字段（zmb*/zms*，元）。
    """
    if df is None or df.empty:
        return pd.DataFrame(
            columns=[
                "stock_code", "active_buy", "active_sell", "net_active",
                "main_buy", "main_sell", *ATOMIC_FROM_MONEYFLOW.keys(),
            ]
        )
    out = pd.DataFrame()
    if "ts_code" in df.columns:
        out["stock_code"] = df["ts_code"].map(ts_code_to_code6)
    elif "stock_code" in df.columns:
        out["stock_code"] = df["stock_code"].astype(str)
    if "trade_date" in df.columns:
        out["trade_date"] = df["trade_date"].astype(str)

    active_buy = df.apply(lambda r: _row_sum(r, MONEYFLOW_BUY_FIELDS), axis=1) * WAN_TO_YUAN
    active_sell = df.apply(lambda r: _row_sum(r, MONEYFLOW_SELL_FIELDS), axis=1) * WAN_TO_YUAN
    main_buy = df.apply(lambda r: _row_sum(r, MAIN_BUY_FIELDS), axis=1) * WAN_TO_YUAN
    main_sell = df.apply(lambda r: _row_sum(r, MAIN_SELL_FIELDS), axis=1) * WAN_TO_YUAN
    out["active_buy"] = active_buy
    out["active_sell"] = active_sell
    out["net_active"] = active_buy - active_sell
    out["main_buy"] = main_buy
    out["main_sell"] = main_sell
    for atomic_col, mf_col in ATOMIC_FROM_MONEYFLOW.items():
        if mf_col in df.columns:
            out[atomic_col] = pd.to_numeric(df[mf_col], errors="coerce").fillna(0.0) * WAN_TO_YUAN
        else:
            out[atomic_col] = 0.0
    return out.reset_index(drop=True)


def daily_to_turnover(df: pd.DataFrame) -> pd.DataFrame:
    """`daily` 原始 DataFrame → 个股成交额（元）与涨跌幅。

    输出列：stock_code, trade_date(若有), turnover(元), pct_chg。
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["stock_code", "turnover", "pct_chg"])
    out = pd.DataFrame()
    if "ts_code" in df.columns:
        out["stock_code"] = df["ts_code"].map(ts_code_to_code6)
    elif "stock_code" in df.columns:
        out["stock_code"] = df["stock_code"].astype(str)
    if "trade_date" in df.columns:
        out["trade_date"] = df["trade_date"].astype(str)
    out["turnover"] = pd.to_numeric(df.get("amount"), errors="coerce") * QIAN_TO_YUAN
    out["pct_chg"] = pd.to_numeric(df.get("pct_chg"), errors="coerce")
    return out.reset_index(drop=True)


def fund_daily_to_turnover(df: pd.DataFrame) -> pd.DataFrame:
    """`fund_daily` 原始 DataFrame → ETF 成交额（元）与涨跌幅。"""
    if df is None or df.empty:
        return pd.DataFrame(columns=["etf_code", "turnover", "pct_chg"])
    out = pd.DataFrame()
    if "ts_code" in df.columns:
        out["etf_code"] = df["ts_code"].map(ts_code_to_code6)
        out["exchange"] = df["ts_code"].map(lambda x: str(x).split(".")[-1] if "." in str(x) else None)
    if "trade_date" in df.columns:
        out["trade_date"] = df["trade_date"].astype(str)
    out["turnover"] = pd.to_numeric(df.get("amount"), errors="coerce") * QIAN_TO_YUAN
    out["pct_chg"] = pd.to_numeric(df.get("pct_chg"), errors="coerce")
    return out.reset_index(drop=True)


def count_up_down(pct_chg: pd.Series) -> tuple[int, int, int]:
    """涨跌平家数：>0 上涨，<0 下跌，=0/缺失 平盘。"""
    s = pd.to_numeric(pct_chg, errors="coerce")
    up = int((s > 0).sum())
    down = int((s < 0).sum())
    flat = int(len(s) - up - down)
    return up, down, flat
