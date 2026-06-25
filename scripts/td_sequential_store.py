"""神奇九转 SQLite 存储。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

CST = ZoneInfo("Asia/Shanghai")

TD_SEQUENTIAL_SETTINGS_DEFAULTS: dict[str, str] = {
    "td_enabled": "true",
    "td_time": "16:45",
    "td_history_days": "120",
    "td_lookback_days": "20",
    "td_vol_shrink_ratio": "0.8",
    "td_vol_expand_ratio": "1.2",
    "td_shadow_lower_min": "0.5",
    "td_cross_body_max": "0.15",
    "td_bear_lower_max": "0.2",
    "td_vol_price_mode": "or",
    "td_countdown_near_min": "10",
    "td_countdown_near_max": "12",
    "td_countdown_after_setup_days": "5",
    "td_macd_fast": "12",
    "td_macd_slow": "26",
    "td_macd_signal": "9",
    "td_macd_div_ref": "hist",
    "td_stop_loss_pct": "0.03",
}

TD_SEQUENTIAL_SETTINGS_META: dict[str, str] = {
    "td_enabled": "是否在交易日自动运行神奇九转扫描。",
    "td_time": "自动扫描时刻（建议 16:45，在火车轨之后）。",
    "td_history_days": "缓存日 K 最少交易日数（默认 120）。",
    "td_lookback_days": "自扫描日向前回溯的交易日数，窗内九转/十三转均统计。",
    "td_vol_shrink_ratio": "列2：当日量低于前5日均量×此比例视为缩量。",
    "td_vol_expand_ratio": "列2：当日量高于前5日均量×此比例视为放量。",
    "td_shadow_lower_min": "列2：下影线占振幅比例下限（锤子）。",
    "td_cross_body_max": "列2：十字实体占振幅比例上限。",
    "td_bear_lower_max": "列2：放量大阴的下影过小阈值。",
    "td_vol_price_mode": "列2合格逻辑：or=缩量或锤子其一；and=须同时满足。",
    "td_countdown_near_min": "列3：Countdown 最少已计数。",
    "td_countdown_near_max": "列3：Countdown 最多已计数（未满13）。",
    "td_countdown_after_setup_days": "列3：自九转完成日至扫描日最大交易日数。",
    "td_macd_fast": "MACD 快线周期。",
    "td_macd_slow": "MACD 慢线周期。",
    "td_macd_signal": "MACD 信号线周期。",
    "td_macd_div_ref": "列5底背离参考：hist / dif / both。",
    "td_stop_loss_pct": "参考止损：九转最低价下方比例（仅展示）。",
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS td_sequential_pick_v4 (
    trade_date TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    stock_name TEXT,
    sector_path TEXT,
    setup_9_date TEXT,
    setup_9_close REAL,
    setup_9_low REAL,
    setup_9_vol REAL,
    setup_9_turnover_rate REAL,
    cd_count INTEGER NOT NULL DEFAULT 0,
    cd_last_date TEXT,
    countdown_13_date TEXT,
    col1_setup9 INTEGER NOT NULL DEFAULT 0,
    col2_vol_price INTEGER NOT NULL DEFAULT 0,
    col3_near13 INTEGER NOT NULL DEFAULT 0,
    col4_cd13 INTEGER NOT NULL DEFAULT 0,
    col5_macd_div INTEGER NOT NULL DEFAULT 0,
    max_col INTEGER NOT NULL DEFAULT 0,
    vol_tag TEXT,
    lower_shadow_ratio REAL,
    upper_shadow_ratio REAL,
    body_ratio REAL,
    macd_hist_setup9 REAL,
    macd_hist_cd13 REAL,
    macd_div_type TEXT,
    bars_setup_to_cd13 INTEGER,
    stop_loss_price REAL,
    days_since_setup INTEGER,
    gap_setup_to_cd_days INTEGER,
    days_setup_to_scan INTEGER,
    detail_json TEXT,
    updated_at TEXT,
    PRIMARY KEY (trade_date, stock_code)
);
CREATE INDEX IF NOT EXISTS idx_td_pick_date_col ON td_sequential_pick_v4(trade_date, max_col);
CREATE TABLE IF NOT EXISTS td_sequential_scan_log (
    trade_date TEXT PRIMARY KEY,
    last_scan_at TEXT,
    universe_count INTEGER,
    funnel_json TEXT,
    error_message TEXT
);
CREATE TABLE IF NOT EXISTS td_sequential_scan_jobs (
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
CREATE INDEX IF NOT EXISTS idx_td_scan_jobs_created ON td_sequential_scan_jobs(created_at DESC);
"""


