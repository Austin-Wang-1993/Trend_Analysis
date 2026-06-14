"""东财 API 请求增强：补充浏览器请求头，降低被断开连接的概率。"""

from __future__ import annotations

import random
import time
from typing import Any

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


def patch_akshare_requests(max_retries: int = 6, base_delay: float = 2.0) -> None:
    """在调用 akshare 东财接口前执行一次。"""
    import akshare.utils.request as req_module

    if getattr(req_module, "_patched_by_trend_analysis", False):
        return

    def request_with_retry(
        url: str,
        params: dict | None = None,
        timeout: int = 20,
        **_: Any,
    ) -> requests.Response:
        last_exception: Exception | None = None
        for attempt in range(max_retries):
            try:
                with requests.Session() as session:
                    adapter = HTTPAdapter(pool_connections=1, pool_maxsize=1)
                    session.mount("http://", adapter)
                    session.mount("https://", adapter)
                    response = session.get(
                        url,
                        params=params,
                        timeout=timeout,
                        headers=EM_HEADERS,
                    )
                    response.raise_for_status()
                    return response
            except (requests.RequestException, ValueError) as exc:
                last_exception = exc
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt) + random.uniform(0.5, 1.5)
                    time.sleep(delay)
        raise last_exception  # type: ignore[misc]

    req_module.request_with_retry = request_with_retry
    req_module._patched_by_trend_analysis = True


def probe_eastmoney(timeout: int = 15) -> tuple[bool, str]:
    """探测东财 push2 接口是否可达。"""
    url = "https://17.push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1",
        "pz": "5",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
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
            data = resp.json()
            count = len(data.get("data", {}).get("diff", []))
            return True, f"OK, 返回 {count} 条行业记录"
    except Exception as exc:
        return False, str(exc)
