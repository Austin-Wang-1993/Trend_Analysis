from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import pandas as pd


def parse_trade_date(value: Any) -> date | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if not text:
        return None
    return pd.to_datetime(text).date()


def normalize_stock_code(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text.zfill(6)


def parse_money_yuan(value: Any) -> float | None:
    """将金额统一解析为元。支持数字、'6.49亿'、'7588.54万' 等格式。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().replace(",", "")
    if not text or text in {"--", "-", "nan"}:
        return None

    multiplier = 1.0
    if text.endswith("亿"):
        multiplier = 1e8
        text = text[:-1]
    elif text.endswith("万"):
        multiplier = 1e4
        text = text[:-1]

    try:
        return float(text) * multiplier
    except ValueError:
        return None


def parse_percent(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("%", "")
    if not text or text in {"--", "-"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def safe_float(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def infer_latest_trade_date_from_frames(*frames: pd.DataFrame | None) -> date:
    for frame in frames:
        if frame is None or frame.empty:
            continue
        for col in ("trade_date", "数据日期", "日期"):
            if col in frame.columns:
                dates = frame[col].dropna()
                if not dates.empty:
                    parsed = parse_trade_date(dates.iloc[-1])
                    if parsed:
                        return parsed
    return date.today()
