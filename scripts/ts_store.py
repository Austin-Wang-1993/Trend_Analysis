"""v4.0 数据访问层（Tushare 四套行业）。

独立于 v3.6 的 `history_store`，使用专用表（后缀 `_v4`），避免影响现网。
- 写入：映射 + 个股/行业/全A/ETF 日表
- 读取：看板 API（输出结构兼容现有前端，并新增 净额/主力/涨跌 指标）

聚合口径见 docs/TUSHARE_SECTOR_DESIGN.md §3（净流入为核心信号）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

from ts_aggregate import SECTOR_COLUMNS
from ts_sectors import KINDS

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS market_daily_v4 (
    trade_date TEXT PRIMARY KEY,
    turnover REAL NOT NULL DEFAULT 0,
    active_buy REAL, active_sell REAL, net_active REAL,
    main_buy REAL, main_sell REAL,
    up_count INTEGER, down_count INTEGER, flat_count INTEGER,
    stock_count INTEGER,
    snapshot_time TEXT
);
CREATE TABLE IF NOT EXISTS stock_daily_v4 (
    trade_date TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    stock_name TEXT,
    turnover REAL, pct_chg REAL,
    active_buy REAL, active_sell REAL, net_active REAL,
    main_buy REAL, main_sell REAL,
    zmbtdcje REAL, zmbddcje REAL, zmbzdcje REAL, zmbxdcje REAL,
    zmstdcje REAL, zmsddcje REAL, zmszdcje REAL, zmsxdcje REAL,
    PRIMARY KEY (trade_date, stock_code)
);
CREATE TABLE IF NOT EXISTS sector_daily_v4 (
    trade_date TEXT NOT NULL,
    kind TEXT NOT NULL,
    sector_code TEXT NOT NULL,
    sector_name TEXT NOT NULL,
    sector_path TEXT,
    turnover REAL NOT NULL DEFAULT 0, turnover_pct REAL,
    active_buy REAL, buy_pct REAL,
    active_sell REAL, sell_pct REAL,
    net_active REAL, net_pct REAL,
    main_buy REAL, main_buy_pct REAL,
    main_sell REAL, main_sell_pct REAL,
    up_count INTEGER, down_count INTEGER, flat_count INTEGER,
    up_ratio REAL, down_ratio REAL,
    stock_count INTEGER,
    PRIMARY KEY (trade_date, kind, sector_code)
);
CREATE INDEX IF NOT EXISTS idx_sector_v4_date_kind ON sector_daily_v4(trade_date, kind);
CREATE TABLE IF NOT EXISTS sector_stock_map_v4 (
    kind TEXT NOT NULL,
    sector_code TEXT NOT NULL,
    sector_name TEXT NOT NULL,
    sector_path TEXT,
    stock_code TEXT NOT NULL,
    PRIMARY KEY (kind, stock_code)
);
CREATE INDEX IF NOT EXISTS idx_map_v4_kind_sector ON sector_stock_map_v4(kind, sector_code);
CREATE TABLE IF NOT EXISTS sector_catalog_v4 (
    kind TEXT NOT NULL,
    sector_code TEXT NOT NULL,
    sector_name TEXT NOT NULL,
    sector_path TEXT,
    PRIMARY KEY (kind, sector_code)
);
CREATE TABLE IF NOT EXISTS etf_daily_v4 (
    trade_date TEXT NOT NULL,
    etf_code TEXT NOT NULL,
    etf_name TEXT,
    exchange TEXT,
    turnover REAL NOT NULL DEFAULT 0, turnover_pct REAL,
    pct_chg REAL,
    fd_share REAL,
    PRIMARY KEY (trade_date, etf_code)
);
CREATE INDEX IF NOT EXISTS idx_etf_v4_date ON etf_daily_v4(trade_date);
"""

