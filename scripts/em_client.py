"""直接调用东财 push2 API（带浏览器请求头），不依赖 akshare 请求层。"""

from __future__ import annotations

import math
import random
import time
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter

EM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

UT_TOKEN = "bd1d9ddb04089700cf9c27f6f7426281"


def em_get(url: str, params: dict[str, Any], timeout: int = 20, max_retries: int = 6) -> requests.Response:
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            with requests.Session() as session:
                adapter = HTTPAdapter(pool_connections=1, pool_maxsize=1)
                session.mount("http://", adapter)
                session.mount("https://", adapter)
                resp = session.get(url, params=params, timeout=timeout, headers=EM_HEADERS)
                resp.raise_for_status()
                return resp
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                time.sleep(2**attempt + random.uniform(0.5, 1.5))
    raise last_exc  # type: ignore[misc]


def fetch_paginated(url: str, base_params: dict[str, Any]) -> pd.DataFrame:
    params = base_params.copy()
    first = em_get(url, params).json()
    diff = first["data"]["diff"]
    if not diff:
        return pd.DataFrame()
    per_page = len(diff)
    total_page = math.ceil(first["data"]["total"] / per_page)
    frames = [pd.DataFrame(diff)]
    for page in range(2, total_page + 1):
        params["pn"] = str(page)
        time.sleep(random.uniform(0.5, 1.2))
        page_json = em_get(url, params).json()
        frames.append(pd.DataFrame(page_json["data"]["diff"]))
    return pd.concat(frames, ignore_index=True)


def fetch_industry_list() -> pd.DataFrame:
    """等同 stock_board_industry_name_em，仅保留板块代码、名称。"""
    url = "https://17.push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1",
        "pz": "100",
        "po": "1",
        "np": "1",
        "ut": UT_TOKEN,
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:90 t:2 f:!50",
        "fields": "f12,f14",
    }
    df = fetch_paginated(url, params)
    return df.rename(columns={"f12": "industry_code", "f14": "industry_name"})[
        ["industry_code", "industry_name"]
    ]


def fetch_industry_constituents(industry_code: str) -> pd.DataFrame:
    """等同 stock_board_industry_cons_em(symbol=行业代码)。"""
    url = "https://29.push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1",
        "pz": "100",
        "po": "1",
        "np": "1",
        "ut": UT_TOKEN,
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": f"b:{industry_code} f:!50",
        "fields": "f12,f14,f6",
    }
    df = fetch_paginated(url, params)
    return df.rename(columns={"f12": "stock_code", "f14": "stock_name", "f6": "turnover"})


def fetch_a_share_spot() -> pd.DataFrame:
    """等同 stock_zh_a_spot_em，仅保留代码、名称、成交额。"""
    url = "https://82.push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1",
        "pz": "100",
        "po": "1",
        "np": "1",
        "ut": UT_TOKEN,
        "fltt": "2",
        "invt": "2",
        "fid": "f12",
        "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
        "fields": "f12,f14,f6",
    }
    df = fetch_paginated(url, params)
    return df.rename(columns={"f12": "stock_code", "f14": "stock_name", "f6": "turnover"})


def probe_eastmoney(timeout: int = 15) -> tuple[bool, str]:
    url = "https://17.push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1",
        "pz": "5",
        "po": "1",
        "np": "1",
        "ut": UT_TOKEN,
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:90 t:2 f:!50",
        "fields": "f12,f14",
    }
    try:
        with requests.Session() as session:
            resp = session.get(url, params=params, timeout=timeout, headers=EM_HEADERS)
            resp.raise_for_status()
            count = len(resp.json().get("data", {}).get("diff", []))
            return True, f"OK, 返回 {count} 条行业记录"
    except Exception as exc:
        return False, str(exc)


# 兼容旧补丁入口（现改为直连，保留空操作避免旧脚本报错）
def patch_akshare_requests(*_args, **_kwargs) -> None:
    return None
