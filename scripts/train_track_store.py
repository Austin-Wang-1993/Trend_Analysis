"""火车轨选股 SQLite 存储与配置元数据。"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

import ts_common as tc

CST = ZoneInfo("Asia/Shanghai")

TRAIN_TRACK_SETTINGS_DEFAULTS: dict[str, str] = {
    "train_track_enabled": "true",
    "train_track_time": "16:30",
    "train_track_history_days": "250",
    "train_track_default_limit": "20",
    "train_track_rps_sum_min": "185",
    "train_track_near_high_250_min": "0.8",
    "train_track_drawdown_20_max": "0.25",
    "train_track_turnover_max": "10",
    "train_track_count_ma250_30_min": "25",
    "train_track_count_ma200_30_min": "25",
    "train_track_count_ma20_10_min": "9",
    "train_track_count_ma10_4_min": "3",
    "train_track_count_ma20_4_min": "3",
    "train_track_ma_rise_days": "5",
    "train_track_recent_20d_pct_max": "30",
    "train_track_ma_touch_band_pct": "2",
}

# 管理页参数说明（key → 中文注释）
TRAIN_TRACK_SETTINGS_META: dict[str, str] = {
    "train_track_enabled": "是否在交易日自动运行火车轨扫描。",
    "train_track_time": "自动扫描时刻（建议收盘后 16:30，需 daily 已更新）。",
    "train_track_history_days": "缓存日线最少交易日数（默认 250，用于 MA250/RPS250）。",
    "train_track_default_limit": "看板默认展示前 N 名（按 RPS250 排序）。",
    "train_track_rps_sum_min": "SXHCG1：RPS120+RPS250 之和下限。陶博士常用 185（约等于双 90+）。",
    "train_track_near_high_250_min": "SXHCG3：收盘/250日最高收盘 ≥ 此比例（默认 0.8=80%）。",
    "train_track_drawdown_20_max": "SXHCG3：允许距20日高点最大回撤比例（0.25=25%，即收盘≥高点×0.75）。",
    "train_track_turnover_max": "SXHCG5：当日换手率上限%（VOL/流通股本，过大视为过热）。",
    "train_track_count_ma250_30_min": "SXHCG2：近30日收盘>MA250 至少几天。",
    "train_track_count_ma200_30_min": "SXHCG2：近30日收盘>MA200 至少几天。",
    "train_track_count_ma20_10_min": "SXHCG2：近10日收盘>MA20 至少几天（与下一行二选一）。",
    "train_track_count_ma10_4_min": "SXHCG2：近4日收盘>MA10 至少几天（需同时满足 MA20 天数）。",
    "train_track_count_ma20_4_min": "SXHCG2：近4日收盘>MA20 至少几天。",
    "train_track_ma_rise_days": "SXHCG4：均线连涨/多头判定连续天数。",
    "train_track_recent_20d_pct_max": "方案C：近20交易日涨幅上限%（筛「没大涨」，如 30=20日涨<30%）。",
    "train_track_ma_touch_band_pct": "距 MA5/MA10 在 ±此% 内标「回踩」标签，辅助手工买点。",
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS train_track_daily_cache (
    trade_date TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    vol REAL,
    turnover_rate REAL,
    PRIMARY KEY (trade_date, stock_code)
);
CREATE INDEX IF NOT EXISTS idx_tt_cache_code ON train_track_daily_cache(stock_code, trade_date);
CREATE TABLE IF NOT EXISTS train_track_pick_v4 (
    trade_date TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    stock_name TEXT,
    sector_path TEXT,
    rps120 REAL,
    rps250 REAL,
    rps_sum REAL,
    close REAL,
    pct_20d REAL,
    dist_ma5_pct REAL,
    dist_ma10_pct REAL,
    ma_touch_tag TEXT,
    turnover_rate REAL,
    near_high_250_pct REAL,
    hit_sxhcg1 INTEGER,
    hit_sxhcg2 INTEGER,
    hit_sxhcg3 INTEGER,
    hit_sxhcg4 INTEGER,
    hit_sxhcg5 INTEGER,
    hit_recent_calm INTEGER,
    rank_rps250 INTEGER,
    updated_at TEXT,
    PRIMARY KEY (trade_date, stock_code)
);
CREATE INDEX IF NOT EXISTS idx_tt_pick_date_rank ON train_track_pick_v4(trade_date, rank_rps250);
CREATE TABLE IF NOT EXISTS train_track_scan_log (
    trade_date TEXT PRIMARY KEY,
    last_scan_at TEXT,
    pick_count INTEGER,
    universe_count INTEGER,
    error_message TEXT,
    funnel_json TEXT
);
CREATE TABLE IF NOT EXISTS train_track_scan_jobs (
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
CREATE INDEX IF NOT EXISTS idx_tt_scan_jobs_created ON train_track_scan_jobs(created_at DESC);
"""