# 行业卡片排序：净流入/主力净流入/成交占比/涨跌比例
_SECTOR_SORTS = {
    "turnover_pct_desc": ("turnover_pct", True),
    "turnover_pct_asc": ("turnover_pct", False),
    "net_pct_desc": ("net_pct", True),
    "net_pct_asc": ("net_pct", False),
    "net_desc": ("net_active", True),
    "net_asc": ("net_active", False),
    "main_net_desc": ("main_net", True),
    "main_net_asc": ("main_net", False),
    "up_ratio_desc": ("up_ratio", True),
    "down_ratio_desc": ("down_ratio", True),
}


class TsStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.commit()

    # ----------------------------------------------------------------- write
    def upsert_mapping(self, kind: str, mapping_df: pd.DataFrame, catalog_df: pd.DataFrame) -> None:
        if kind not in KINDS:
            raise ValueError(f"unsupported kind: {kind}")
        with self._connect() as conn:
            conn.execute("DELETE FROM sector_stock_map_v4 WHERE kind=?", (kind,))
            conn.execute("DELETE FROM sector_catalog_v4 WHERE kind=?", (kind,))
            if mapping_df is not None and not mapping_df.empty:
                conn.executemany(
                    "INSERT OR REPLACE INTO sector_stock_map_v4(kind, sector_code, sector_name, sector_path, stock_code) VALUES (?,?,?,?,?)",
                    [
                        (kind, str(r["sector_code"]), str(r["sector_name"]), r.get("sector_path"), str(r["stock_code"]))
                        for _, r in mapping_df.iterrows()
                    ],
                )
            if catalog_df is not None and not catalog_df.empty:
                conn.executemany(
                    "INSERT OR REPLACE INTO sector_catalog_v4(kind, sector_code, sector_name, sector_path) VALUES (?,?,?,?)",
                    [
                        (kind, str(r["sector_code"]), str(r["sector_name"]), r.get("sector_path"))
                        for _, r in catalog_df.iterrows()
                    ],
                )
            conn.commit()

    def get_mapping(self, kind: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        with self._connect() as conn:
            mapping = pd.read_sql_query(
                "SELECT sector_code, sector_name, sector_path, stock_code FROM sector_stock_map_v4 WHERE kind=?",
                conn, params=(kind,),
            )
            catalog = pd.read_sql_query(
                "SELECT sector_code, sector_name, sector_path FROM sector_catalog_v4 WHERE kind=?",
                conn, params=(kind,),
            )
        return mapping, catalog

    def upsert_market(self, trade_date: str, market: dict[str, Any], snapshot_time: str | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO market_daily_v4
                   (trade_date, turnover, active_buy, active_sell, net_active, main_buy, main_sell,
                    up_count, down_count, flat_count, stock_count, snapshot_time)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    trade_date, market.get("turnover", 0.0), market.get("active_buy"), market.get("active_sell"),
                    market.get("net_active"), market.get("main_buy"), market.get("main_sell"),
                    market.get("up_count"), market.get("down_count"), market.get("flat_count"),
                    market.get("stock_count"), snapshot_time,
                ),
            )
            conn.commit()

    def upsert_stocks(self, trade_date: str, stock_df: pd.DataFrame) -> None:
        if stock_df is None or stock_df.empty:
            return
        atomic = ["zmbtdcje", "zmbddcje", "zmbzdcje", "zmbxdcje", "zmstdcje", "zmsddcje", "zmszdcje", "zmsxdcje"]
        cols = ["turnover", "pct_chg", "active_buy", "active_sell", "net_active", "main_buy", "main_sell", *atomic]
        rows = []
        for _, r in stock_df.iterrows():
            rows.append(
                (trade_date, str(r["stock_code"]), r.get("stock_name"),
                 *[(float(r[c]) if c in stock_df.columns and pd.notna(r.get(c)) else None) for c in cols])
            )
        placeholders = ",".join(["?"] * (3 + len(cols)))
        with self._connect() as conn:
            conn.executemany(
                f"INSERT OR REPLACE INTO stock_daily_v4(trade_date, stock_code, stock_name, {', '.join(cols)}) VALUES ({placeholders})",
                rows,
            )
            conn.commit()

    def upsert_sectors(self, trade_date: str, kind: str, sector_df: pd.DataFrame) -> None:
        if sector_df is None or sector_df.empty:
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM sector_daily_v4 WHERE trade_date=? AND kind=?", (trade_date, kind))
            rows = []
            for _, r in sector_df.iterrows():
                vals = [r.get(c) for c in SECTOR_COLUMNS]
                rows.append((trade_date, kind, *vals))
            placeholders = ",".join(["?"] * (2 + len(SECTOR_COLUMNS)))
            conn.executemany(
                f"INSERT OR REPLACE INTO sector_daily_v4(trade_date, kind, {', '.join(SECTOR_COLUMNS)}) VALUES ({placeholders})",
                rows,
            )
            conn.commit()

    def upsert_etfs(self, trade_date: str, etf_df: pd.DataFrame) -> None:
        if etf_df is None or etf_df.empty:
            return
        cols = ["etf_name", "exchange", "turnover", "turnover_pct", "pct_chg", "fd_share"]
        rows = []
        for _, r in etf_df.iterrows():
            rows.append((trade_date, str(r["etf_code"]),
                         *[(r.get(c) if pd.notna(r.get(c)) else None) for c in cols]))
        placeholders = ",".join(["?"] * (2 + len(cols)))
        with self._connect() as conn:
            conn.executemany(
                f"INSERT OR REPLACE INTO etf_daily_v4(trade_date, etf_code, {', '.join(cols)}) VALUES ({placeholders})",
                rows,
            )
            conn.commit()

    # ------------------------------------------------------------------ read
    def list_trading_days(self, limit: int = 5) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT trade_date FROM market_daily_v4 ORDER BY trade_date DESC LIMIT ?", (limit,)
            ).fetchall()
        return sorted(r["trade_date"] for r in rows)

    def get_market_series(self, days: int = 5) -> dict[str, Any]:
        td = self.list_trading_days(days)
        if not td:
            return {"trade_dates": [], "turnover_series": [], "net_active_series": [], "main_net_series": []}
        ph = ",".join("?" * len(td))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM market_daily_v4 WHERE trade_date IN ({ph}) ORDER BY trade_date", td
            ).fetchall()
        return {
            "trade_dates": td,
            "turnover_series": [{"trade_date": r["trade_date"], "value": r["turnover"]} for r in rows],
            "active_buy_series": [{"trade_date": r["trade_date"], "value": r["active_buy"] or 0} for r in rows],
            "active_sell_series": [{"trade_date": r["trade_date"], "value": r["active_sell"] or 0} for r in rows],
            "net_active_series": [{"trade_date": r["trade_date"], "value": r["net_active"] or 0} for r in rows],
            "main_net_series": [
                {"trade_date": r["trade_date"], "value": (r["main_buy"] or 0) - (r["main_sell"] or 0)} for r in rows
            ],
        }

    @staticmethod
    def _normalize_sector_sort(sort: str) -> str:
        return sort if sort in _SECTOR_SORTS else "turnover_pct_desc"

    @staticmethod
    def _sort_cards(items: list[dict[str, Any]], sort: str, name_key: str) -> None:
        field, desc = _SECTOR_SORTS.get(sort, ("turnover_pct", True))

        def key(it: dict[str, Any]) -> tuple:
            v = it.get(field)
            if v is None:
                return (1, 0.0, it.get(name_key, ""))
            return (0, -v if desc else v, it.get(name_key, ""))

        items.sort(key=key)

    def get_sector_table(self, days: int = 5, sort: str = "turnover_pct_desc", kind: str = "sw_l3") -> dict[str, Any]:
        if kind not in KINDS:
            kind = "sw_l3"
        sort = self._normalize_sector_sort(sort)
        td = self.list_trading_days(days)
        if not td:
            return {"days": days, "sort": sort, "kind": kind, "trade_dates": [], "columns": []}
        ph = ",".join("?" * len(td))
        with self._connect() as conn:
            df = pd.read_sql_query(
                f"SELECT * FROM sector_daily_v4 WHERE kind=? AND trade_date IN ({ph})",
                conn, params=(kind, *td),
            )
        dates_new_to_old = list(reversed(td))
        columns: list[dict[str, Any]] = []
        for d in dates_new_to_old:
            sub = df[df["trade_date"] == d] if not df.empty else df
            cards: list[dict[str, Any]] = []
            for _, r in sub.iterrows():
                main_net = (float(r["main_buy"] or 0) - float(r["main_sell"] or 0))
                cards.append({
                    "sector_code": str(r["sector_code"]),
                    "sector_name": str(r["sector_name"]),
                    "sector_path": r["sector_path"],
                    "turnover": float(r["turnover"] or 0),
                    "turnover_pct": _f(r["turnover_pct"]),
                    "active_buy": _f(r["active_buy"]),
                    "active_sell": _f(r["active_sell"]),
                    "buy_pct": _f(r["buy_pct"]),
                    "sell_pct": _f(r["sell_pct"]),
                    "net_value": _f(r["net_active"]),
                    "net_active": _f(r["net_active"]),
                    "net_pct": _f(r["net_pct"]),
                    "main_buy": _f(r["main_buy"]),
                    "main_sell": _f(r["main_sell"]),
                    "main_net": main_net,
                    "up_count": int(r["up_count"] or 0),
                    "down_count": int(r["down_count"] or 0),
                    "up_ratio": _f(r["up_ratio"]),
                    "down_ratio": _f(r["down_ratio"]),
                    "stock_count": int(r["stock_count"] or 0),
                })
            self._sort_cards(cards, sort, "sector_name")
            for rank, c in enumerate(cards, start=1):
                c["rank"] = rank
            columns.append({"trade_date": d, "sectors": cards})
        return {"days": days, "sort": sort, "kind": kind, "trade_dates": dates_new_to_old, "columns": columns}

    def get_sector_charts(self, days: int = 5, kind: str = "sw_l3") -> list[dict[str, Any]]:
        if kind not in KINDS:
            kind = "sw_l3"
        td = self.list_trading_days(days)
        if not td:
            return []
        ph = ",".join("?" * len(td))
        with self._connect() as conn:
            df = pd.read_sql_query(
                f"SELECT * FROM sector_daily_v4 WHERE kind=? AND trade_date IN ({ph}) ORDER BY sector_code, trade_date",
                conn, params=(kind, *td),
            )
        out = []
        if df.empty:
            return out
        for (code, name), grp in df.groupby(["sector_code", "sector_name"]):
            g = grp.set_index("trade_date").reindex(td)
            out.append({
                "sector_code": code, "sector_name": name,
                "turnover_series": [{"trade_date": d, "value": _num(g, d, "turnover")} for d in td],
                "net_active_series": [{"trade_date": d, "value": _num(g, d, "net_active")} for d in td],
                "main_net_series": [
                    {"trade_date": d, "value": _num(g, d, "main_buy") - _num(g, d, "main_sell")} for d in td
                ],
            })
        return out

    def get_sector_stocks(self, sector_code: str, days: int = 5, sort: str = "turnover_pct_desc", kind: str = "sw_l3") -> dict[str, Any]:
        if kind not in KINDS:
            kind = "sw_l3"
        td = self.list_trading_days(days)
        base = {"sector_code": sector_code, "sector_name": sector_code, "days": days, "sort": sort, "kind": kind, "trade_dates": [], "columns": []}
        if not td:
            return base
        ph = ",".join("?" * len(td))
        with self._connect() as conn:
            meta = conn.execute(
                "SELECT sector_name FROM sector_stock_map_v4 WHERE kind=? AND sector_code=? LIMIT 1", (kind, sector_code)
            ).fetchone() or conn.execute(
                "SELECT sector_name FROM sector_catalog_v4 WHERE kind=? AND sector_code=? LIMIT 1", (kind, sector_code)
            ).fetchone()
            df = pd.read_sql_query(
                f"""SELECT s.* FROM stock_daily_v4 s
                    INNER JOIN sector_stock_map_v4 m ON m.stock_code=s.stock_code AND m.kind=? AND m.sector_code=?
                    WHERE s.trade_date IN ({ph}) ORDER BY s.stock_code, s.trade_date""",
                conn, params=(kind, sector_code, *td),
            )
        sector_name = meta["sector_name"] if meta else sector_code
        totals: dict[str, dict[str, float]] = {}
        if not df.empty:
            for d, grp in df.groupby("trade_date"):
                totals[str(d)] = {"turnover": float(grp["turnover"].fillna(0).sum())}
        dates_new_to_old = list(reversed(td))
        columns = []
        for d in dates_new_to_old:
            sub = df[df["trade_date"] == d] if not df.empty else df
            tot = totals.get(d, {"turnover": 0.0})
            stocks = []
            for _, r in sub.iterrows():
                turnover = float(r["turnover"] or 0)
                main_net = float(r["main_buy"] or 0) - float(r["main_sell"] or 0)
                stocks.append({
                    "stock_code": str(r["stock_code"]),
                    "stock_name": str(r["stock_name"] or ""),
                    "turnover": turnover,
                    "turnover_pct": (turnover / tot["turnover"]) if tot["turnover"] > 0 else None,
                    "pct_chg": _f(r["pct_chg"]),
                    "net_value": _f(r["net_active"]),
                    "net_active": _f(r["net_active"]),
                    "main_net": main_net,
                })
            _sort_stocks(stocks, sort)
            for rank, s in enumerate(stocks, start=1):
                s["rank"] = rank
            columns.append({"trade_date": d, "stocks": stocks})
        return {"sector_code": sector_code, "sector_name": sector_name, "days": days, "sort": sort, "kind": kind, "trade_dates": dates_new_to_old, "columns": columns}

    def get_stock_industries(self, stock_code: str) -> dict[str, Any]:
        """个股四套行业归属。"""
        out: dict[str, Any] = {}
        with self._connect() as conn:
            for kind in KINDS:
                r = conn.execute(
                    "SELECT sector_code, sector_name, sector_path FROM sector_stock_map_v4 WHERE kind=? AND stock_code=? LIMIT 1",
                    (kind, stock_code),
                ).fetchone()
                out[kind] = {"sector_code": r["sector_code"], "sector_name": r["sector_name"], "sector_path": r["sector_path"]} if r else None
        return out

    def get_stock_series(self, stock_code: str, days: int = 5) -> dict[str, Any]:
        td = self.list_trading_days(days)
        industries = self.get_stock_industries(stock_code)
        if not td:
            return {"stock_code": stock_code, "stock_name": stock_code, "days": days, "industries": industries, "trade_dates": [], "series": []}
        ph = ",".join("?" * len(td))
        with self._connect() as conn:
            df = pd.read_sql_query(
                f"SELECT * FROM stock_daily_v4 WHERE stock_code=? AND trade_date IN ({ph}) ORDER BY trade_date DESC",
                conn, params=(stock_code, *td),
            )
        name = str(df.iloc[0]["stock_name"]) if not df.empty and pd.notna(df.iloc[0]["stock_name"]) else stock_code
        series = [{
            "trade_date": str(r["trade_date"]),
            "turnover": _f(r["turnover"]),
            "pct_chg": _f(r["pct_chg"]),
            "active_buy": _f(r["active_buy"]),
            "active_sell": _f(r["active_sell"]),
            "net_active": _f(r["net_active"]),
            "main_buy": _f(r["main_buy"]),
            "main_sell": _f(r["main_sell"]),
            "main_net": (float(r["main_buy"] or 0) - float(r["main_sell"] or 0)),
        } for _, r in df.iterrows()]
        return {"stock_code": stock_code, "stock_name": name, "days": days, "industries": industries, "trade_dates": list(reversed(td)), "series": series}

    def get_etf_table(self, days: int = 5, sort: str = "turnover_pct_desc") -> dict[str, Any]:
        td = self.list_trading_days(days)
        if not td:
            return {"days": days, "sort": sort, "trade_dates": [], "columns": []}
        ph = ",".join("?" * len(td))
        with self._connect() as conn:
            df = pd.read_sql_query(f"SELECT * FROM etf_daily_v4 WHERE trade_date IN ({ph})", conn, params=td)
        dates_new_to_old = list(reversed(td))
        columns = []
        sort_field = "turnover" if sort in ("turnover_desc", "turnover_asc") else "turnover_pct"
        desc = not sort.endswith("_asc")
        for d in dates_new_to_old:
            sub = df[df["trade_date"] == d] if not df.empty else df
            items = [{
                "etf_code": str(r["etf_code"]), "etf_name": str(r["etf_name"] or ""),
                "turnover": float(r["turnover"] or 0), "turnover_pct": _f(r["turnover_pct"]),
                "pct_chg": _f(r["pct_chg"]), "fd_share": _f(r["fd_share"]),
            } for _, r in sub.iterrows()]
            items.sort(key=lambda x: (x.get(sort_field) is None, -(x.get(sort_field) or 0) if desc else (x.get(sort_field) or 0)))
            for rank, it in enumerate(items, start=1):
                it["rank"] = rank
            columns.append({"trade_date": d, "etfs": items})
        return {"days": days, "sort": sort, "trade_dates": dates_new_to_old, "columns": columns}

    def get_etf_series(self, etf_code: str, days: int = 5) -> dict[str, Any]:
        td = self.list_trading_days(days)
        if not td:
            return {"etf_code": etf_code, "etf_name": etf_code, "days": days, "trade_dates": [], "series": []}
        ph = ",".join("?" * len(td))
        with self._connect() as conn:
            df = pd.read_sql_query(
                f"SELECT * FROM etf_daily_v4 WHERE etf_code=? AND trade_date IN ({ph}) ORDER BY trade_date DESC",
                conn, params=(etf_code, *td),
            )
        name = str(df.iloc[0]["etf_name"]) if not df.empty and pd.notna(df.iloc[0]["etf_name"]) else etf_code
        series = [{
            "trade_date": str(r["trade_date"]), "turnover": _f(r["turnover"]),
            "turnover_pct": _f(r["turnover_pct"]), "pct_chg": _f(r["pct_chg"]), "fd_share": _f(r["fd_share"]),
        } for _, r in df.iterrows()]
        return {"etf_code": etf_code, "etf_name": name, "days": days, "trade_dates": list(reversed(td)), "series": series}


def _f(v: Any) -> float | None:
    return float(v) if v is not None and pd.notna(v) else None


def _num(g: pd.DataFrame, d: str, col: str) -> float:
    try:
        v = g.loc[d, col]
        return float(v) if pd.notna(v) else 0.0
    except (KeyError, TypeError):
        return 0.0


def _sort_stocks(items: list[dict[str, Any]], sort: str) -> None:
    # 成份股：成交占比 / 涨跌幅（up_ratio→pct_chg 降序、down_ratio→pct_chg 升序）/ 净额
    mapping = {
        "turnover_pct_desc": ("turnover_pct", True),
        "turnover_pct_asc": ("turnover_pct", False),
        "up_ratio_desc": ("pct_chg", True),
        "down_ratio_desc": ("pct_chg", False),
        "net_desc": ("net_active", True),
        "net_asc": ("net_active", False),
    }
    field, desc = mapping.get(sort, ("turnover_pct", True))

    def key(it: dict[str, Any]) -> tuple:
        v = it.get(field)
        if v is None:
            return (1, 0.0, it.get("stock_code", ""))
        return (0, -v if desc else v, it.get("stock_code", ""))

    items.sort(key=key)
