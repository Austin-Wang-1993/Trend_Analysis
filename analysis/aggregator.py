from __future__ import annotations

import json
from datetime import date, datetime

import pandas as pd
from sqlalchemy import delete, select

from core.db import get_session
from core.models import (
    AnalysisSnapshot,
    EtfFundFlow,
    MarketFundFlow,
    SectorFundFlow,
    StockFundFlow,
)


def _share(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return round(numerator / denominator * 100, 4)


def _load_market_metric(session, trade_date: date) -> dict[str, float | None]:
    row = session.scalar(
        select(MarketFundFlow).where(MarketFundFlow.trade_date == trade_date).limit(1)
    )
    if not row:
        return {"inflow": None, "outflow": None, "net": None}
    inflow = row.inflow_amount
    outflow = row.outflow_amount
    net = row.net_inflow or row.main_net_inflow
    if inflow is None and outflow is None and net is not None:
        inflow = max(net, 0)
        outflow = max(-net, 0)
    return {"inflow": inflow, "outflow": outflow, "net": net}


def build_daily_snapshot(trade_date: date) -> dict[str, int]:
    snapshots: list[AnalysisSnapshot] = []

    with get_session() as session:
        market = _load_market_metric(session, trade_date)
        market_denominator = market["net"] or market["inflow"]

        sectors = session.scalars(
            select(SectorFundFlow).where(SectorFundFlow.trade_date == trade_date)
        ).all()
        sector_df = pd.DataFrame(
            [
                {
                    "sector_type": s.sector_type,
                    "sector_name": s.sector_name,
                    "stock_count": s.stock_count,
                    "net_inflow": s.net_inflow or s.main_net_inflow,
                    "inflow_amount": s.inflow_amount,
                    "outflow_amount": s.outflow_amount,
                }
                for s in sectors
            ]
        )
        if not sector_df.empty:
            sector_df = sector_df.sort_values("net_inflow", ascending=False, na_position="last")
            for rank_no, (_, row) in enumerate(sector_df.iterrows(), start=1):
                snapshots.append(
                    AnalysisSnapshot(
                        trade_date=trade_date,
                        entity_type="sector",
                        entity_key=f"{row['sector_type']}:{row['sector_name']}",
                        rank_no=rank_no,
                        net_inflow=row["net_inflow"],
                        inflow_amount=row["inflow_amount"],
                        outflow_amount=row["outflow_amount"],
                        market_share=_share(row["net_inflow"], market_denominator),
                        stock_count=int(row["stock_count"]) if pd.notna(row["stock_count"]) else None,
                        extra_json=json.dumps(
                            {"sector_type": row["sector_type"], "sector_name": row["sector_name"]},
                            ensure_ascii=False,
                        ),
                    )
                )

        stocks = session.scalars(
            select(StockFundFlow).where(StockFundFlow.trade_date == trade_date)
        ).all()
        stock_df = pd.DataFrame(
            [
                {
                    "stock_code": s.stock_code,
                    "stock_name": s.stock_name,
                    "sector_name": s.sector_name,
                    "net_inflow": s.net_inflow or s.main_net_inflow,
                    "inflow_amount": s.inflow_amount,
                    "outflow_amount": s.outflow_amount,
                }
                for s in stocks
            ]
        )
        if not stock_df.empty:
            stock_df = stock_df.sort_values("net_inflow", ascending=False, na_position="last")
            for rank_no, (_, row) in enumerate(stock_df.head(200).iterrows(), start=1):
                sector_net = None
                if row["sector_name"]:
                    sector_row = sector_df[
                        (sector_df["sector_name"] == row["sector_name"])
                        & (sector_df["sector_type"] == "industry")
                    ]
                    if not sector_row.empty:
                        sector_net = sector_row.iloc[0]["net_inflow"]
                snapshots.append(
                    AnalysisSnapshot(
                        trade_date=trade_date,
                        entity_type="stock",
                        entity_key=row["stock_code"],
                        rank_no=rank_no,
                        net_inflow=row["net_inflow"],
                        inflow_amount=row["inflow_amount"],
                        outflow_amount=row["outflow_amount"],
                        market_share=_share(row["net_inflow"], market_denominator),
                        parent_share=_share(row["net_inflow"], sector_net),
                        extra_json=json.dumps(
                            {
                                "stock_name": row["stock_name"],
                                "sector_name": row["sector_name"],
                            },
                            ensure_ascii=False,
                        ),
                    )
                )

        etfs = session.scalars(
            select(EtfFundFlow).where(EtfFundFlow.trade_date == trade_date)
        ).all()
        etf_df = pd.DataFrame(
            [
                {
                    "etf_code": e.etf_code,
                    "etf_name": e.etf_name,
                    "net_inflow": e.main_net_inflow,
                }
                for e in etfs
            ]
        )
        if not etf_df.empty:
            etf_df = etf_df.sort_values("net_inflow", ascending=False, na_position="last")
            for rank_no, (_, row) in enumerate(etf_df.iterrows(), start=1):
                snapshots.append(
                    AnalysisSnapshot(
                        trade_date=trade_date,
                        entity_type="etf",
                        entity_key=row["etf_code"],
                        rank_no=rank_no,
                        net_inflow=row["net_inflow"],
                        market_share=_share(row["net_inflow"], market_denominator),
                        extra_json=json.dumps({"etf_name": row["etf_name"]}, ensure_ascii=False),
                    )
                )

        if market_denominator is not None:
            snapshots.append(
                AnalysisSnapshot(
                    trade_date=trade_date,
                    entity_type="market",
                    entity_key="A_SHARE",
                    rank_no=1,
                    net_inflow=market["net"],
                    inflow_amount=market["inflow"],
                    outflow_amount=market["outflow"],
                    market_share=100.0 if market["net"] is not None else None,
                    extra_json=json.dumps({"note": "大盘汇总"}, ensure_ascii=False),
                )
            )

        session.execute(delete(AnalysisSnapshot).where(AnalysisSnapshot.trade_date == trade_date))
        session.add_all(snapshots)
        counts = {
            "market": sum(1 for s in snapshots if s.entity_type == "market"),
            "sector": sum(1 for s in snapshots if s.entity_type == "sector"),
            "stock": sum(1 for s in snapshots if s.entity_type == "stock"),
            "etf": sum(1 for s in snapshots if s.entity_type == "etf"),
        }

    return counts
