"""SQLite 历史库：market / sector / stock / etf 日表 + 任务与配置。"""

from __future__ import annotations

import io
import json
import sqlite3
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

CST = ZoneInfo("Asia/Shanghai")

DEFAULT_SETTINGS: dict[str, str] = {
    "schedule_enabled": "true",
    "schedule_time": "21:35",
    "schedule_timezone": "Asia/Shanghai",
    "schedule_run_mode": "trading_day",
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS market_daily (
    trade_date TEXT PRIMARY KEY,
    turnover REAL NOT NULL DEFAULT 0,
    active_buy REAL,
    active_sell REAL,
    net_active REAL,
    stock_count INTEGER,
    snapshot_time TEXT
);
CREATE TABLE IF NOT EXISTS sector_daily (
    trade_date TEXT NOT NULL,
    sector_code TEXT NOT NULL,
    sector_name TEXT NOT NULL,
    turnover REAL NOT NULL DEFAULT 0,
    turnover_pct REAL,
    active_buy REAL,
    active_sell REAL,
    net_active REAL,
    stock_count INTEGER,
    PRIMARY KEY (trade_date, sector_code)
);
CREATE TABLE IF NOT EXISTS stock_daily (
    trade_date TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    stock_name TEXT,
    sector_code TEXT,
    sector_name TEXT,
    turnover REAL,
    active_buy REAL,
    active_sell REAL,
    net_active REAL,
    PRIMARY KEY (trade_date, stock_code)
);
CREATE TABLE IF NOT EXISTS etf_daily (
    trade_date TEXT NOT NULL,
    etf_code TEXT NOT NULL,
    etf_name TEXT,
    exchange TEXT,
    turnover REAL NOT NULL DEFAULT 0,
    turnover_pct REAL,
    PRIMARY KEY (trade_date, etf_code)
);
CREATE TABLE IF NOT EXISTS fetch_jobs (
    job_id TEXT PRIMARY KEY,
    trade_date TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    duration_sec REAL,
    progress TEXT,
    error_message TEXT,
    log_path TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trading_calendar (
    trade_date TEXT PRIMARY KEY,
    is_trading INTEGER NOT NULL,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sector_daily_date ON sector_daily(trade_date);
CREATE INDEX IF NOT EXISTS idx_stock_daily_sector ON stock_daily(trade_date, sector_code);
CREATE INDEX IF NOT EXISTS idx_stock_daily_code ON stock_daily(stock_code, trade_date);
CREATE INDEX IF NOT EXISTS idx_etf_daily_date ON etf_daily(trade_date);
CREATE INDEX IF NOT EXISTS idx_fetch_jobs_status ON fetch_jobs(status);
"""


class HistoryStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
            for key, value in DEFAULT_SETTINGS.items():
                conn.execute(
                    "INSERT OR IGNORE INTO app_settings(key, value) VALUES (?, ?)",
                    (key, value),
                )
            conn.commit()

    def get_settings(self) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
        settings = dict(DEFAULT_SETTINGS)
        settings.update({r["key"]: r["value"] for r in rows})
        return settings

    def set_settings(self, updates: dict[str, str]) -> dict[str, str]:
        with self._connect() as conn:
            for key, value in updates.items():
                conn.execute(
                    """
                    INSERT INTO app_settings(key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value
                    """,
                    (key, str(value)),
                )
            conn.commit()
        return self.get_settings()

    def list_trading_days(self, limit: int = 5) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT trade_date FROM market_daily
                ORDER BY trade_date DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        days = [r["trade_date"] for r in rows]
        if days:
            return sorted(days)
        # fallback: any table
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT trade_date FROM stock_daily
                ORDER BY trade_date DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return sorted([r["trade_date"] for r in rows])

    def upsert_snapshot(
        self,
        trade_date: str,
        stock_df: pd.DataFrame,
        sector_df: pd.DataFrame,
        sector_ff_df: pd.DataFrame | None,
        market_row: dict[str, Any] | None,
        etf_df: pd.DataFrame | None,
        snapshot_time: str,
    ) -> None:
        market_turnover = float(stock_df["turnover"].sum()) if "turnover" in stock_df.columns else 0.0
        if market_row:
            m = dict(market_row)
        else:
            m = {"turnover": market_turnover, "stock_count": len(stock_df)}
        m.setdefault("trade_date", trade_date)
        m.setdefault("snapshot_time", snapshot_time)
        m.setdefault("turnover", market_turnover)

        sector = sector_df.copy()
        if sector_ff_df is not None and not sector_ff_df.empty:
            ff_cols = [c for c in sector_ff_df.columns if c not in sector.columns or c in ("active_buy", "active_sell", "net_active", "large_buy", "large_sell", "net_large")]
            sector = sector.merge(
                sector_ff_df[["sector_code"] + [c for c in ("active_buy", "active_sell", "net_active", "turnover") if c in sector_ff_df.columns]],
                on="sector_code",
                how="left",
                suffixes=("", "_ff"),
            )
            if "turnover_ff" in sector.columns:
                sector["turnover"] = sector["turnover"].fillna(sector["turnover_ff"])
        if market_turnover > 0 and "turnover" in sector.columns:
            sector["turnover_pct"] = sector["turnover"] / market_turnover

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO market_daily(trade_date, turnover, active_buy, active_sell, net_active, stock_count, snapshot_time)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trade_date) DO UPDATE SET
                    turnover=excluded.turnover, active_buy=excluded.active_buy,
                    active_sell=excluded.active_sell, net_active=excluded.net_active,
                    stock_count=excluded.stock_count, snapshot_time=excluded.snapshot_time
                """,
                (
                    trade_date,
                    float(m.get("turnover") or 0),
                    m.get("active_buy"),
                    m.get("active_sell"),
                    m.get("net_active"),
                    int(m.get("stock_count") or len(stock_df)),
                    snapshot_time,
                ),
            )
            for _, row in sector.iterrows():
                conn.execute(
                    """
                    INSERT INTO sector_daily(trade_date, sector_code, sector_name, turnover, turnover_pct,
                        active_buy, active_sell, net_active, stock_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(trade_date, sector_code) DO UPDATE SET
                        sector_name=excluded.sector_name, turnover=excluded.turnover,
                        turnover_pct=excluded.turnover_pct, active_buy=excluded.active_buy,
                        active_sell=excluded.active_sell, net_active=excluded.net_active,
                        stock_count=excluded.stock_count
                    """,
                    (
                        trade_date,
                        str(row.get("sector_code", "")),
                        str(row.get("sector_name", "")),
                        float(row.get("turnover") or 0),
                        row.get("turnover_pct"),
                        row.get("active_buy"),
                        row.get("active_sell"),
                        row.get("net_active"),
                        int(row.get("stock_count") or 0),
                    ),
                )
            for _, row in stock_df.iterrows():
                conn.execute(
                    """
                    INSERT INTO stock_daily(trade_date, stock_code, stock_name, sector_code, sector_name,
                        turnover, active_buy, active_sell, net_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(trade_date, stock_code) DO UPDATE SET
                        stock_name=excluded.stock_name, sector_code=excluded.sector_code,
                        sector_name=excluded.sector_name, turnover=excluded.turnover,
                        active_buy=excluded.active_buy, active_sell=excluded.active_sell,
                        net_active=excluded.net_active
                    """,
                    (
                        trade_date,
                        str(row.get("stock_code", "")),
                        str(row.get("stock_name", "")),
                        row.get("sector_code"),
                        row.get("sector_name"),
                        row.get("turnover"),
                        row.get("active_buy"),
                        row.get("active_sell"),
                        row.get("net_active"),
                    ),
                )
            if etf_df is not None and not etf_df.empty:
                for _, row in etf_df.iterrows():
                    pct = (float(row.get("turnover") or 0) / market_turnover) if market_turnover else None
                    conn.execute(
                        """
                        INSERT INTO etf_daily(trade_date, etf_code, etf_name, exchange, turnover, turnover_pct)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(trade_date, etf_code) DO UPDATE SET
                            etf_name=excluded.etf_name, exchange=excluded.exchange,
                            turnover=excluded.turnover, turnover_pct=excluded.turnover_pct
                        """,
                        (
                            trade_date,
                            str(row.get("etf_code", "")),
                            str(row.get("etf_name", "")),
                            row.get("exchange"),
                            float(row.get("turnover") or 0),
                            pct,
                        ),
                    )
            conn.commit()

    def upsert_stock_daily_rows(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        with self._connect() as conn:
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO stock_daily(trade_date, stock_code, stock_name, sector_code, sector_name,
                        turnover, active_buy, active_sell, net_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(trade_date, stock_code) DO UPDATE SET
                        stock_name=COALESCE(excluded.stock_name, stock_daily.stock_name),
                        sector_code=COALESCE(excluded.sector_code, stock_daily.sector_code),
                        sector_name=COALESCE(excluded.sector_name, stock_daily.sector_name),
                        turnover=COALESCE(excluded.turnover, stock_daily.turnover),
                        active_buy=COALESCE(excluded.active_buy, stock_daily.active_buy),
                        active_sell=COALESCE(excluded.active_sell, stock_daily.active_sell),
                        net_active=COALESCE(excluded.net_active, stock_daily.net_active)
                    """,
                    (
                        row["trade_date"],
                        row["stock_code"],
                        row.get("stock_name"),
                        row.get("sector_code"),
                        row.get("sector_name"),
                        row.get("turnover"),
                        row.get("active_buy"),
                        row.get("active_sell"),
                        row.get("net_active"),
                    ),
                )
            conn.commit()
        self.rebuild_aggregates_for_dates({r["trade_date"] for r in rows})

    def rebuild_aggregates_for_dates(self, dates: set[str]) -> None:
        for trade_date in sorted(dates):
            with self._connect() as conn:
                stocks = pd.read_sql_query(
                    "SELECT * FROM stock_daily WHERE trade_date = ?",
                    conn,
                    params=(trade_date,),
                )
            if stocks.empty:
                continue
            market_turnover = float(stocks["turnover"].fillna(0).sum())
            market = {
                "turnover": market_turnover,
                "active_buy": float(stocks["active_buy"].fillna(0).sum()) if "active_buy" in stocks else None,
                "active_sell": float(stocks["active_sell"].fillna(0).sum()) if "active_sell" in stocks else None,
                "net_active": float(stocks["net_active"].fillna(0).sum()) if "net_active" in stocks else None,
                "stock_count": len(stocks),
            }
            sector = (
                stocks.dropna(subset=["sector_code"])
                .groupby(["sector_code", "sector_name"], dropna=False)
                .agg(
                    turnover=("turnover", "sum"),
                    active_buy=("active_buy", "sum"),
                    active_sell=("active_sell", "sum"),
                    net_active=("net_active", "sum"),
                    stock_count=("stock_code", "count"),
                )
                .reset_index()
            )
            if market_turnover > 0:
                sector["turnover_pct"] = sector["turnover"] / market_turnover
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO market_daily(trade_date, turnover, active_buy, active_sell, net_active, stock_count, snapshot_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(trade_date) DO UPDATE SET
                        turnover=excluded.turnover, active_buy=excluded.active_buy,
                        active_sell=excluded.active_sell, net_active=excluded.net_active,
                        stock_count=excluded.stock_count, snapshot_time=excluded.snapshot_time
                    """,
                    (
                        trade_date,
                        market["turnover"],
                        market["active_buy"],
                        market["active_sell"],
                        market["net_active"],
                        market["stock_count"],
                        datetime.now(CST).isoformat(),
                    ),
                )
                for _, row in sector.iterrows():
                    conn.execute(
                        """
                        INSERT INTO sector_daily(trade_date, sector_code, sector_name, turnover, turnover_pct,
                            active_buy, active_sell, net_active, stock_count)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(trade_date, sector_code) DO UPDATE SET
                            sector_name=excluded.sector_name, turnover=excluded.turnover,
                            turnover_pct=excluded.turnover_pct, active_buy=excluded.active_buy,
                            active_sell=excluded.active_sell, net_active=excluded.net_active,
                            stock_count=excluded.stock_count
                        """,
                        (
                            trade_date,
                            str(row["sector_code"]),
                            str(row["sector_name"]),
                            float(row["turnover"] or 0),
                            row.get("turnover_pct"),
                            row.get("active_buy"),
                            row.get("active_sell"),
                            row.get("net_active"),
                            int(row["stock_count"]),
                        ),
                    )
                conn.commit()

    def get_market_series(self, days: int = 5) -> dict[str, list[dict[str, Any]]]:
        trade_dates = self.list_trading_days(days)
        if not trade_dates:
            return {"trade_dates": [], "turnover_series": [], "active_buy_series": [], "active_sell_series": []}
        placeholders = ",".join("?" * len(trade_dates))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM market_daily WHERE trade_date IN ({placeholders}) ORDER BY trade_date",
                trade_dates,
            ).fetchall()
        return {
            "trade_dates": trade_dates,
            "turnover_series": [{"trade_date": r["trade_date"], "value": r["turnover"]} for r in rows],
            "active_buy_series": [{"trade_date": r["trade_date"], "value": r["active_buy"] or 0} for r in rows],
            "active_sell_series": [{"trade_date": r["trade_date"], "value": r["active_sell"] or 0} for r in rows],
        }

    def get_sector_table(self, days: int = 5, sort: str = "pct_desc") -> dict[str, Any]:
        trade_dates = self.list_trading_days(days)
        if not trade_dates:
            return {"trade_dates": [], "rows": []}
        latest = trade_dates[-1]
        placeholders = ",".join("?" * len(trade_dates))
        with self._connect() as conn:
            df = pd.read_sql_query(
                f"""
                SELECT trade_date, sector_code, sector_name, turnover, turnover_pct
                FROM sector_daily WHERE trade_date IN ({placeholders})
                """,
                conn,
                params=trade_dates,
            )
        if df.empty:
            return {"trade_dates": trade_dates, "rows": []}
        sectors = df.groupby(["sector_code", "sector_name"])
        rows_out: list[dict[str, Any]] = []
        for (code, name), grp in sectors:
            cells = []
            for d in trade_dates:
                sub = grp[grp["trade_date"] == d]
                if len(sub):
                    r = sub.iloc[0]
                    cells.append({"trade_date": d, "turnover": float(r["turnover"]), "turnover_pct": float(r["turnover_pct"] or 0)})
                else:
                    cells.append({"trade_date": d, "turnover": 0, "turnover_pct": 0})
            latest_pct = next((c["turnover_pct"] for c in cells if c["trade_date"] == latest), 0)
            rows_out.append({"sector_code": code, "sector_name": name, "cells": cells, "_sort_pct": latest_pct, "_sort_turnover": cells[-1]["turnover"]})
        if sort == "pct_asc":
            rows_out.sort(key=lambda x: x["_sort_pct"])
        elif sort == "amount_desc":
            rows_out.sort(key=lambda x: x["_sort_turnover"], reverse=True)
        elif sort == "name_asc":
            rows_out.sort(key=lambda x: x["sector_name"])
        else:
            rows_out.sort(key=lambda x: x["_sort_pct"], reverse=True)
        for r in rows_out:
            r.pop("_sort_pct", None)
            r.pop("_sort_turnover", None)
        return {"trade_dates": trade_dates, "rows": rows_out}

    def get_sector_charts(self, days: int = 5) -> list[dict[str, Any]]:
        trade_dates = self.list_trading_days(days)
        if not trade_dates:
            return []
        placeholders = ",".join("?" * len(trade_dates))
        with self._connect() as conn:
            df = pd.read_sql_query(
                f"""
                SELECT * FROM sector_daily WHERE trade_date IN ({placeholders})
                ORDER BY sector_code, trade_date
                """,
                conn,
                params=trade_dates,
            )
        out = []
        for (code, name), grp in df.groupby(["sector_code", "sector_name"]):
            g = grp.set_index("trade_date").reindex(trade_dates)
            out.append({
                "sector_code": code,
                "sector_name": name,
                "turnover_series": [{"trade_date": d, "value": float(g.loc[d, "turnover"] or 0) if d in g.index else 0} for d in trade_dates],
                "active_buy_series": [{"trade_date": d, "value": float(g.loc[d, "active_buy"] or 0) if d in g.index else 0} for d in trade_dates],
                "active_sell_series": [{"trade_date": d, "value": float(g.loc[d, "active_sell"] or 0) if d in g.index else 0} for d in trade_dates],
            })
        return out

    def get_sector_stocks(self, sector_code: str, days: int = 5) -> dict[str, Any]:
        trade_dates = self.list_trading_days(days)
        placeholders = ",".join("?" * len(trade_dates))
        with self._connect() as conn:
            meta = conn.execute(
                "SELECT sector_name FROM sector_daily WHERE sector_code=? LIMIT 1",
                (sector_code,),
            ).fetchone()
            df = pd.read_sql_query(
                f"""
                SELECT * FROM stock_daily
                WHERE sector_code=? AND trade_date IN ({placeholders})
                ORDER BY stock_code, trade_date
                """,
                conn,
                params=(sector_code, *trade_dates),
            )
        sector_name = meta["sector_name"] if meta else sector_code
        stocks = []
        if not df.empty:
            for (code, name), grp in df.groupby(["stock_code", "stock_name"]):
                g = grp.set_index("trade_date")
                stocks.append({
                    "stock_code": code,
                    "stock_name": name,
                    "turnover_series": [{"trade_date": d, "value": float(g.loc[d, "turnover"] or 0) if d in g.index else 0} for d in trade_dates],
                    "active_buy_series": [{"trade_date": d, "value": float(g.loc[d, "active_buy"] or 0) if d in g.index else 0} for d in trade_dates],
                    "active_sell_series": [{"trade_date": d, "value": float(g.loc[d, "active_sell"] or 0) if d in g.index else 0} for d in trade_dates],
                })
            latest = trade_dates[-1]
            stocks.sort(key=lambda s: s["turnover_series"][-1]["value"], reverse=True)
        return {"sector_code": sector_code, "sector_name": sector_name, "trade_dates": trade_dates, "stocks": stocks}

    def get_etf_table(self, days: int = 5, sort: str = "pct_desc", page: int = 1, page_size: int = 50, q: str = "") -> dict[str, Any]:
        trade_dates = self.list_trading_days(days)
        if not trade_dates:
            return {"trade_dates": [], "meta": {"total": 0, "page": page, "page_size": page_size}, "rows": []}
        latest = trade_dates[-1]
        placeholders = ",".join("?" * len(trade_dates))
        with self._connect() as conn:
            df = pd.read_sql_query(
                f"SELECT * FROM etf_daily WHERE trade_date IN ({placeholders})",
                conn,
                params=trade_dates,
            )
        if df.empty:
            return {"trade_dates": trade_dates, "meta": {"total": 0, "page": page, "page_size": page_size}, "rows": []}
        if q:
            q = q.strip().lower()
            df = df[df["etf_code"].str.lower().str.contains(q) | df["etf_name"].str.lower().str.contains(q)]
        rows_out = []
        for (code, name), grp in df.groupby(["etf_code", "etf_name"]):
            cells = []
            for d in trade_dates:
                sub = grp[grp["trade_date"] == d]
                if len(sub):
                    r = sub.iloc[0]
                    cells.append({"trade_date": d, "turnover": float(r["turnover"]), "turnover_pct": float(r["turnover_pct"] or 0)})
                else:
                    cells.append({"trade_date": d, "turnover": 0, "turnover_pct": 0})
            latest_pct = next((c["turnover_pct"] for c in cells if c["trade_date"] == latest), 0)
            rows_out.append({"etf_code": code, "etf_name": name, "cells": cells, "_sort_pct": latest_pct, "_sort_turnover": cells[-1]["turnover"]})
        if sort == "pct_asc":
            rows_out.sort(key=lambda x: x["_sort_pct"])
        elif sort == "name_asc":
            rows_out.sort(key=lambda x: x["etf_name"])
        else:
            rows_out.sort(key=lambda x: x["_sort_pct"], reverse=True)
        total = len(rows_out)
        start = (page - 1) * page_size
        page_rows = rows_out[start : start + page_size]
        for r in page_rows:
            r.pop("_sort_pct", None)
            r.pop("_sort_turnover", None)
        return {"trade_dates": trade_dates, "meta": {"total": total, "page": page, "page_size": page_size}, "rows": page_rows}

    def get_etf_charts(self, days: int = 5, top: int = 50, q: str = "") -> list[dict[str, Any]]:
        table = self.get_etf_table(days=days, sort="pct_desc", page=1, page_size=max(top, 500), q=q)
        trade_dates = table["trade_dates"]
        out = []
        for row in table["rows"][:top]:
            out.append({
                "etf_code": row["etf_code"],
                "etf_name": row["etf_name"],
                "turnover_series": [{"trade_date": c["trade_date"], "value": c["turnover"]} for c in row["cells"]],
            })
        return out

    def get_data_calendar(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            dates = conn.execute(
                """
                SELECT DISTINCT trade_date FROM (
                    SELECT trade_date FROM market_daily
                    UNION SELECT trade_date FROM stock_daily
                    UNION SELECT trade_date FROM etf_daily
                ) ORDER BY trade_date DESC
                """
            ).fetchall()
        result = []
        for r in dates:
            d = r["trade_date"]
            with self._connect() as conn:
                m = conn.execute("SELECT 1 FROM market_daily WHERE trade_date=?", (d,)).fetchone()
                sc = conn.execute("SELECT COUNT(*) c FROM sector_daily WHERE trade_date=?", (d,)).fetchone()["c"]
                st = conn.execute("SELECT COUNT(*) c FROM stock_daily WHERE trade_date=?", (d,)).fetchone()["c"]
                et = conn.execute("SELECT COUNT(*) c FROM etf_daily WHERE trade_date=?", (d,)).fetchone()["c"]
                snap = conn.execute("SELECT snapshot_time FROM market_daily WHERE trade_date=?", (d,)).fetchone()
            completeness = "full" if m and sc > 0 and st > 0 and et > 0 else ("partial" if m and st > 0 else "missing")
            result.append({
                "trade_date": d,
                "completeness": completeness,
                "market": bool(m),
                "sector_count": sc,
                "stock_count": st,
                "etf_count": et,
                "last_updated": snap["snapshot_time"] if snap else None,
            })
        return result

    def create_job(self, trade_date: str, trigger_type: str) -> str:
        job_id = str(uuid.uuid4())
        now = datetime.now(CST).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO fetch_jobs(job_id, trade_date, trigger_type, status, created_at)
                VALUES (?, ?, ?, 'pending', ?)
                """,
                (job_id, trade_date, trigger_type, now),
            )
            conn.commit()
        return job_id

    def update_job(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._connect() as conn:
            conn.execute(f"UPDATE fetch_jobs SET {cols} WHERE job_id=?", (*fields.values(), job_id))
            conn.commit()

    def list_jobs(self, limit: int = 20, status: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM fetch_jobs WHERE status=? ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM fetch_jobs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM fetch_jobs WHERE job_id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def export_zip(self, trade_date: str) -> bytes:
        with self._connect() as conn:
            tables = {
                "market_daily.csv": pd.read_sql_query("SELECT * FROM market_daily WHERE trade_date=?", conn, params=(trade_date,)),
                "sector_daily.csv": pd.read_sql_query("SELECT * FROM sector_daily WHERE trade_date=?", conn, params=(trade_date,)),
                "stock_daily.csv": pd.read_sql_query("SELECT * FROM stock_daily WHERE trade_date=?", conn, params=(trade_date,)),
                "etf_daily.csv": pd.read_sql_query("SELECT * FROM etf_daily WHERE trade_date=?", conn, params=(trade_date,)),
            }
        buf = io.BytesIO()
        meta = {"trade_date": trade_date, "generated_at": datetime.now(CST).isoformat()}
        for name, df in tables.items():
            meta[name.replace(".csv", "_rows")] = len(df)
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
            for name, df in tables.items():
                zf.writestr(name, df.to_csv(index=False))
        return buf.getvalue()
