"""量价吸筹 SQLite 存储。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

CST = ZoneInfo("Asia/Shanghai")

ACCUM_PATTERN_SETTINGS_DEFAULTS: dict[str, str] = {
    "accum_enabled": "true",
    "accum_time": "17:00",
    "accum_history_days": "120",
    "accum_vol_expand_trigger": "2.0",
    "accum_vol_expand_start": "2.0",
    "accum_vol_expand_decay": "0.1",
    "accum_vol_expand_floor": "1.1",
    "accum_vol_expand_max_consecutive_miss": "3",
    "accum_vol_min_days": "3",
    "accum_price_rise_min": "0.30",
    "accum_wash_mult": "1.5",
    "accum_vol_shrink_max": "1.1",
    "accum_vol_wash_max_consecutive_over": "2",
    "accum_vol_reset_trigger": "2.0",
    "accum_drawdown_min": "0.60",
    "accum_drawdown_max": "0.90",
}

ACCUM_PATTERN_SETTINGS_META: dict[str, str] = {
    "accum_enabled": "是否在交易日自动运行量价吸筹扫描。",
    "accum_time": "自动扫描时刻（建议 17:00，在神奇九转之后）。",
    "accum_history_days": "缓存日 K 最少交易日数（默认 120）。",
    "accum_vol_expand_trigger": "T₀ 触发：当日成交量 > 此倍数 × MA5（原始 vol）。",
    "accum_vol_expand_start": "放量延续：第 0 日动态阈值 M_start（与触发倍数可相同）。",
    "accum_vol_expand_decay": "放量延续：每过 1 日 M 递减幅度（M_k = max(M_start − decay×k, floor)）。",
    "accum_vol_expand_floor": "放量动态阈值下限（如 1.1 倍 MA5）。",
    "accum_vol_expand_max_consecutive_miss": "放量期连续不达标天数达到此值则结束放量段。",
    "accum_vol_min_days": "放量段最短交易日数 N（须 ≥3）。",
    "accum_price_rise_min": "放量段折线涨幅下限（0.30=30%）：窗口内阳线收盘/阴线开盘连接点，最高相对最低。",
    "accum_wash_mult": "洗盘观察天数系数：M = int(wash_mult × N)，可配 1.0～1.5。",
    "accum_vol_shrink_max": "洗盘期缩量上限：V 须 < 此倍数 × MA5。",
    "accum_vol_wash_max_consecutive_over": "洗盘期连续超标（≥缩量上限）天数上限（达到则形态失败）。",
    "accum_vol_reset_trigger": "洗盘期再放量：V > 此倍数 × MA5 则旧形态作废、从该日重扫。",
    "accum_drawdown_min": "洗盘回撤占 T₁ 涨幅比例下限（0.60 = 60%）。",
    "accum_drawdown_max": "洗盘回撤占 T₁ 涨幅比例上限（0.90 = 90%）；仅洗盘走完时用于确认。",
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS accum_pattern_daily_cache (
    trade_date TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    open REAL,
    close REAL,
    vol REAL,
    adj_factor REAL,
    PRIMARY KEY (trade_date, stock_code)
);
CREATE INDEX IF NOT EXISTS idx_accum_cache_code ON accum_pattern_daily_cache(stock_code, trade_date);
CREATE TABLE IF NOT EXISTS accum_pattern_pick_v4 (
    trade_date TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    stock_name TEXT,
    sector_path TEXT,
    t0_date TEXT,
    expand_end_date TEXT,
    n_days INTEGER,
    m_target INTEGER,
    wash_days_done INTEGER,
    phase TEXT,
    price_rise_pct REAL,
    drawdown_ratio REAL,
    drawdown_ok INTEGER,
    close REAL,
    detail_json TEXT,
    updated_at TEXT,
    PRIMARY KEY (trade_date, stock_code)
);
CREATE INDEX IF NOT EXISTS idx_accum_pick_date ON accum_pattern_pick_v4(trade_date, phase);
CREATE TABLE IF NOT EXISTS accum_pattern_scan_log (
    trade_date TEXT PRIMARY KEY,
    last_scan_at TEXT,
    universe_count INTEGER,
    pick_count INTEGER,
    funnel_json TEXT,
    error_message TEXT
);
CREATE TABLE IF NOT EXISTS accum_pattern_scan_jobs (
    job_id TEXT PRIMARY KEY,
    trade_date TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    duration_sec REAL,
    progress TEXT,
    error_message TEXT,
    pick_count INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_accum_scan_jobs_created ON accum_pattern_scan_jobs(created_at DESC);
"""


class AccumPatternStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA_SQL)

    def upsert_cache_rows(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        with self._conn() as conn:
            conn.executemany(
                """INSERT INTO accum_pattern_daily_cache
                   (trade_date, stock_code, open, close, vol, adj_factor)
                   VALUES (:trade_date,:stock_code,:open,:close,:vol,:adj_factor)
                   ON CONFLICT(trade_date, stock_code) DO UPDATE SET
                     open=excluded.open, close=excluded.close,
                     vol=excluded.vol, adj_factor=excluded.adj_factor""",
                rows,
            )

    def list_cached_dates(self) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT trade_date FROM accum_pattern_daily_cache ORDER BY trade_date"
            ).fetchall()
        return [r["trade_date"] for r in rows]

    def load_cache_panel(self, trade_dates: list[str]) -> list[dict[str, Any]]:
        if not trade_dates:
            return []
        placeholders = ",".join("?" * len(trade_dates))
        with self._conn() as conn:
            rows = conn.execute(
                f"""SELECT trade_date, stock_code, open, close, vol, adj_factor
                    FROM accum_pattern_daily_cache WHERE trade_date IN ({placeholders})""",
                trade_dates,
            ).fetchall()
        return [dict(r) for r in rows]

    def prune_cache_before(self, min_date: str) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM accum_pattern_daily_cache WHERE trade_date < ?", (min_date,)
            )
            return cur.rowcount

    def replace_picks(self, trade_date: str, picks: list[dict[str, Any]]) -> None:
        now = datetime.now(CST).isoformat()
        with self._conn() as conn:
            conn.execute("DELETE FROM accum_pattern_pick_v4 WHERE trade_date=?", (trade_date,))
            for row in picks:
                conn.execute(
                    """INSERT INTO accum_pattern_pick_v4(
                        trade_date, stock_code, stock_name, sector_path,
                        t0_date, expand_end_date, n_days, m_target, wash_days_done,
                        phase, price_rise_pct, drawdown_ratio, drawdown_ok, close,
                        detail_json, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        trade_date,
                        row["stock_code"],
                        row.get("stock_name"),
                        row.get("sector_path"),
                        row.get("t0_date"),
                        row.get("expand_end_date"),
                        row.get("n_days"),
                        row.get("m_target"),
                        row.get("wash_days_done"),
                        row.get("phase"),
                        row.get("price_rise_pct"),
                        row.get("drawdown_ratio"),
                        row.get("drawdown_ok", 0),
                        row.get("close"),
                        row.get("detail_json"),
                        now,
                    ),
                )

    def list_picks(
        self,
        trade_date: str,
        *,
        phase: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM accum_pattern_pick_v4 WHERE trade_date=?"
        params: list[Any] = [trade_date]
        if phase:
            sql += " AND phase=?"
            params.append(phase)
        sql += " ORDER BY t0_date DESC, stock_code"
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_pick(self, trade_date: str, stock_code: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM accum_pattern_pick_v4 WHERE trade_date=? AND stock_code=?",
                (trade_date, stock_code),
            ).fetchone()
        return dict(row) if row else None

    def set_scan_log(
        self,
        trade_date: str,
        *,
        universe_count: int,
        pick_count: int,
        error: str | None = None,
        funnel: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now(CST).isoformat()
        funnel_json = json.dumps(funnel, ensure_ascii=False) if funnel else None
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO accum_pattern_scan_log(
                       trade_date, last_scan_at, universe_count, pick_count,
                       error_message, funnel_json
                   ) VALUES (?,?,?,?,?,?)
                   ON CONFLICT(trade_date) DO UPDATE SET
                     last_scan_at=excluded.last_scan_at,
                     universe_count=excluded.universe_count,
                     pick_count=excluded.pick_count,
                     error_message=excluded.error_message,
                     funnel_json=excluded.funnel_json""",
                (trade_date, now, universe_count, pick_count, error, funnel_json),
            )

    def get_scan_log(self, trade_date: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM accum_pattern_scan_log WHERE trade_date=?", (trade_date,)
            ).fetchone()
        return dict(row) if row else None

    def get_settings_meta(self) -> dict[str, str]:
        return dict(ACCUM_PATTERN_SETTINGS_META)

    def create_scan_job(self, trade_date: str, trigger_type: str) -> str:
        job_id = str(uuid.uuid4())
        now = datetime.now(CST).isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO accum_pattern_scan_jobs(
                       job_id, trade_date, trigger_type, status, created_at
                   ) VALUES (?, ?, ?, 'pending', ?)""",
                (job_id, trade_date, trigger_type, now),
            )
        return job_id

    def update_scan_job(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE accum_pattern_scan_jobs SET {cols} WHERE job_id=?",
                (*fields.values(), job_id),
            )

    def get_scan_job(self, job_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM accum_pattern_scan_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_active_scan_job(self) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM accum_pattern_scan_jobs
                   WHERE status IN ('pending', 'running')
                   ORDER BY created_at DESC LIMIT 1"""
            ).fetchone()
        return dict(row) if row else None

    def get_latest_scan_job(self) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM accum_pattern_scan_jobs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None


def cache_rows_from_daily_adj(
    daily_df: Any,
    adj_df: Any,
    trade_date: str,
) -> list[dict[str, Any]]:
    """合并 daily + adj_factor 为缓存行。"""
    import pandas as pd

    import ts_common as tc

    if daily_df is None or daily_df.empty:
        return []
    adj_map: dict[str, float] = {}
    if adj_df is not None and not adj_df.empty:
        for _, r in adj_df.iterrows():
            code = tc.ts_code_to_code6(str(r["ts_code"]))
            adj_map[code] = float(r.get("adj_factor") or 0)
    rows: list[dict[str, Any]] = []
    for _, r in daily_df.iterrows():
        code = tc.ts_code_to_code6(str(r["ts_code"]))
        rows.append(
            {
                "trade_date": trade_date,
                "stock_code": code,
                "open": float(r.get("open") or 0),
                "close": float(r.get("close") or 0),
                "vol": float(r.get("vol") or 0),
                "adj_factor": adj_map.get(code, 1.0),
            }
        )
    return rows


def format_scan_progress(phase: str, current: int, total: int) -> str:
    if phase == "compute":
        if total > 1:
            return f"compute:{current}/{total}"
        return "compute"
    return f"cache:{current}/{total}"
