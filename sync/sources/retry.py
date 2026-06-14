from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from tenacity import retry, stop_after_attempt, wait_fixed

from core.config import settings

T = TypeVar("T")


def call_with_retry(func: Callable[..., T], *args, **kwargs) -> T:
    @retry(
        stop=stop_after_attempt(settings.api_max_retries),
        wait=wait_fixed(settings.api_retry_wait_seconds),
        reraise=True,
    )
    def _inner() -> T:
        return func(*args, **kwargs)

    return _inner()