class TdSequentialStore:
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
            cols = {r[1] for r in conn.execute("PRAGMA table_info(td_sequential_pick_v4)").fetchall()}
            if "gap_setup_to_cd_days" not in cols:
                conn.execute("ALTER TABLE td_sequential_pick_v4 ADD COLUMN gap_setup_to_cd_days INTEGER")
            if "days_setup_to_scan" not in cols:
                conn.execute("ALTER TABLE td_sequential_pick_v4 ADD COLUMN days_setup_to_scan INTEGER")

    def replace_picks(self, trade_date: str, picks: list[dict[str, Any]]) -> None:
        now = datetime.now(CST).isoformat()
        with self._conn() as conn:
            conn.execute("DELETE FROM td_sequential_pick_v4 WHERE trade_date=?", (trade_date,))
            for row in picks:
                conn.execute(
                    """INSERT INTO td_sequential_pick_v4(
                        trade_date, stock_code, stock_name, sector_path,
                        setup_9_date, setup_9_close, setup_9_low, setup_9_vol, setup_9_turnover_rate,
                        cd_count, cd_last_date, countdown_13_date,
                        col1_setup9, col2_vol_price, col3_near13, col4_cd13, col5_macd_div, max_col,
                        vol_tag, lower_shadow_ratio, upper_shadow_ratio, body_ratio,
                        macd_hist_setup9, macd_hist_cd13, macd_div_type,
                        bars_setup_to_cd13, stop_loss_price, days_since_setup,
                        gap_setup_to_cd_days, days_setup_to_scan, detail_json, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        trade_date,
                        row["stock_code"],
                        row.get("stock_name"),
                        row.get("sector_path"),
                        row.get("setup_9_date"),
                        row.get("setup_9_close"),
                        row.get("setup_9_low"),
                        row.get("setup_9_vol"),
                        row.get("setup_9_turnover_rate"),
                        row.get("cd_count", 0),
                        row.get("cd_last_date"),
                        row.get("countdown_13_date"),
                        row.get("col1_setup9", 0),
                        row.get("col2_vol_price", 0),
                        row.get("col3_near13", 0),
                        row.get("col4_cd13", 0),
                        row.get("col5_macd_div", 0),
                        row.get("max_col", 0),
                        row.get("vol_tag"),
                        row.get("lower_shadow_ratio"),
                        row.get("upper_shadow_ratio"),
                        row.get("body_ratio"),
                        row.get("macd_hist_setup9"),
                        row.get("macd_hist_cd13"),
                        row.get("macd_div_type"),
                        row.get("bars_setup_to_cd13"),
                        row.get("stop_loss_price"),
                        row.get("days_since_setup"),
                        row.get("gap_setup_to_cd_days"),
                        row.get("days_setup_to_scan"),
                        row.get("detail_json"),
                        now,
                    ),
                )

    def list_picks_by_col(self, trade_date: str, col: int) -> list[dict[str, Any]]:
        """按列标志筛选（非 max_col）；列间为递进子集由 board() 组装。"""
        flag = {
            1: "col1_setup9",
            2: "col2_vol_price",
            3: "col3_near13",
            4: "col4_cd13",
            5: "col5_macd_div",
        }.get(col)
        if not flag:
            return []
        with self._conn() as conn:
            rows = conn.execute(
                f"""SELECT * FROM td_sequential_pick_v4
                   WHERE trade_date=? AND {flag}=1
                   ORDER BY setup_9_date DESC, stock_code""",
                (trade_date,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_all_picks(self, trade_date: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM td_sequential_pick_v4
                   WHERE trade_date=? ORDER BY max_col DESC, setup_9_date DESC, stock_code""",
                (trade_date,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_pick(self, trade_date: str, stock_code: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM td_sequential_pick_v4 WHERE trade_date=? AND stock_code=?",
                (trade_date, stock_code),
            ).fetchone()
        return dict(row) if row else None

    def set_scan_log(
        self,
        trade_date: str,
        *,
        universe_count: int,
        error: str | None = None,
        funnel: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now(CST).isoformat()
        funnel_json = json.dumps(funnel, ensure_ascii=False) if funnel else None
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO td_sequential_scan_log(
                       trade_date, last_scan_at, universe_count, error_message, funnel_json
                   ) VALUES (?,?,?,?,?)
                   ON CONFLICT(trade_date) DO UPDATE SET
                     last_scan_at=excluded.last_scan_at,
                     universe_count=excluded.universe_count,
                     error_message=excluded.error_message,
                     funnel_json=excluded.funnel_json""",
                (trade_date, now, universe_count, error, funnel_json),
            )

    def get_scan_log(self, trade_date: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM td_sequential_scan_log WHERE trade_date=?", (trade_date,)
            ).fetchone()
        return dict(row) if row else None

    def get_settings_meta(self) -> dict[str, str]:
        return dict(TD_SEQUENTIAL_SETTINGS_META)

    def create_scan_job(self, trade_date: str, trigger_type: str) -> str:
        job_id = str(uuid.uuid4())
        now = datetime.now(CST).isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO td_sequential_scan_jobs(
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
                f"UPDATE td_sequential_scan_jobs SET {cols} WHERE job_id=?",
                (*fields.values(), job_id),
            )

    def get_scan_job(self, job_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM td_sequential_scan_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_active_scan_job(self) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM td_sequential_scan_jobs
                   WHERE status IN ('pending', 'running')
                   ORDER BY created_at DESC LIMIT 1"""
            ).fetchone()
        return dict(row) if row else None

    def get_latest_scan_job(self) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM td_sequential_scan_jobs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None


def format_scan_progress(phase: str, current: int, total: int) -> str:
    if phase == "compute":
        return "compute"
    return f"cache:{current}/{total}"
