from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class MarketFundFlow(Base):
    """大盘资金流量（A 股整体）。"""

    __tablename__ = "market_fund_flow"
    __table_args__ = (UniqueConstraint("trade_date", "data_source", name="uq_market_date_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    index_sh_close: Mapped[float | None] = mapped_column(Float)
    index_sh_pct_chg: Mapped[float | None] = mapped_column(Float)
    index_sz_close: Mapped[float | None] = mapped_column(Float)
    index_sz_pct_chg: Mapped[float | None] = mapped_column(Float)
    inflow_amount: Mapped[float | None] = mapped_column(Float)
    outflow_amount: Mapped[float | None] = mapped_column(Float)
    net_inflow: Mapped[float | None] = mapped_column(Float)
    main_net_inflow: Mapped[float | None] = mapped_column(Float)
    main_net_inflow_ratio: Mapped[float | None] = mapped_column(Float)
    super_large_net_inflow: Mapped[float | None] = mapped_column(Float)
    super_large_net_inflow_ratio: Mapped[float | None] = mapped_column(Float)
    large_net_inflow: Mapped[float | None] = mapped_column(Float)
    large_net_inflow_ratio: Mapped[float | None] = mapped_column(Float)
    medium_net_inflow: Mapped[float | None] = mapped_column(Float)
    medium_net_inflow_ratio: Mapped[float | None] = mapped_column(Float)
    small_net_inflow: Mapped[float | None] = mapped_column(Float)
    small_net_inflow_ratio: Mapped[float | None] = mapped_column(Float)
    data_source: Mapped[str] = mapped_column(String(32), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SectorFundFlow(Base):
    """板块资金流量（行业 / 概念 / 地域）。"""

    __tablename__ = "sector_fund_flow"
    __table_args__ = (
        UniqueConstraint(
            "trade_date",
            "sector_type",
            "sector_name",
            "data_source",
            name="uq_sector_date_type_name_source",
        ),
        Index("ix_sector_date_type", "trade_date", "sector_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    sector_type: Mapped[str] = mapped_column(String(16), nullable=False)
    sector_name: Mapped[str] = mapped_column(String(64), nullable=False)
    stock_count: Mapped[int | None] = mapped_column(Integer)
    pct_chg: Mapped[float | None] = mapped_column(Float)
    inflow_amount: Mapped[float | None] = mapped_column(Float)
    outflow_amount: Mapped[float | None] = mapped_column(Float)
    net_inflow: Mapped[float | None] = mapped_column(Float)
    main_net_inflow: Mapped[float | None] = mapped_column(Float)
    main_net_inflow_ratio: Mapped[float | None] = mapped_column(Float)
    super_large_net_inflow: Mapped[float | None] = mapped_column(Float)
    super_large_net_inflow_ratio: Mapped[float | None] = mapped_column(Float)
    large_net_inflow: Mapped[float | None] = mapped_column(Float)
    large_net_inflow_ratio: Mapped[float | None] = mapped_column(Float)
    medium_net_inflow: Mapped[float | None] = mapped_column(Float)
    medium_net_inflow_ratio: Mapped[float | None] = mapped_column(Float)
    small_net_inflow: Mapped[float | None] = mapped_column(Float)
    small_net_inflow_ratio: Mapped[float | None] = mapped_column(Float)
    data_source: Mapped[str] = mapped_column(String(32), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class StockFundFlow(Base):
    """个股资金流量。"""

    __tablename__ = "stock_fund_flow"
    __table_args__ = (
        UniqueConstraint(
            "trade_date",
            "stock_code",
            "data_source",
            name="uq_stock_date_code_source",
        ),
        Index("ix_stock_date_sector", "trade_date", "sector_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    stock_code: Mapped[str] = mapped_column(String(10), nullable=False)
    stock_name: Mapped[str] = mapped_column(String(64), nullable=False)
    sector_name: Mapped[str | None] = mapped_column(String(64))
    sector_type: Mapped[str | None] = mapped_column(String(16))
    price: Mapped[float | None] = mapped_column(Float)
    pct_chg: Mapped[float | None] = mapped_column(Float)
    turnover: Mapped[float | None] = mapped_column(Float)
    inflow_amount: Mapped[float | None] = mapped_column(Float)
    outflow_amount: Mapped[float | None] = mapped_column(Float)
    net_inflow: Mapped[float | None] = mapped_column(Float)
    main_net_inflow: Mapped[float | None] = mapped_column(Float)
    main_net_inflow_ratio: Mapped[float | None] = mapped_column(Float)
    super_large_net_inflow: Mapped[float | None] = mapped_column(Float)
    super_large_net_inflow_ratio: Mapped[float | None] = mapped_column(Float)
    large_net_inflow: Mapped[float | None] = mapped_column(Float)
    large_net_inflow_ratio: Mapped[float | None] = mapped_column(Float)
    medium_net_inflow: Mapped[float | None] = mapped_column(Float)
    medium_net_inflow_ratio: Mapped[float | None] = mapped_column(Float)
    small_net_inflow: Mapped[float | None] = mapped_column(Float)
    small_net_inflow_ratio: Mapped[float | None] = mapped_column(Float)
    data_source: Mapped[str] = mapped_column(String(32), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class EtfFundFlow(Base):
    """ETF 资金流量。"""

    __tablename__ = "etf_fund_flow"
    __table_args__ = (
        UniqueConstraint("trade_date", "etf_code", "data_source", name="uq_etf_date_code_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    etf_code: Mapped[str] = mapped_column(String(10), nullable=False)
    etf_name: Mapped[str] = mapped_column(String(64), nullable=False)
    price: Mapped[float | None] = mapped_column(Float)
    pct_chg: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    turnover: Mapped[float | None] = mapped_column(Float)
    main_net_inflow: Mapped[float | None] = mapped_column(Float)
    main_net_inflow_ratio: Mapped[float | None] = mapped_column(Float)
    super_large_net_inflow: Mapped[float | None] = mapped_column(Float)
    super_large_net_inflow_ratio: Mapped[float | None] = mapped_column(Float)
    large_net_inflow: Mapped[float | None] = mapped_column(Float)
    large_net_inflow_ratio: Mapped[float | None] = mapped_column(Float)
    medium_net_inflow: Mapped[float | None] = mapped_column(Float)
    medium_net_inflow_ratio: Mapped[float | None] = mapped_column(Float)
    small_net_inflow: Mapped[float | None] = mapped_column(Float)
    small_net_inflow_ratio: Mapped[float | None] = mapped_column(Float)
    data_source: Mapped[str] = mapped_column(String(32), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SyncLog(Base):
    """数据同步任务日志。"""

    __tablename__ = "sync_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_name: Mapped[str] = mapped_column(String(64), nullable=False)
    trade_date: Mapped[date | None] = mapped_column(Date)
    data_source: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    row_count: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class AnalysisSnapshot(Base):
    """分析层产出：某日汇总指标（占比、排名等），与原始同步数据解耦。"""

    __tablename__ = "analysis_snapshot"
    __table_args__ = (
        UniqueConstraint("trade_date", "entity_type", "entity_key", name="uq_analysis_snapshot"),
        Index("ix_analysis_date_type", "trade_date", "entity_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_key: Mapped[str] = mapped_column(String(128), nullable=False)
    rank_no: Mapped[int | None] = mapped_column(Integer)
    net_inflow: Mapped[float | None] = mapped_column(Float)
    inflow_amount: Mapped[float | None] = mapped_column(Float)
    outflow_amount: Mapped[float | None] = mapped_column(Float)
    market_share: Mapped[float | None] = mapped_column(Float)
    parent_share: Mapped[float | None] = mapped_column(Float)
    stock_count: Mapped[int | None] = mapped_column(Integer)
    extra_json: Mapped[str | None] = mapped_column(Text)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
