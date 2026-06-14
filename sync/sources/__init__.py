from __future__ import annotations

from sync.sources.akshare_em import EastMoneySource
from sync.sources.akshare_ths import TongHuaShunSource
from sync.sources.base import FundFlowSource

SOURCE_REGISTRY: dict[str, type[FundFlowSource]] = {
    "eastmoney": EastMoneySource,
    "tonghuashun": TongHuaShunSource,
}


def get_source(name: str) -> FundFlowSource:
    if name not in SOURCE_REGISTRY:
        raise KeyError(f"未知数据源: {name}")
    return SOURCE_REGISTRY[name]()
