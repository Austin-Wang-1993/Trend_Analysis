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
    "mapping_refresh_enabled": "true",
    "mapping_refresh_time": "02:00",
}

ATOMIC_FLOW_AMOUNT_FIELDS = (
    "zmbtdcje",
    "zmbddcje",
    "zmbzdcje",
    "zmbxdcje",
    "zmstdcje",
    "zmsddcje",
    "zmszdcje",
    "zmsxdcje",
)
STOCK_FLOW_METRICS = ("turnover", "active_buy", "active_sell", "net_active", *ATOMIC_FLOW_AMOUNT_FIELDS)

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
CREATE TABLE IF NOT EXISTS concept_stock_map (
    concept_type INTEGER NOT NULL,
    sector_code TEXT NOT NULL,
    sector_name TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    PRIMARY KEY (concept_type, sector_code, stock_code)
);
CREATE INDEX IF NOT EXISTS idx_concept_map_stock ON concept_stock_map(concept_type, stock_code);
CREATE INDEX IF NOT EXISTS idx_concept_map_sector ON concept_stock_map(concept_type, sector_code);
CREATE TABLE IF NOT EXISTS concept_sector_daily (
    trade_date TEXT NOT NULL,
    concept_type INTEGER NOT NULL,
    sector_code TEXT NOT NULL,
    sector_name TEXT NOT NULL,
    turnover REAL NOT NULL DEFAULT 0,
    turnover_pct REAL,
    active_buy REAL,
    active_sell REAL,
    net_active REAL,
    zmbtdcje REAL,
    zmbddcje REAL,
    zmbzdcje REAL,
    zmbxdcje REAL,
    zmstdcje REAL,
    zmsddcje REAL,
    zmszdcje REAL,
    zmsxdcje REAL,
    stock_count INTEGER,
    PRIMARY KEY (trade_date, concept_type, sector_code)
);
CREATE INDEX IF NOT EXISTS idx_concept_sector_date ON concept_sector_daily(trade_date, concept_type);
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
            self._migrate_schema(conn)
            for key, value in DEFAULT_SETTINGS.items():
                conn.execute(
                    "INSERT OR IGNORE INTO app_settings(key, value) VALUES (?, ?)",
                    (key, value),
                )
            conn.commit()

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(fetch_jobs)").fetchall()}
        if "end_date" not in cols:
            conn.execute("ALTER TABLE fetch_jobs ADD COLUMN end_date TEXT")
        stock_cols = {row[1] for row in conn.execute("PRAGMA table_info(stock_daily)").fetchall()}
        for col in ATOMIC_FLOW_AMOUNT_FIELDS:
            if col not in stock_cols:
                conn.execute(f"ALTER TABLE stock_daily ADD COLUMN {col} REAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS concept_stock_map (
                concept_type INTEGER NOT NULL,
                sector_code TEXT NOT NULL,
                sector_name TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                PRIMARY KEY (concept_type, sector_code, stock_code)
            );
            CREATE INDEX IF NOT EXISTS idx_concept_map_stock ON concept_stock_map(concept_type, stock_code);
            CREATE INDEX IF NOT EXISTS idx_concept_map_sector ON concept_stock_map(concept_type, sector_code);
            CREATE TABLE IF NOT EXISTS concept_sector_daily (
                trade_date TEXT NOT NULL,
                concept_type INTEGER NOT NULL,
                sector_code TEXT NOT NULL,
                sector_name TEXT NOT NULL,
                turnover REAL NOT NULL DEFAULT 0,
                turnover_pct REAL,
                active_buy REAL,
                active_sell REAL,
                net_active REAL,
                zmbtdcje REAL,
                zmbddcje REAL,
                zmbzdcje REAL,
                zmbxdcje REAL,
                zmstdcje REAL,
                zmsddcje REAL,
                zmszdcje REAL,
                zmsxdcje REAL,
                stock_count INTEGER,
                PRIMARY KEY (trade_date, concept_type, sector_code)
            );
            CREATE INDEX IF NOT EXISTS idx_concept_sector_date ON concept_sector_daily(trade_date, concept_type);
            """
        )

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

    @staticmethod
    def _prune_sector_daily(conn: sqlite3.Connection, trade_date: str, kept_codes: set[str]) -> int:
        """删除当日不在 kept_codes 中的 sector_daily 行（清理 L1→L2 迁移残留等）。"""
        if not kept_codes:
            cur = conn.execute("DELETE FROM sector_daily WHERE trade_date=?", (trade_date,))
            return cur.rowcount
        placeholders = ",".join("?" * len(kept_codes))
        cur = conn.execute(
            f"DELETE FROM sector_daily WHERE trade_date=? AND sector_code NOT IN ({placeholders})",
            (trade_date, *sorted(kept_codes)),
        )
        return cur.rowcount

    @staticmethod
    def _prune_concept_sector_daily(
        conn: sqlite3.Connection, trade_date: str, concept_type: int, kept_codes: set[str]
    ) -> int:
        if not kept_codes:
            cur = conn.execute(
                "DELETE FROM concept_sector_daily WHERE trade_date=? AND concept_type=?",
                (trade_date, concept_type),
            )
            return cur.rowcount
        placeholders = ",".join("?" * len(kept_codes))
        cur = conn.execute(
            f"""DELETE FROM concept_sector_daily
                WHERE trade_date=? AND concept_type=? AND sector_code NOT IN ({placeholders})""",
            (trade_date, concept_type, *sorted(kept_codes)),
        )
        return cur.rowcount

    def replace_concept_stock_map(self, concept_type: int, mapping_df: pd.DataFrame) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM concept_stock_map WHERE concept_type=?", (concept_type,))
            for _, row in mapping_df.iterrows():
                conn.execute(
                    """
                    INSERT OR REPLACE INTO concept_stock_map(concept_type, sector_code, sector_name, stock_code)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        concept_type,
                        str(row.get("sector_code", "")),
                        str(row.get("sector_name", "")),
                        str(row.get("stock_code", "")),
                    ),
                )
            conn.commit()

    @staticmethod
    def _stock_upsert_params(row: pd.Series | dict[str, Any]) -> tuple[Any, ...]:
        data = row.to_dict() if isinstance(row, pd.Series) else dict(row)
        return (
            data.get("trade_date"),
            str(data.get("stock_code", "")),
            data.get("stock_name"),
            data.get("sector_code"),
            data.get("sector_name"),
            data.get("turnover"),
            data.get("active_buy"),
            data.get("active_sell"),
            data.get("net_active"),
            *(data.get(col) for col in ATOMIC_FLOW_AMOUNT_FIELDS),
        )

    def _upsert_concept_sector_rows(
        self,
        conn: sqlite3.Connection,
        trade_date: str,
        concept_type: int,
        sector_df: pd.DataFrame,
        market_turnover: float,
    ) -> None:
        if sector_df.empty:
            return
        df = sector_df.copy()
        if market_turnover > 0 and "turnover" in df.columns:
            df["turnover_pct"] = df["turnover"] / market_turnover
        for _, row in df.iterrows():
            conn.execute(
                """
                INSERT INTO concept_sector_daily(
                    trade_date, concept_type, sector_code, sector_name, turnover, turnover_pct,
                    active_buy, active_sell, net_active,
                    zmbtdcje, zmbddcje, zmbzdcje, zmbxdcje,
                    zmstdcje, zmsddcje, zmszdcje, zmsxdcje,
                    stock_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trade_date, concept_type, sector_code) DO UPDATE SET
                    sector_name=excluded.sector_name, turnover=excluded.turnover,
                    turnover_pct=excluded.turnover_pct, active_buy=excluded.active_buy,
                    active_sell=excluded.active_sell, net_active=excluded.net_active,
                    zmbtdcje=excluded.zmbtdcje, zmbddcje=excluded.zmbddcje,
                    zmbzdcje=excluded.zmbzdcje, zmbxdcje=excluded.zmbxdcje,
                    zmstdcje=excluded.zmstdcje, zmsddcje=excluded.zmsddcje,
                    zmszdcje=excluded.zmszdcje, zmsxdcje=excluded.zmsxdcje,
                    stock_count=excluded.stock_count
                """,
                (
                    trade_date,
                    concept_type,
                    str(row.get("sector_code", "")),
                    str(row.get("sector_name", "")),
                    float(row.get("turnover") or 0),
                    row.get("turnover_pct"),
                    row.get("active_buy"),
                    row.get("active_sell"),
                    row.get("net_active"),
                    row.get("zmbtdcje"),
                    row.get("zmbddcje"),
                    row.get("zmbzdcje"),
                    row.get("zmbxdcje"),
                    row.get("zmstdcje"),
                    row.get("zmsddcje"),
                    row.get("zmszdcje"),
                    row.get("zmsxdcje"),
                    int(row.get("stock_count") or 0),
                ),
            )
        kept = {
            str(row.get("sector_code", ""))
            for _, row in df.iterrows()
            if str(row.get("sector_code", "")).strip()
        }
        self._prune_concept_sector_daily(conn, trade_date, concept_type, kept)

    def rebuild_concept_aggregates_for_date(self, trade_date: str) -> None:
        from concept_common import aggregate_concept_sectors, sectors_for_concept_type
        from by_common import TYPE2_BOARD, TYPE2_HOT

        with self._connect() as conn:
            stocks = pd.read_sql_query(
                "SELECT * FROM stock_daily WHERE trade_date = ?",
                conn,
                params=(trade_date,),
            )
            tree_path = self.db_path.parent / "cache" / "sector_tree.json"
            if tree_path.exists():
                import json

                tree_df = pd.DataFrame(json.loads(tree_path.read_text(encoding="utf-8")))
            else:
                tree_df = pd.DataFrame()
        if stocks.empty:
            return
        market_turnover = float(stocks["turnover"].fillna(0).sum())
        for concept_type in (TYPE2_HOT, TYPE2_BOARD):
            with self._connect() as conn:
                mapping = pd.read_sql_query(
                    "SELECT sector_code, sector_name, stock_code FROM concept_stock_map WHERE concept_type=?",
                    conn,
                    params=(concept_type,),
                )
            if mapping.empty:
                continue
            if not tree_df.empty:
                catalog = sectors_for_concept_type(tree_df, concept_type)
            else:
                catalog = mapping[["sector_code", "sector_name"]].drop_duplicates()
                catalog = catalog.rename(columns={"sector_code": "code", "sector_name": "name"})
            sector_df = aggregate_concept_sectors(stocks, mapping, catalog)
            with self._connect() as conn:
                self._upsert_concept_sector_rows(conn, trade_date, concept_type, sector_df, market_turnover)
                conn.commit()

    def upsert_snapshot(
        self,
        trade_date: str,
        stock_df: pd.DataFrame,
        sector_df: pd.DataFrame,
        sector_ff_df: pd.DataFrame | None,
        market_row: dict[str, Any] | None,
        etf_df: pd.DataFrame | None,
        snapshot_time: str,
        concept_sector_dfs: dict[int, pd.DataFrame] | None = None,
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
            kept_sectors = {
                str(row.get("sector_code", ""))
                for _, row in sector.iterrows()
                if str(row.get("sector_code", "")).strip()
            }
            self._prune_sector_daily(conn, trade_date, kept_sectors)
            for _, row in stock_df.iterrows():
                conn.execute(
                    """
                    INSERT INTO stock_daily(trade_date, stock_code, stock_name, sector_code, sector_name,
                        turnover, active_buy, active_sell, net_active,
                        zmbtdcje, zmbddcje, zmbzdcje, zmbxdcje,
                        zmstdcje, zmsddcje, zmszdcje, zmsxdcje)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(trade_date, stock_code) DO UPDATE SET
                        stock_name=excluded.stock_name, sector_code=excluded.sector_code,
                        sector_name=excluded.sector_name, turnover=excluded.turnover,
                        active_buy=excluded.active_buy, active_sell=excluded.active_sell,
                        net_active=excluded.net_active,
                        zmbtdcje=excluded.zmbtdcje, zmbddcje=excluded.zmbddcje,
                        zmbzdcje=excluded.zmbzdcje, zmbxdcje=excluded.zmbxdcje,
                        zmstdcje=excluded.zmstdcje, zmsddcje=excluded.zmsddcje,
                        zmszdcje=excluded.zmszdcje, zmsxdcje=excluded.zmsxdcje
                    """,
                    self._stock_upsert_params({**row.to_dict(), "trade_date": trade_date}),
                )
            if concept_sector_dfs:
                for concept_type, cdf in concept_sector_dfs.items():
                    self._upsert_concept_sector_rows(conn, trade_date, concept_type, cdf, market_turnover)
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
                        turnover, active_buy, active_sell, net_active,
                        zmbtdcje, zmbddcje, zmbzdcje, zmbxdcje,
                        zmstdcje, zmsddcje, zmszdcje, zmsxdcje)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(trade_date, stock_code) DO UPDATE SET
                        stock_name=COALESCE(excluded.stock_name, stock_daily.stock_name),
                        sector_code=COALESCE(excluded.sector_code, stock_daily.sector_code),
                        sector_name=COALESCE(excluded.sector_name, stock_daily.sector_name),
                        turnover=COALESCE(excluded.turnover, stock_daily.turnover),
                        active_buy=COALESCE(excluded.active_buy, stock_daily.active_buy),
                        active_sell=COALESCE(excluded.active_sell, stock_daily.active_sell),
                        net_active=COALESCE(excluded.net_active, stock_daily.net_active),
                        zmbtdcje=COALESCE(excluded.zmbtdcje, stock_daily.zmbtdcje),
                        zmbddcje=COALESCE(excluded.zmbddcje, stock_daily.zmbddcje),
                        zmbzdcje=COALESCE(excluded.zmbzdcje, stock_daily.zmbzdcje),
                        zmbxdcje=COALESCE(excluded.zmbxdcje, stock_daily.zmbxdcje),
                        zmstdcje=COALESCE(excluded.zmstdcje, stock_daily.zmstdcje),
                        zmsddcje=COALESCE(excluded.zmsddcje, stock_daily.zmsddcje),
                        zmszdcje=COALESCE(excluded.zmszdcje, stock_daily.zmszdcje),
                        zmsxdcje=COALESCE(excluded.zmsxdcje, stock_daily.zmsxdcje)
                    """,
                    self._stock_upsert_params(row),
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
                kept_sectors = set(sector["sector_code"].astype(str).str.strip()) - {""}
                self._prune_sector_daily(conn, trade_date, kept_sectors)
                self.rebuild_concept_aggregates_for_date(trade_date)
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

    def get_sector_table(self, days: int = 5, sort: str = "turnover_pct_desc", kind: str = "sw_l2") -> dict[str, Any]:
        if kind == "sw_l2":
            return self._get_rank_table_from_sql(
                days,
                sort,
                table="sector_daily",
                extra_where="",
                extra_params=(),
            )
        from sector_config import concept_type_for_kind

        concept_type = concept_type_for_kind(kind)
        return self._get_rank_table_from_sql(
            days,
            sort,
            table="concept_sector_daily",
            extra_where=" AND concept_type=?",
            extra_params=(concept_type,),
        )

    def _get_rank_table_from_sql(
        self,
        days: int,
        sort: str,
        *,
        table: str,
        extra_where: str,
        extra_params: tuple[Any, ...],
    ) -> dict[str, Any]:
        trade_dates = self.list_trading_days(days)
        kind_label = "sw_l2"
        if table == "concept_sector_daily" and extra_params:
            kind_label = "hot" if extra_params[0] == 2 else "board"
        if not trade_dates:
            return {"days": days, "sort": sort, "kind": kind_label, "trade_dates": [], "columns": []}

        sort = self._normalize_sector_table_sort(sort)
        placeholders = ",".join("?" * len(trade_dates))
        with self._connect() as conn:
            sector_df = pd.read_sql_query(
                f"""
                SELECT trade_date, sector_code, sector_name, turnover, turnover_pct,
                       active_buy, active_sell
                FROM {table} WHERE trade_date IN ({placeholders}){extra_where}
                """,
                conn,
                params=(*trade_dates, *extra_params),
            )
            market_df = pd.read_sql_query(
                f"""
                SELECT trade_date, turnover, active_buy, active_sell
                FROM market_daily WHERE trade_date IN ({placeholders})
                """,
                conn,
                params=trade_dates,
            )

        market_by_date = {
            str(r["trade_date"]): {
                "turnover": float(r["turnover"] or 0),
                "active_buy": float(r["active_buy"] or 0) if r["active_buy"] is not None else 0.0,
                "active_sell": float(r["active_sell"] or 0) if r["active_sell"] is not None else 0.0,
            }
            for _, r in market_df.iterrows()
        }

        columns: list[dict[str, Any]] = []
        dates_new_to_old = list(reversed(trade_dates))
        for d in dates_new_to_old:
            day_sectors: list[dict[str, Any]] = []
            sub = sector_df[sector_df["trade_date"] == d]
            mkt = market_by_date.get(d, {"turnover": 0, "active_buy": 0, "active_sell": 0})
            for _, r in sub.iterrows():
                buy = float(r["active_buy"]) if pd.notna(r["active_buy"]) else None
                sell = float(r["active_sell"]) if pd.notna(r["active_sell"]) else None
                net = (buy - sell) if buy is not None and sell is not None else None
                market_net = mkt["active_buy"] - mkt["active_sell"]
                day_sectors.append(
                    {
                        "sector_code": str(r["sector_code"]),
                        "sector_name": str(r["sector_name"]),
                        "turnover": float(r["turnover"] or 0),
                        "turnover_pct": float(r["turnover_pct"] or 0),
                        "active_buy": buy,
                        "active_sell": sell,
                        "buy_pct": (buy / mkt["active_buy"]) if buy is not None and mkt["active_buy"] > 0 else None,
                        "sell_pct": (sell / mkt["active_sell"]) if sell is not None and mkt["active_sell"] > 0 else None,
                        "net_value": net,
                        "net_pct": (net / market_net) if net is not None and market_net != 0 else None,
                    }
                )
            self._sort_sector_table_day(day_sectors, sort)
            for rank, sec in enumerate(day_sectors, start=1):
                sec["rank"] = rank
            columns.append({"trade_date": d, "sectors": day_sectors})

        kind_label = "sw_l2"
        if table == "concept_sector_daily" and extra_params:
            kind_label = "hot" if extra_params[0] == 2 else "board"
        return {
            "days": days,
            "sort": sort,
            "kind": kind_label,
            "trade_dates": dates_new_to_old,
            "columns": columns,
        }

    @staticmethod
    def _normalize_sector_table_sort(sort: str) -> str:
        aliases = {
            "pct_desc": "turnover_pct_desc",
            "pct_asc": "turnover_pct_asc",
            "amount_desc": "turnover_pct_desc",
            "name_asc": "turnover_pct_desc",
        }
        sort = aliases.get(sort, sort)
        allowed = {
            "turnover_pct_desc",
            "turnover_pct_asc",
            "buy_pct_desc",
            "buy_pct_asc",
            "sell_pct_desc",
            "sell_pct_asc",
            "net_desc",
            "net_asc",
        }
        return sort if sort in allowed else "turnover_pct_desc"

    @staticmethod
    def _normalize_rank_table_sort(sort: str) -> str:
        return HistoryStore._normalize_sector_table_sort(sort)

    @staticmethod
    def _sort_rank_cards(items: list[dict[str, Any]], sort: str, name_key: str) -> None:
        key_map = {
            "turnover_pct_desc": ("turnover_pct", True),
            "turnover_pct_asc": ("turnover_pct", False),
            "buy_pct_desc": ("buy_pct", True),
            "buy_pct_asc": ("buy_pct", False),
            "sell_pct_desc": ("sell_pct", True),
            "sell_pct_asc": ("sell_pct", False),
            "net_desc": ("net_value", True),
            "net_asc": ("net_value", False),
        }
        field, desc = key_map.get(sort, ("turnover_pct", True))

        def sort_key(item: dict[str, Any]) -> tuple:
            v = item.get(field)
            if v is None:
                return (1, 0.0, item.get(name_key, ""))
            return (0, -v if desc else v, item.get(name_key, ""))

        items.sort(key=sort_key)

    @staticmethod
    def _sort_sector_table_day(sectors: list[dict[str, Any]], sort: str) -> None:
        HistoryStore._sort_rank_cards(sectors, sort, "sector_name")

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

    def get_sector_stocks(
        self,
        sector_code: str,
        days: int = 5,
        sort: str = "turnover_pct_desc",
        kind: str = "sw_l2",
    ) -> dict[str, Any]:
        trade_dates = self.list_trading_days(days)
        if not trade_dates:
            return {
                "sector_code": sector_code,
                "sector_name": sector_code,
                "days": days,
                "sort": sort,
                "kind": kind,
                "trade_dates": [],
                "columns": [],
            }

        sort = self._normalize_rank_table_sort(sort)
        placeholders = ",".join("?" * len(trade_dates))
        with self._connect() as conn:
            if kind in ("hot", "board"):
                from sector_config import concept_type_for_kind

                concept_type = concept_type_for_kind(kind)
                meta = conn.execute(
                    """
                    SELECT sector_name FROM concept_stock_map
                    WHERE concept_type=? AND sector_code=? LIMIT 1
                    """,
                    (concept_type, sector_code),
                ).fetchone()
                if not meta:
                    meta = conn.execute(
                        """
                        SELECT sector_name FROM concept_sector_daily
                        WHERE concept_type=? AND sector_code=? LIMIT 1
                        """,
                        (concept_type, sector_code),
                    ).fetchone()
                df = pd.read_sql_query(
                    f"""
                    SELECT s.* FROM stock_daily s
                    INNER JOIN concept_stock_map m
                      ON m.stock_code = s.stock_code AND m.concept_type = ? AND m.sector_code = ?
                    WHERE s.trade_date IN ({placeholders})
                    ORDER BY s.stock_code, s.trade_date
                    """,
                    conn,
                    params=(concept_type, sector_code, *trade_dates),
                )
            else:
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

        sector_totals_by_date: dict[str, dict[str, float]] = {}
        if not df.empty:
            for d, grp in df.groupby("trade_date"):
                buy_sum = grp["active_buy"].fillna(0).astype(float).sum()
                sell_sum = grp["active_sell"].fillna(0).astype(float).sum()
                sector_totals_by_date[str(d)] = {
                    "turnover": float(grp["turnover"].fillna(0).astype(float).sum()),
                    "active_buy": float(buy_sum),
                    "active_sell": float(sell_sum),
                    "net": float(buy_sum - sell_sum),
                }

        columns: list[dict[str, Any]] = []
        dates_new_to_old = list(reversed(trade_dates))
        for d in dates_new_to_old:
            day_stocks: list[dict[str, Any]] = []
            sub = df[df["trade_date"] == d] if not df.empty else df
            totals = sector_totals_by_date.get(
                d, {"turnover": 0.0, "active_buy": 0.0, "active_sell": 0.0, "net": 0.0}
            )
            for _, r in sub.iterrows():
                buy = float(r["active_buy"]) if pd.notna(r["active_buy"]) else None
                sell = float(r["active_sell"]) if pd.notna(r["active_sell"]) else None
                net = (buy - sell) if buy is not None and sell is not None else None
                turnover = float(r["turnover"] or 0)
                day_stocks.append(
                    {
                        "stock_code": str(r["stock_code"]),
                        "stock_name": str(r["stock_name"] or ""),
                        "turnover": turnover,
                        "turnover_pct": (turnover / totals["turnover"]) if totals["turnover"] > 0 else None,
                        "active_buy": buy,
                        "active_sell": sell,
                        "buy_pct": (buy / totals["active_buy"]) if buy is not None and totals["active_buy"] > 0 else None,
                        "sell_pct": (sell / totals["active_sell"]) if sell is not None and totals["active_sell"] > 0 else None,
                        "net_value": net,
                        "net_pct": (net / totals["net"]) if net is not None and totals["net"] != 0 else None,
                    }
                )
            self._sort_rank_cards(day_stocks, sort, "stock_code")
            for rank, stock in enumerate(day_stocks, start=1):
                stock["rank"] = rank
            columns.append({"trade_date": d, "stocks": day_stocks})

        return {
            "sector_code": sector_code,
            "sector_name": sector_name,
            "days": days,
            "sort": sort,
            "kind": kind,
            "trade_dates": dates_new_to_old,
            "columns": columns,
        }

    def get_stock_series(self, stock_code: str, days: int = 5, sector_code: str | None = None) -> dict[str, Any]:
        trade_dates = self.list_trading_days(days)
        if not trade_dates:
            return {
                "stock_code": stock_code,
                "stock_name": stock_code,
                "sector_code": sector_code,
                "sector_name": None,
                "days": days,
                "series": [],
            }

        placeholders = ",".join("?" * len(trade_dates))
        query = f"""
            SELECT * FROM stock_daily
            WHERE stock_code=? AND trade_date IN ({placeholders})
        """
        params: list[Any] = [stock_code, *trade_dates]
        if sector_code:
            query += " AND sector_code=?"
            params.append(sector_code)

        with self._connect() as conn:
            df = pd.read_sql_query(query, conn, params=params)

        if df.empty:
            return {
                "stock_code": stock_code,
                "stock_name": stock_code,
                "sector_code": sector_code,
                "sector_name": None,
                "days": days,
                "series": [],
            }

        row0 = df.iloc[0]
        stock_name = str(row0["stock_name"] or "")
        sec_code = str(row0["sector_code"] or sector_code or "")
        sector_name = None
        if sec_code:
            with self._connect() as conn:
                meta = conn.execute(
                    "SELECT sector_name FROM sector_daily WHERE sector_code=? LIMIT 1",
                    (sec_code,),
                ).fetchone()
                sector_name = meta["sector_name"] if meta else None

        g = df.set_index("trade_date")
        dates_new_to_old = list(reversed(trade_dates))
        series = []
        for d in dates_new_to_old:
            if d in g.index:
                r = g.loc[d]
                buy = float(r["active_buy"]) if pd.notna(r["active_buy"]) else 0.0
                sell = float(r["active_sell"]) if pd.notna(r["active_sell"]) else 0.0
                turnover = float(r["turnover"] or 0)
            else:
                buy = sell = turnover = 0.0
            series.append(
                {
                    "trade_date": d,
                    "turnover": turnover,
                    "active_buy": buy,
                    "active_sell": sell,
                }
            )

        return {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "sector_code": sec_code or sector_code,
            "sector_name": sector_name,
            "days": days,
            "series": series,
        }

    @staticmethod
    def _normalize_etf_table_sort(sort: str) -> str:
        aliases = {
            "pct_desc": "turnover_pct_desc",
            "pct_asc": "turnover_pct_asc",
            "amount_desc": "turnover_desc",
            "name_asc": "turnover_pct_desc",
        }
        sort = aliases.get(sort, sort)
        allowed = {
            "turnover_pct_desc",
            "turnover_pct_asc",
            "turnover_desc",
            "turnover_asc",
        }
        return sort if sort in allowed else "turnover_pct_desc"

    @staticmethod
    def _sort_etf_table_day(etfs: list[dict[str, Any]], sort: str) -> None:
        key_map = {
            "turnover_pct_desc": ("turnover_pct", True),
            "turnover_pct_asc": ("turnover_pct", False),
            "turnover_desc": ("turnover", True),
            "turnover_asc": ("turnover", False),
        }
        field, desc = key_map.get(sort, ("turnover_pct", True))

        def sort_key(item: dict[str, Any]) -> tuple:
            v = item.get(field)
            if v is None:
                return (1, 0.0, item.get("etf_name", ""), item.get("etf_code", ""))
            return (0, -v if desc else v, item.get("etf_name", ""), item.get("etf_code", ""))

        etfs.sort(key=sort_key)

    def get_etf_table(self, days: int = 5, sort: str = "turnover_pct_desc") -> dict[str, Any]:
        trade_dates = self.list_trading_days(days)
        if not trade_dates:
            return {"days": days, "sort": sort, "trade_dates": [], "columns": []}

        sort = self._normalize_etf_table_sort(sort)
        placeholders = ",".join("?" * len(trade_dates))
        with self._connect() as conn:
            df = pd.read_sql_query(
                f"SELECT * FROM etf_daily WHERE trade_date IN ({placeholders})",
                conn,
                params=trade_dates,
            )

        columns: list[dict[str, Any]] = []
        dates_new_to_old = list(reversed(trade_dates))
        for d in dates_new_to_old:
            day_etfs: list[dict[str, Any]] = []
            sub = df[df["trade_date"] == d] if not df.empty else df
            for _, r in sub.iterrows():
                day_etfs.append(
                    {
                        "etf_code": str(r["etf_code"]),
                        "etf_name": str(r["etf_name"] or ""),
                        "turnover": float(r["turnover"] or 0),
                        "turnover_pct": float(r["turnover_pct"] or 0),
                    }
                )
            self._sort_etf_table_day(day_etfs, sort)
            for rank, etf in enumerate(day_etfs, start=1):
                etf["rank"] = rank
            columns.append({"trade_date": d, "etfs": day_etfs})

        return {
            "days": days,
            "sort": sort,
            "trade_dates": dates_new_to_old,
            "columns": columns,
        }

    def get_etf_series(self, etf_code: str, days: int = 5) -> dict[str, Any]:
        trade_dates = self.list_trading_days(days)
        if not trade_dates:
            return {"etf_code": etf_code, "etf_name": etf_code, "days": days, "series": []}

        placeholders = ",".join("?" * len(trade_dates))
        with self._connect() as conn:
            df = pd.read_sql_query(
                f"""
                SELECT * FROM etf_daily
                WHERE etf_code=? AND trade_date IN ({placeholders})
                ORDER BY trade_date
                """,
                conn,
                params=(etf_code, *trade_dates),
            )

        etf_name = etf_code
        if not df.empty:
            etf_name = str(df.iloc[0]["etf_name"] or etf_code)

        g = df.set_index("trade_date") if not df.empty else df
        dates_new_to_old = list(reversed(trade_dates))
        series = []
        for d in dates_new_to_old:
            if not df.empty and d in g.index:
                r = g.loc[d]
                turnover = float(r["turnover"] or 0)
                turnover_pct = float(r["turnover_pct"] or 0)
            else:
                turnover = turnover_pct = 0.0
            series.append(
                {
                    "trade_date": d,
                    "turnover": turnover,
                    "turnover_pct": turnover_pct,
                }
            )

        return {
            "etf_code": etf_code,
            "etf_name": etf_name,
            "days": days,
            "series": series,
        }

    def get_etf_charts(self, days: int = 5, top: int = 50, q: str = "") -> list[dict[str, Any]]:
        table = self.get_etf_table(days=days, sort="turnover_pct_desc")
        out = []
        for col in table.get("columns", []):
            if not col.get("etfs"):
                continue
            for row in col["etfs"]:
                if q:
                    ql = q.strip().lower()
                    text = f"{row['etf_code']} {row.get('etf_name', '')}".lower()
                    if ql not in text and ql not in row["etf_code"].lower():
                        continue
                out.append(row)
            break
        seen = set()
        unique = []
        for row in out:
            if row["etf_code"] in seen:
                continue
            seen.add(row["etf_code"])
            unique.append(row)
        unique = unique[:top]
        series_map: dict[str, list] = {r["etf_code"]: [] for r in unique}
        for col in table.get("columns", []):
            d = col["trade_date"]
            by_code = {e["etf_code"]: e for e in col.get("etfs", [])}
            for code in series_map:
                e = by_code.get(code)
                series_map[code].append(
                    {"trade_date": d, "value": float(e["turnover"]) if e else 0.0}
                )
        return [
            {
                "etf_code": r["etf_code"],
                "etf_name": r["etf_name"],
                "turnover_series": series_map[r["etf_code"]],
            }
            for r in unique
        ]

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

    def create_job(self, trade_date: str, trigger_type: str, *, end_date: str | None = None) -> str:
        job_id = str(uuid.uuid4())
        now = datetime.now(CST).isoformat()
        end = end_date or trade_date
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO fetch_jobs(job_id, trade_date, end_date, trigger_type, status, created_at)
                VALUES (?, ?, ?, ?, 'pending', ?)
                """,
                (job_id, trade_date, end, trigger_type, now),
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
                "concept_sector_daily.csv": pd.read_sql_query(
                    "SELECT * FROM concept_sector_daily WHERE trade_date=?",
                    conn,
                    params=(trade_date,),
                ),
                "sector_daily.csv": pd.read_sql_query("SELECT * FROM sector_daily WHERE trade_date=?", conn, params=(trade_date,)),
                "stock_daily.csv": pd.read_sql_query("SELECT * FROM stock_daily WHERE trade_date=?", conn, params=(trade_date,)),
                "etf_daily.csv": pd.read_sql_query("SELECT * FROM etf_daily WHERE trade_date=?", conn, params=(trade_date,)),
            }
        buf = io.BytesIO()
        meta = {"trade_date": trade_date, "generated_at": datetime.now(CST).isoformat()}
        for name, df in tables.items():
            meta[name.replace(".csv", "_rows")] = len(df)
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("meta.json", json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"))
            for name, df in tables.items():
                zf.writestr(name, self._csv_bytes_for_excel(df))
        return buf.getvalue()

    @staticmethod
    def _csv_bytes_for_excel(df: pd.DataFrame) -> bytes:
        """UTF-8 BOM，Excel 双击打开中文不乱码。"""
        out = df.copy()
        if "sector_name" in out.columns:
            out["sector_name"] = (
                out["sector_name"]
                .astype(str)
                .str.replace(r"^A股-申万(?:行业|二级)-", "", regex=True)
            )
        return out.to_csv(index=False).encode("utf-8-sig")