class TrainTrackStore:
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
            cols = {r[1] for r in conn.execute("PRAGMA table_info(train_track_scan_log)").fetchall()}
            if "funnel_json" not in cols:
                conn.execute("ALTER TABLE train_track_scan_log ADD COLUMN funnel_json TEXT")

    def upsert_cache_rows(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        with self._conn() as conn:
            conn.executemany(
                """INSERT INTO train_track_daily_cache
                   (trade_date, stock_code, open, high, low, close, vol, turnover_rate)
                   VALUES (:trade_date,:stock_code,:open,:high,:low,:close,:vol,:turnover_rate)
                   ON CONFLICT(trade_date, stock_code) DO UPDATE SET
                     open=excluded.open, high=excluded.high, low=excluded.low,
                     close=excluded.close, vol=excluded.vol, turnover_rate=excluded.turnover_rate""",
                rows,
            )

    def list_cached_dates(self) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT trade_date FROM train_track_daily_cache ORDER BY trade_date"
            ).fetchall()
        return [r["trade_date"] for r in rows]

    def load_cache_panel(self, trade_dates: list[str]) -> list[dict[str, Any]]:
        if not trade_dates:
            return []
        placeholders = ",".join("?" * len(trade_dates))
        with self._conn() as conn:
            rows = conn.execute(
                f"""SELECT trade_date, stock_code, open, high, low, close, vol, turnover_rate
                    FROM train_track_daily_cache WHERE trade_date IN ({placeholders})""",
                trade_dates,
            ).fetchall()
        return [dict(r) for r in rows]

    def prune_cache_before(self, min_date: str) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM train_track_daily_cache WHERE trade_date < ?", (min_date,)
            )
            return cur.rowcount

    def replace_picks(self, trade_date: str, picks: list[dict[str, Any]]) -> None:
        now = datetime.now(CST).isoformat()
        with self._conn() as conn:
            conn.execute("DELETE FROM train_track_pick_v4 WHERE trade_date=?", (trade_date,))
            for row in picks:
                conn.execute(
                    """INSERT INTO train_track_pick_v4(
                        trade_date, stock_code, stock_name, sector_path,
                        rps120, rps250, rps_sum, close, pct_20d,
                        dist_ma5_pct, dist_ma10_pct, ma_touch_tag, turnover_rate,
                        near_high_250_pct, hit_sxhcg1, hit_sxhcg2, hit_sxhcg3,
                        hit_sxhcg4, hit_sxhcg5, hit_recent_calm, rank_rps250, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        trade_date,
                        row["stock_code"],
                        row.get("stock_name"),
                        row.get("sector_path"),
                        row.get("rps120"),
                        row.get("rps250"),
                        row.get("rps_sum"),
                        row.get("close"),
                        row.get("pct_20d"),
                        row.get("dist_ma5_pct"),
                        row.get("dist_ma10_pct"),
                        row.get("ma_touch_tag"),
                        row.get("turnover_rate"),
                        row.get("near_high_250_pct"),
                        row.get("hit_sxhcg1"),
                        row.get("hit_sxhcg2"),
                        row.get("hit_sxhcg3"),
                        row.get("hit_sxhcg4"),
                        row.get("hit_sxhcg5"),
                        row.get("hit_recent_calm"),
                        row.get("rank_rps250"),
                        now,
                    ),
                )

    def list_picks(
        self,
        trade_date: str,
        *,
        limit: int | None = None,
        sort: str = "rps250",
    ) -> list[dict[str, Any]]:
        order = "rank_rps250 ASC"
        if sort == "rps120":
            order = "rps120 DESC"
        elif sort == "pct_20d":
            order = "pct_20d ASC"
        sql = f"SELECT * FROM train_track_pick_v4 WHERE trade_date=? ORDER BY {order}"
        if limit:
            sql += f" LIMIT {int(limit)}"
        with self._conn() as conn:
            rows = conn.execute(sql, (trade_date,)).fetchall()
        return [dict(r) for r in rows]

    def set_scan_log(
        self,
        trade_date: str,
        *,
        pick_count: int,
        universe_count: int,
        error: str | None = None,
        funnel: dict[str, Any] | None = None,
    ) -> None:
        import json

        now = datetime.now(CST).isoformat()
        funnel_json = json.dumps(funnel, ensure_ascii=False) if funnel else None
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO train_track_scan_log(
                       trade_date, last_scan_at, pick_count, universe_count, error_message, funnel_json
                   ) VALUES (?,?,?,?,?,?)
                   ON CONFLICT(trade_date) DO UPDATE SET
                     last_scan_at=excluded.last_scan_at,
                     pick_count=excluded.pick_count,
                     universe_count=excluded.universe_count,
                     error_message=excluded.error_message,
                     funnel_json=excluded.funnel_json""",
                (trade_date, now, pick_count, universe_count, error, funnel_json),
            )

    def get_scan_log(self, trade_date: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM train_track_scan_log WHERE trade_date=?", (trade_date,)
            ).fetchone()
        return dict(row) if row else None

    def get_settings_meta(self) -> dict[str, str]:
        return dict(TRAIN_TRACK_SETTINGS_META)

    def create_scan_job(self, trade_date: str, trigger_type: str) -> str:
        job_id = str(uuid.uuid4())
        now = datetime.now(CST).isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO train_track_scan_jobs(
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
                f"UPDATE train_track_scan_jobs SET {cols} WHERE job_id=?",
                (*fields.values(), job_id),
            )

    def get_scan_job(self, job_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM train_track_scan_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_active_scan_job(self) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM train_track_scan_jobs
                   WHERE status IN ('pending', 'running')
                   ORDER BY created_at DESC LIMIT 1"""
            ).fetchone()
        return dict(row) if row else None

    def get_latest_scan_job(self) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM train_track_scan_jobs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None


def normalize_trade_date(value: str) -> str:
    d = str(value).strip()
    if len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return d


def turnover_map_from_basic(basic_df: pd.DataFrame | None) -> dict[str, float]:
    out: dict[str, float] = {}
    if basic_df is None or basic_df.empty:
        return out
    for _, r in basic_df.iterrows():
        code = tc.ts_code_to_code6(str(r["ts_code"]))
        if pd.notna(r.get("turnover_rate")):
            out[code] = float(r["turnover_rate"])
    return out


def cache_rows_from_daily(
    daily_df: pd.DataFrame | None,
    turnover_by_code: dict[str, float],
    trade_date: str,
) -> list[dict[str, Any]]:
    """由 Tushare daily + turnover 映射生成火车轨缓存行。"""
    td = normalize_trade_date(trade_date)
    rows: list[dict[str, Any]] = []
    if daily_df is None or daily_df.empty:
        return rows
    for _, r in daily_df.iterrows():
        code = tc.ts_code_to_code6(str(r["ts_code"]))
        rows.append(
            {
                "trade_date": td,
                "stock_code": code,
                "open": float(r["open"]) if pd.notna(r.get("open")) else None,
                "high": float(r["high"]) if pd.notna(r.get("high")) else None,
                "low": float(r["low"]) if pd.notna(r.get("low")) else None,
                "close": float(r["close"]) if pd.notna(r.get("close")) else None,
                "vol": float(r["vol"]) if pd.notna(r.get("vol")) else None,
                "turnover_rate": turnover_by_code.get(code),
            }
        )
    return rows


def format_scan_progress(phase: str, current: int, total: int) -> str:
    if phase == "compute":
        return "compute"
    return f"cache:{current}/{total}"
