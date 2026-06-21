"""反包打板信号 SQLite 存储。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

CST = ZoneInfo("Asia/Shanghai")

SIGNAL_SETTINGS_DEFAULTS: dict[str, str] = {
    "signal_enabled": "true",
    "signal_poll_interval_sec": "15",
    "signal_sched_start": "09:25",
    "signal_sched_end": "09:45",
    "signal_window_start": "09:30",
    "signal_window_end": "09:40",
    "signal_pct_threshold": "9.8",
    "signal_engulf_mode": "high",
    "signal_cross_body_ratio": "0.1",
    "signal_long_upper_ratio": "1.0",
    "signal_data_stale_sec": "120",
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS signal_hit_v4 (
    trade_date TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    stock_name TEXT,
    first_hit_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    last_price REAL,
    pct_change REAL,
    max_pct REAL,
    pre_close REAL,
    pre_high REAL,
    pre_open REAL,
    today_open REAL,
    t1_shape TEXT,
    engulf_type TEXT,
    is_limit_up INTEGER DEFAULT 0,
    score INTEGER DEFAULT 0,
    signal_hit INTEGER DEFAULT 0,
    hit_pct INTEGER DEFAULT 0,
    hit_pattern INTEGER DEFAULT 0,
    PRIMARY KEY (trade_date, stock_code)
);
CREATE INDEX IF NOT EXISTS idx_signal_hit_date_score ON signal_hit_v4(trade_date, score);
CREATE TABLE IF NOT EXISTS signal_scan_log_v4 (
    trade_date TEXT PRIMARY KEY,
    last_scan_at TEXT,
    last_error TEXT,
    scanned_count INTEGER,
    hit_count INTEGER
);
"""


class SignalStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA_SQL)

    def upsert_hit(
        self,
        trade_date: str,
        row: dict[str, Any],
        *,
        allow_insert: bool,
    ) -> bool:
        """写入或更新。allow_insert=False 时仅更新已有行。返回是否写入。"""
        now = datetime.now(CST).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT stock_code, first_hit_at, max_pct FROM signal_hit_v4 WHERE trade_date=? AND stock_code=?",
                (trade_date, row["stock_code"]),
            )
            existing = cur.fetchone()
            if existing is None and not allow_insert:
                return False
            max_pct = row.get("pct_change")
            if existing and existing["max_pct"] is not None and max_pct is not None:
                max_pct = max(float(existing["max_pct"]), float(max_pct))
            first_hit = existing["first_hit_at"] if existing else now
            conn.execute(
                """INSERT INTO signal_hit_v4(
                    trade_date, stock_code, stock_name, first_hit_at, last_seen_at,
                    last_price, pct_change, max_pct, pre_close, pre_high, pre_open, today_open,
                    t1_shape, engulf_type, is_limit_up, score, signal_hit, hit_pct, hit_pattern
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(trade_date, stock_code) DO UPDATE SET
                    stock_name=excluded.stock_name,
                    last_seen_at=excluded.last_seen_at,
                    last_price=excluded.last_price,
                    pct_change=excluded.pct_change,
                    max_pct=excluded.max_pct,
                    pre_close=excluded.pre_close,
                    pre_high=excluded.pre_high,
                    pre_open=excluded.pre_open,
                    today_open=COALESCE(excluded.today_open, signal_hit_v4.today_open),
                    t1_shape=excluded.t1_shape,
                    engulf_type=excluded.engulf_type,
                    is_limit_up=excluded.is_limit_up,
                    score=excluded.score,
                    signal_hit=excluded.signal_hit,
                    hit_pct=excluded.hit_pct,
                    hit_pattern=excluded.hit_pattern
                """,
                (
                    trade_date,
                    row["stock_code"],
                    row.get("stock_name"),
                    first_hit,
                    now,
                    row.get("last_price"),
                    row.get("pct_change"),
                    max_pct,
                    row.get("pre_close"),
                    row.get("pre_high"),
                    row.get("pre_open"),
                    row.get("today_open"),
                    row.get("t1_shape"),
                    row.get("engulf_type"),
                    1 if row.get("is_limit_up") else 0,
                    row.get("score", 0),
                    1 if row.get("signal_hit") else 0,
                    row.get("hit_pct", 0),
                    row.get("hit_pattern", 0),
                ),
            )
            return True

    def list_hits(self, trade_date: str, *, min_score: int = 1) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM signal_hit_v4
                   WHERE trade_date=? AND score>=?
                   ORDER BY signal_hit DESC, score DESC, pct_change DESC, stock_code""",
                (trade_date, min_score),
            ).fetchall()
        return [dict(r) for r in rows]

    def set_scan_meta(
        self,
        trade_date: str,
        *,
        scanned_count: int,
        hit_count: int,
        error: str | None = None,
    ) -> None:
        now = datetime.now(CST).isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO signal_scan_log_v4(trade_date, last_scan_at, last_error, scanned_count, hit_count)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(trade_date) DO UPDATE SET
                     last_scan_at=excluded.last_scan_at,
                     last_error=excluded.last_error,
                     scanned_count=excluded.scanned_count,
                     hit_count=excluded.hit_count""",
                (trade_date, now, error, scanned_count, hit_count),
            )

    def get_scan_meta(self, trade_date: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM signal_scan_log_v4 WHERE trade_date=?", (trade_date,)
            ).fetchone()
        return dict(row) if row else None
