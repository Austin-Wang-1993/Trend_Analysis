from __future__ import annotations

from datetime import date, datetime

import pandas as pd
from loguru import logger

from core.config import settings
from core.db import get_session, replace_rows
from core.models import (
    EtfFundFlow,
    MarketFundFlow,
    SectorFundFlow,
    StockFundFlow,
    SyncLog,
)
from core.utils import infer_latest_trade_date_from_frames
from sync.sources import get_source


def _first_available(fetch_fn, sources: list[str]) -> tuple[pd.DataFrame, str]:
    last_error: Exception | None = None
    for source_name in sources:
        try:
            source = get_source(source_name)
            frame = fetch_fn(source)
            if frame is not None and not frame.empty:
                return frame, source_name
        except Exception as exc:
            last_error = exc
            logger.warning("数据源 {} 拉取失败: {}", source_name, exc)
    if last_error:
        raise last_error
    return pd.DataFrame(), sources[0] if sources else "unknown"


def _log_sync(job_name: str, trade_date: date | None, source: str, status: str, rows: int, message: str = ""):
    with get_session() as session:
        session.add(
            SyncLog(
                job_name=job_name,
                trade_date=trade_date,
                data_source=source,
                status=status,
                row_count=rows,
                message=message,
                finished_at=datetime.utcnow(),
            )
        )


def _df_to_models(frame: pd.DataFrame, model_cls, field_map: dict[str, str] | None = None):
    records = []
    for _, row in frame.iterrows():
        payload = {}
        for col in frame.columns:
            key = field_map.get(col, col) if field_map else col
            if hasattr(model_cls, key):
                payload[key] = row[col]
        payload.setdefault("synced_at", datetime.utcnow())
        records.append(model_cls(**payload))
    return records


def sync_market(trade_date: date | None = None) -> int:
    sources = settings.source_priority_list

    def _fetch(source):
        return source.fetch_market(trade_date)

    frame, source_name = _first_available(_fetch, sources)
    if trade_date is None:
        trade_date = infer_latest_trade_date_from_frames(frame)
    if "trade_date" not in frame.columns or frame["trade_date"].isna().all():
        frame["trade_date"] = trade_date
    frame = frame[frame["trade_date"] == trade_date]
    rows = _df_to_models(frame, MarketFundFlow)
    with get_session() as session:
        count = replace_rows(session, MarketFundFlow, trade_date, source_name, rows)
    _log_sync("market", trade_date, source_name, "success", count)
    return count


def sync_sectors(trade_date: date | None = None) -> int:
    sources = settings.source_priority_list
    total = 0
    used_source = sources[0]

    for sector_type in ("industry", "concept"):
        def _fetch(source, st=sector_type):
            return source.fetch_sectors(st, trade_date)

        frame, source_name = _first_available(_fetch, sources)
        used_source = source_name
        if trade_date is None:
            trade_date = infer_latest_trade_date_from_frames(frame)
        frame["trade_date"] = trade_date
        rows = _df_to_models(frame, SectorFundFlow)
        with get_session() as session:
            for row in rows:
                session.execute(
                    SectorFundFlow.__table__.delete().where(
                        SectorFundFlow.trade_date == trade_date,
                        SectorFundFlow.sector_type == row.sector_type,
                        SectorFundFlow.sector_name == row.sector_name,
                        SectorFundFlow.data_source == source_name,
                    )
                )
            session.add_all(rows)
            total += len(rows)

    _log_sync("sector", trade_date, used_source, "success", total)
    return total


def sync_stocks(trade_date: date | None = None) -> int:
    sources = settings.source_priority_list

    def _fetch(source):
        return source.fetch_stocks(trade_date)

    frame, source_name = _first_available(_fetch, sources)
    if trade_date is None:
        trade_date = infer_latest_trade_date_from_frames(frame)
    frame["trade_date"] = trade_date
    rows = _df_to_models(frame, StockFundFlow)
    with get_session() as session:
        count = replace_rows(session, StockFundFlow, trade_date, source_name, rows)
    _log_sync("stock", trade_date, source_name, "success", count)
    return count


def sync_etfs(trade_date: date | None = None) -> int:
    sources = settings.source_priority_list

    def _fetch(source):
        return source.fetch_etfs(trade_date)

    frame, source_name = _first_available(_fetch, sources)
    if trade_date is None:
        trade_date = infer_latest_trade_date_from_frames(frame)
    if "trade_date" not in frame.columns or frame["trade_date"].isna().any():
        frame["trade_date"] = frame["trade_date"].fillna(trade_date)
    frame = frame[frame["trade_date"] == trade_date]
    rows = _df_to_models(frame, EtfFundFlow)
    with get_session() as session:
        count = replace_rows(session, EtfFundFlow, trade_date, source_name, rows)
    _log_sync("etf", trade_date, source_name, "success", count)
    return count


def sync_all(trade_date: date | None = None) -> dict[str, int]:
    if trade_date is None:
        # ETF 行情带「数据日期」，优先用于推断最近交易日
        try:
            from sync.sources import get_source

            etf_frame = get_source(settings.source_priority_list[0]).fetch_etfs()
            trade_date = infer_latest_trade_date_from_frames(etf_frame)
        except Exception:
            trade_date = None

    return {
        "market": sync_market(trade_date),
        "sector": sync_sectors(trade_date),
        "stock": sync_stocks(trade_date),
        "etf": sync_etfs(trade_date),
    }
