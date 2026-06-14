"""直接调用东财 push2 API。优先 curl_cffi 模拟浏览器 TLS，多节点回退。"""

from __future__ import annotations

import math
import random
import time
from typing import Any
from urllib.parse import urlparse, urlunparse

import pandas as pd
import requests
from requests.adapters import HTTPAdapter

try:
    from curl_cffi import requests as curl_requests

    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

EM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Connection": "close",
}

UT_TOKEN = "bd1d9ddb04089700cf9c27f6f7426281"

# 东财 push2 常见节点，连接失败时轮换
PUSH2_HOSTS = (
    "17.push2.eastmoney.com",
    "push2.eastmoney.com",
    "82.push2.eastmoney.com",
    "29.push2.eastmoney.com",
    "91.push2.eastmoney.com",
)

CURL_IMPERSONATE = "chrome120"


class EmResponse:
    """统一 requests / curl_cffi 响应接口。"""

    def __init__(self, raw: Any):
        self._raw = raw
        self.text = raw.text

    def json(self) -> dict:
        return self._raw.json()

    def raise_for_status(self) -> None:
        self._raw.raise_for_status()


def expand_url_hosts(url: str) -> list[str]:
    parsed = urlparse(url)
    host = parsed.netloc
    urls = [url]
    for alt in PUSH2_HOSTS:
        if alt != host:
            urls.append(urlunparse(parsed._replace(netloc=alt)))
    return urls


def _single_get(url: str, params: dict[str, Any], timeout: int) -> EmResponse:
    if HAS_CURL_CFFI:
        resp = curl_requests.get(
            url,
            params=params,
            headers=EM_HEADERS,
            timeout=timeout,
            impersonate=CURL_IMPERSONATE,
        )
        resp.raise_for_status()
        return EmResponse(resp)

    with requests.Session() as session:
        adapter = HTTPAdapter(pool_connections=1, pool_maxsize=1)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        resp = session.get(url, params=params, timeout=timeout, headers=EM_HEADERS)
        resp.raise_for_status()
        return EmResponse(resp)


def em_get(url: str, params: dict[str, Any], timeout: int = 25, max_retries: int = 8) -> EmResponse:
    urls = expand_url_hosts(url)
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        for try_url in urls:
            try:
                return _single_get(try_url, params, timeout)
            except Exception as exc:
                last_exc = exc
                time.sleep(0.5)
        if attempt < max_retries - 1:
            time.sleep(2**attempt + random.uniform(1.0, 3.0))
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
        time.sleep(random.uniform(0.8, 1.5))
        page_json = em_get(url, params).json()
        frames.append(pd.DataFrame(page_json["data"]["diff"]))
    return pd.concat(frames, ignore_index=True)


def fetch_industry_list() -> pd.DataFrame:
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


def probe_hosts() -> list[tuple[str, bool, str]]:
    """逐个节点探测，便于排障。"""
    params = {
        "pn": "1",
        "pz": "3",
        "po": "1",
        "np": "1",
        "ut": UT_TOKEN,
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:90 t:2 f:!50",
        "fields": "f12,f14",
    }
    results = []
    for host in PUSH2_HOSTS:
        url = f"https://{host}/api/qt/clist/get"
        try:
            resp = _single_get(url, params, timeout=15)
            count = len(resp.json().get("data", {}).get("diff", []))
            results.append((host, True, f"{count} 条"))
        except Exception as exc:
            results.append((host, False, str(exc)[:80]))
        time.sleep(1.0)
    return results


def probe_eastmoney(timeout: int = 15) -> tuple[bool, str]:
    del timeout
    results = probe_hosts()
    ok_hosts = [h for h, ok, _ in results if ok]
    if ok_hosts:
        mode = "curl_cffi" if HAS_CURL_CFFI else "requests"
        return True, f"OK via {ok_hosts[0]} ({mode})"
    detail = "; ".join(f"{h}: {msg}" for h, ok, msg in results if not ok)
    return False, f"全部节点失败: {detail[:200]}"


def patch_akshare_requests(*_args, **_kwargs) -> None:
    return None
