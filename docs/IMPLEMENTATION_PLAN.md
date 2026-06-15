# 实现方案：历史落库 + Web 看板 + 管理页

> 版本：**v3.5**  
> 前置：[REQUIREMENTS.md](./REQUIREMENTS.md)  
> 必盈接口：[BIYING_API.md](./BIYING_API.md)

**v3.5 变更（待实施）**：管理页 **区间补数**（开始+结束必填，相等=单日）；`fetch_by_range.py`；`transaction` / 日 K **`st/et` 按股拉取**；不跳过已有数据。

**v3.4 变更**：看板板块默认 **申万二级（131）**；`migrate_sectors_to_l2.py` / `build_sector_mapping.py` / `rebuild_sector_aggregates.py`；管理页 **交易日校验** + **任务取消**；sector 僵尸行清理；Excel UTF-8 BOM 导出。

---

## 1. 总体架构

```text
┌──────────────────────────────────────────────────────────────────────────┐
│  采集层                                                                    │
│  fetch_by_daily.py / fetch_by_date.py / fetch_by_range.py                │
│       │                                                                   │
│       └──► history_store.py ──► SQLite data/history.db                   │
│              ▲                                                            │
│  scheduler.py（APScheduler，默认 21:35，交易日/自然日可配）                  │
│  trading_calendar.py（PMC SSE 为主，必盈日 K 校验）                        │
└──────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
                          data/history.db
              market / sector / stock / etf_daily
              fetch_jobs / app_settings
                                     │
                                     ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  API 层  FastAPI  /api/*  +  /api/admin/*                               │
└──────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  展示层  dashboard/*.html + ECharts + format.js                             │
│  页面1–6 看板 │ 页面7 admin.html 管理                                      │
└──────────────────────────────────────────────────────────────────────────┘
```

**技术选型**

| 层 | 选型 |
|----|------|
| 存储 | SQLite `data/history.db` |
| API | FastAPI + uvicorn |
| 图表 | ECharts 5（CDN） |
| 前端 | 多页 MPA + 原生 JS |
| ETF 大表 | 分页 API + 表格分页 / 虚拟滚动 |
| 调度 | **APScheduler**（进程内，随 `serve_dashboard.py` 启动） |
| 任务队列 | 单 worker 线程 + `fetch_jobs` 状态表 |

**版本变更摘要**

| 项 | v3.3 | v3.4 |
|----|------|------|
| 看板板块 | 申万一级 31 | **申万二级 131** |
| 默认 `--level` | `l1` | **`l2`** |
| L1→L2 迁移 | — | **`migrate_sectors_to_l2.py`** |
| 手动补数 | 单日 | **起止日期必填**；区间 ≤30 交易日；**不跳过已有** |
| 任务取消 | — | **`POST .../cancel`** |
| sector 僵尸行 | 不删除 | **upsert/rebuild 后 DELETE  orphan** |
| Excel 导出 | 无 BOM 乱码 | **utf-8-sig** |
| 表头 sticky | `top:48px` 压盖 | **`.table-wrap` + `top:0`** |

---

## 2. 目录结构

```text
Trend_Analysis/
├── scripts/
│   ├── fetch_by_daily.py       # 最新可用 trade_date
│   ├── fetch_by_date.py        # 指定单日（区间=1 日时复用）
│   ├── fetch_by_range.py       # 区间补数（管理页主入口，待实施）
│   ├── sector_config.py        # DEFAULT_SECTOR_LEVEL=l2
│   ├── build_sector_mapping.py # 仅拉 hszg/gg 映射（L2 迁移用）
│   ├── migrate_sectors_to_l2.py # L1 库 → L2 重聚合（无需重打 API）
│   ├── rebuild_sector_aggregates.py  # 重算 sector + 清理僵尸行
│   ├── history_store.py
│   ├── scheduler.py            # APScheduler，默认 21:35
│   ├── trading_calendar.py     # PMC SSE + 必盈校验 CLI
│   └── serve_dashboard.py      # uvicorn + 启动调度器
├── api/
│   ├── server.py
│   ├── queries.py
│   ├── schemas.py
│   └── admin.py                # 管理 API
├── dashboard/
│   ├── index.html … etf-charts.html
│   ├── admin.html              # 页面 7
│   └── static/js/… admin.js
├── data/
│   ├── history.db
│   └── exports/                # 按日 ZIP（gitignore）
├── logs/jobs/                  # 任务日志（gitignore）
└── docs/
```

---

## 3. Phase 2：SQLite Schema

```sql
CREATE TABLE IF NOT EXISTS market_daily (
    trade_date    TEXT PRIMARY KEY,
    turnover      REAL NOT NULL,
    active_buy    REAL,
    active_sell   REAL,
    net_active    REAL,
    stock_count   INTEGER,
    snapshot_time TEXT
);

CREATE TABLE IF NOT EXISTS sector_daily (
    trade_date     TEXT NOT NULL,
    sector_code    TEXT NOT NULL,
    sector_name    TEXT NOT NULL,
    turnover       REAL NOT NULL,
    turnover_pct   REAL,
    active_buy     REAL,
    active_sell    REAL,
    net_active     REAL,
    stock_count    INTEGER,
    PRIMARY KEY (trade_date, sector_code)
);

CREATE TABLE IF NOT EXISTS stock_daily (
    trade_date    TEXT NOT NULL,
    stock_code    TEXT NOT NULL,
    stock_name    TEXT,
    sector_code   TEXT,
    sector_name   TEXT,
    turnover      REAL,
    active_buy    REAL,
    active_sell   REAL,
    net_active    REAL,
    PRIMARY KEY (trade_date, stock_code)
);

-- 新增：ETF 日明细
CREATE TABLE IF NOT EXISTS etf_daily (
    trade_date     TEXT NOT NULL,
    etf_code       TEXT NOT NULL,
    etf_name       TEXT,
    exchange       TEXT,
    turnover       REAL NOT NULL,
    turnover_pct   REAL,          -- etf.turnover / market.turnover
    PRIMARY KEY (trade_date, etf_code)
);

CREATE INDEX IF NOT EXISTS idx_sector_daily_date ON sector_daily(trade_date);
CREATE INDEX IF NOT EXISTS idx_stock_daily_sector ON stock_daily(trade_date, sector_code);
CREATE INDEX IF NOT EXISTS idx_etf_daily_date ON etf_daily(trade_date);
CREATE INDEX IF NOT EXISTS idx_etf_daily_code ON etf_daily(etf_code, trade_date);

-- 采集任务（管理页状态 / 报错）
CREATE TABLE IF NOT EXISTS fetch_jobs (
    job_id         TEXT PRIMARY KEY,
    trade_date     TEXT NOT NULL,
    trigger_type   TEXT NOT NULL,          -- scheduled | manual
    status         TEXT NOT NULL,          -- pending | running | success | failed | cancelled
    started_at     TEXT,
    finished_at    TEXT,
    duration_sec   REAL,
    progress       TEXT,
    error_message  TEXT,
    log_path       TEXT,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fetch_jobs_date ON fetch_jobs(trade_date);
CREATE INDEX IF NOT EXISTS idx_fetch_jobs_status ON fetch_jobs(status);

-- 应用配置（定时等）
CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- 初始 INSERT: schedule_time=21:35, schedule_run_mode=trading_day, ...

-- 交易日历（本地缓存，非必盈独立 API）
CREATE TABLE IF NOT EXISTS trading_calendar (
    trade_date   TEXT PRIMARY KEY,
    is_trading   INTEGER NOT NULL DEFAULT 1,
    source       TEXT NOT NULL DEFAULT 'biying_kline',
    updated_at   TEXT NOT NULL
);
```

### 3.1 history_store.py 接口

```python
class HistoryStore:
    def upsert_market(self, row: dict) -> None: ...
    def upsert_sectors(self, rows: list[dict]) -> None: ...
    def upsert_stocks(self, rows: list[dict]) -> None: ...
    def upsert_etfs(self, rows: list[dict]) -> None: ...      # 新增

    def get_trading_days(self, n: int = 5) -> list[str]: ...
    def get_market_series(self, days: int = 5) -> dict: ...
    def get_sector_table(self, days: int = 5, sort: str = "pct_desc") -> dict: ...
    def get_sector_charts(self, days: int = 5) -> list[dict]: ...
    def get_sector_stocks(self, sector_code: str, days: int = 5) -> dict: ...
    def get_etf_table(self, days: int = 5, sort: str = "pct_desc",
                      page: int = 1, page_size: int = 50,
                      q: str = "") -> dict: ...              # 新增，分页+搜索
    def get_etf_charts(self, days: int = 5, sort: str = "pct_desc",
                       top: int | None = None, q: str = "") -> list[dict]: ...

    def get_data_calendar(self) -> list[dict]: ...           # 各日完整度
    def export_date_zip(self, trade_date: str) -> Path: ...   # 生成 ZIP

    def create_job(self, trade_date: str, trigger: str) -> str: ...
    def update_job(self, job_id: str, **fields) -> None: ...
    def list_jobs(self, limit: int = 50) -> list[dict]: ...
    def get_job(self, job_id: str) -> dict: ...

    def get_settings(self) -> dict: ...
    def set_settings(self, settings: dict) -> None: ...
```

### 3.2 trading_calendar.py（PMC 为主）

**主方案**：`pandas_market_calendars.get_calendar("SSE")`（与 `XSHG` 等价，覆盖沪深 A 股休市）。

```python
from trading_calendar import (
    is_trading_day,
    get_recent_trading_days,
    should_run_scheduled_task,
    sync_pmc_to_sqlite,
    compare_with_biying,
)
```

| 函数 | 说明 |
|------|------|
| `is_trading_day(date)` | 是否 A 股交易日 |
| `get_recent_trading_days(n, end=...)` | 看板近 N 日 |
| `should_run_scheduled_task(run_mode)` | `trading_day` / `calendar_day` |
| `sync_pmc_to_sqlite(db, st, et)` | 可选写入 `trading_calendar` 表 |
| `compare_with_biying(licence, st, et)` | 管理页校验 |

**CLI**

```bash
python3 scripts/trading_calendar.py recent --days 5
python3 scripts/trading_calendar.py verify --start 2026-06-01 --end 2026-06-15
python3 scripts/trading_calendar.py sync-db data/history.db --start 2026-01-01 --end 2026-12-31
```

**必盈日 K**：仅 `verify` / 兜底；日常调度 **不调用** 必盈 API。

**刷新策略**

- 无需定时 sync API；PMC 本地计算。
- 可选 `sync-db` 写入 SQLite 供管理页日历展示；服务启动时 sync 当年范围即可。

### 3.3 fetch_by_date.py（指定单日采集）

```bash
python3 scripts/fetch_by_date.py --date 2026-06-12 --no-all-turnover --job-id <uuid>
```

| 参数 | 说明 |
|------|------|
| `--date` | 目标 `trade_date`（YYYY-MM-DD） |
| `--job-id` | 关联 `fetch_jobs`，更新 progress / log |

逻辑差异：

```text
买卖：history/transaction/{code}?st=YYYYMMDD&et=YYYYMMDD
成交：若 ssjy 仅当日，则日 K st/et；或标记 turnover 缺失
ETF：fd/real/time 仅当日 → 历史日 ETF skip 并写 job 警告
聚合 → UPSERT 四表（与 fetch_by_daily 相同结构）
```

### 3.3b fetch_by_range.py（区间补数，v3.5）

```bash
python3 scripts/fetch_by_range.py --start 2026-06-01 --end 2026-06-12 --job-id <uuid>
# 单日等价
python3 scripts/fetch_by_range.py --start 2026-06-12 --end 2026-06-12
```

| 参数 | 说明 |
|------|------|
| `--start` | 开始日期（必填） |
| `--end` | 结束日期（必填） |
| `--force` | 单日非交易日时强制（区间边界休市不 force） |
| `--job-id` | 关联 `fetch_jobs` |

**流程**

```text
① validate: start/end 必填, start≤end, end≤today, 1≤交易日数≤30
② days = get_trading_days(start, end)   # PMC SSE
③ 若 days 仅 1 日且 = today → 委托 fetch_by_daily
④ 否则按股批量拉取（核心优化，调用量 ≈ 5200×2，与区间长度弱相关）：
     transaction?st=min(days)&et=max(days)  → 按 trade_date 拆分买卖
     kline?st=&et=                           → 按 trade_date 拆分成交额
⑤ 若 days 含 today → today 额外走 fetch_by_daily 或 ssjy 覆盖成交
⑥ upsert_stock_daily_rows → rebuild_aggregates_for_dates(days)
⑦ 含 today 且未 --no-etf → ETF 当日 upsert
⑧ **不跳过** days 中已有完整数据的日期（全量 UPSERT 覆盖）
```

**进度**：`progress` 字段 `stocks 1200/5208`；日志每 200 股一行。

**取消**：循环内检查 `fetch_jobs.status == cancelled`。

**by_common 扩展**（实施时）：

```python
def fetch_fund_flow_history(licence, code, *, lt=None, st=None, et=None):
    # lt 与 st/et 二选一；区间补数用 st/et（YYYYMMDD）
```

### 3.4 scheduler.py

```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

def start_scheduler(store: HistoryStore):
    settings = store.get_settings()
    if not settings["schedule_enabled"]:
        return
    hour, minute = settings["schedule_time"].split(":")
    scheduler.add_job(
        run_scheduled_fetch,
        CronTrigger(hour=int(hour), minute=int(minute), timezone="Asia/Shanghai"),
        id="daily_fetch",
        replace_existing=True,
    )
```

- `serve_dashboard.py` 启动时 `start_scheduler()`。
- 管理页修改后 `PUT /api/admin/settings` → 持久化 + **热重载** cron。
- `schedule_run_mode=trading_day`（默认）：`should_run_today()` 为 false 时跳过并写 job 记录 `skipped_non_trading_day`。
- `schedule_run_mode=calendar_day`：每天到点都跑。

### 3.5 任务执行模型

```text
POST /api/admin/fetch  ──► 创建 fetch_jobs(pending)
         │
         ▼
BackgroundTasks / 线程池 worker（max_workers=1）
         │
         ├─ status=running, log → logs/jobs/{job_id}.log
         ├─ subprocess fetch_by_range.py / fetch_by_date.py
         ├─ 成功 → status=success
         └─ 异常 → status=failed, error_message=str(exc)
```

- 前端每 **2s** 轮询 `GET /api/admin/jobs?limit=20` 或 `GET /api/admin/jobs/{id}`。
- 日志区：`GET /api/admin/jobs/{id}/log?tail=200` 返回末尾 N 行。

### 3.6 fetch_by_daily.py 扩展

采集完成后：

```python
store = HistoryStore(DATA_DIR / "history.db")

# 已有
store.upsert_market(market_row)
store.upsert_sectors(sector_ff_df)   # 含 turnover + 买卖
store.upsert_stocks(stock_df)

# 新增：ETF
etf_rows = etf_df.assign(
    turnover_pct=etf_df["turnover"] / market_row["turnover"]
)
store.upsert_etfs(etf_rows)
```

### 3.8 sector 僵尸行清理

`upsert_snapshot` 与 `rebuild_aggregates_for_dates` 在写入 `sector_daily` 后执行：

```sql
DELETE FROM sector_daily
WHERE trade_date = ? AND sector_code NOT IN (本次聚合的 code 列表);
```

CLI：

```bash
python3 scripts/rebuild_sector_aggregates.py
```

### 3.9 backfill_history.py（近 5 日）

```bash
python3 scripts/backfill_history.py --days 5 --no-all-turnover
```

```text
① 逐股 history/transaction?lt=5  → stock_daily（买卖；成交若当日 cron 已有则保留）
② 按日聚合 → sector_daily, market_daily
③ ETF：必盈 fd/real/time 仅当日；5 日 ETF 历史依赖：
     - 方案 A（推荐）：连续 5 天 cron 自然积累 etf_daily
     - 方案 B：若必盈后续提供 ETF 日 K，再扩展 backfill
④ 不足 5 日时 backfill 写已有天数，看板显示提示
```

**说明**：ETF 无 `history/transaction`，**5 日 ETF 数据主要靠每日 cron 积累**；A 股买卖可通过 `lt=5` 一次回填。

### 3.8 定时调度（默认 21:35，默认交易日）

由 **`scheduler.py` + `app_settings`** 驱动，不再依赖系统 crontab 为唯一入口。

| 键 | 默认值 |
|----|--------|
| `schedule_time` | **`21:35`** |
| `schedule_timezone` | `Asia/Shanghai` |
| `schedule_enabled` | `true` |
| `schedule_run_mode` | **`trading_day`**（可选 `calendar_day`） |

管理页修改时刻 → `PUT /api/admin/settings` → 热重载 APScheduler。

可选：系统 cron 仅负责 **开机自启服务**：

```cron
@reboot cd ~/Trend_Analysis && .venv/bin/python scripts/serve_dashboard.py
```

连续 **5 个交易日** 采集后，看板六页数据齐全。

---

## 4. Phase 3：API 设计

所有接口默认 `days=5`，金额单位 **元**。

### 4.1 GET /api/meta/trading-days

```json
{ "days_requested": 5, "days_actual": 5, "trade_dates": ["2026-06-09", "..."] }
```

### 4.2 GET /api/market?days=5

页面 1 用。

```json
{
  "turnover_series": [{"trade_date": "2026-06-13", "value": 2.03e12}],
  "active_buy_series": [...],
  "active_sell_series": [...]
}
```

### 4.3 GET /api/sectors/table?days=5&sort=pct_desc

页面 2 用。`sort`: `pct_desc` | `pct_asc` | `amount_desc` | `name_asc`。

### 4.4 GET /api/sectors/charts?days=5&sort=pct_desc

页面 3 用。返回 **131** 个申万二级板块 × 三序列。

### 4.5 GET /api/sectors/{sector_code}/stocks?days=5

页面 4 用。

### 4.6 GET /api/etf/table?days=5&sort=pct_desc&page=1&page_size=50&q=

页面 5 用。**必须分页**。

```json
{
  "meta": { "total": 1480, "page": 1, "page_size": 50 },
  "columns": ["2026-06-09", "2026-06-10", "..."],
  "rows": [
    {
      "etf_code": "510300",
      "etf_name": "沪深300ETF",
      "cells": [
        {"trade_date": "2026-06-13", "turnover": 4.68e9, "turnover_pct": 0.0023}
      ]
    }
  ]
}
```

### 4.7 GET /api/etf/charts?days=5&sort=pct_desc&top=50&q=

页面 6 用。默认 `top=50` 仅返回成交额 Top 50（可改 `top=` 或全量）。

```json
[
  {
    "etf_code": "510300",
    "etf_name": "沪深300ETF",
    "turnover_series": [{"trade_date": "...", "value": ...}]
  }
]
```

]

---

## 4b. Phase 3b：管理 API

前缀 `/api/admin`，需 **Admin 鉴权**（Header `X-Admin-Token` 或 Basic Auth）。

### 4b.1 GET /api/admin/settings

返回定时配置 + 下次预计执行时间。

```json
{
  "schedule_enabled": true,
  "schedule_time": "21:35",
  "schedule_timezone": "Asia/Shanghai",
  "schedule_run_mode": "trading_day",
  "next_run_at": "2026-06-16T21:35:00+08:00",
  "next_run_will_execute": true
```

`next_run_will_execute`：若下次触发日为非交易日且 mode=trading_day，则为 false 并给出 `next_trading_run_at`。

### 4b.2a POST /api/admin/calendar/verify

对比 PMC 与必盈日 K（调 `compare_with_biying`），返回 diff。

### 4b.2b POST /api/admin/calendar/sync-db

将 PMC 区间写入 `trading_calendar` 表（调 `sync_pmc_to_sqlite`）。

### 4b.2 PUT /api/admin/settings

更新定时配置；body 同 GET 字段子集；返回 200 并重载 scheduler。

### 4b.3 POST /api/admin/fetch

手动触发区间采集。**开始、结束日期均必填**。

```json
{ "start_date": "2026-06-01", "end_date": "2026-06-12", "force": false }
```

| 校验 | 响应 |
|------|------|
| 缺 `start_date` / `end_date` | 400 |
| `start_date > end_date` | 400 |
| `end_date > today` | 400 |
| 区间内 0 个交易日 | 400 |
| 区间内 > 30 个交易日 | 400 |
| `start==end` 且非交易日且 `force=false` | 400（与 v3.4 单日一致） |
| 已有 `running` 任务 | 409 |

**兼容**：旧字段 `trade_date` 可映射为 `start_date=end_date=trade_date`（过渡期）。

**fetch_jobs 扩展**（迁移）：

```sql
ALTER TABLE fetch_jobs ADD COLUMN end_date TEXT;
-- trade_date 存 start_date；end_date 缺省时等于 trade_date
```

任务列表展示：`start_date ~ end_date`（相等则只显示一天）。

### 4b.3a GET /api/admin/fetch-preview?start=&end=

返回区间预览（不落库、不启任务）：

```json
{
  "start_date": "2026-06-01",
  "end_date": "2026-06-12",
  "trading_day_count": 8,
  "trading_days": ["2026-06-01", "..."],
  "valid": true,
  "error": null
}
```

前端在日期变更时 debounce 调用，展示「共 N 个交易日」。

### 4b.3b GET /api/admin/trading-day?date=

返回 `{ "trade_date", "is_trading_day" }`，供管理页日期提示。

### 4b.3c POST /api/admin/jobs/{job_id}/cancel

取消 `pending` / `running` 任务，终止子进程，状态 `cancelled`。

### 4b.4 GET /api/admin/jobs

Query: `limit`, `status`, `trade_date`。

### 4b.5 GET /api/admin/jobs/{job_id}

含 `error_message`、`progress`、`log_tail`（最后 200 行）。

### 4b.6 GET /api/admin/jobs/{job_id}/log

Query: `tail=500`；返回纯文本或 JSON `{ "lines": [...] }`。

### 4b.7 POST /api/admin/jobs/{job_id}/retry

失败任务重试（新建 job，同 trade_date）。

### 4b.8 GET /api/admin/calendar

数据日历：已落库日期 + 完整度。

```json
{
  "dates": [
    {
      "trade_date": "2026-06-12",
      "completeness": "full",
      "market": true,
      "sector_count": 31,
      "stock_count": 5198,
      "etf_count": 1475,
      "last_updated": "2026-06-13T05:12:00+08:00"
    }
  ]
}
```

`completeness`: `full` | `partial` | `missing_etf` | `missing_flow`

### 4b.9 GET /api/admin/export/{trade_date}

响应 `application/zip`，文件名 `trend_analysis_{trade_date}.zip`。

ZIP 内容：

```text
market_daily.csv
sector_daily.csv
stock_daily.csv
etf_daily.csv
meta.json
```

ZIP 内 CSV 使用 **UTF-8 BOM**（`utf-8-sig`），Excel 双击打开中文不乱码。

---

## 5. Phase 3：前端设计

### 5.1 导航栏（共用 nav.js）

```html
<nav>
  <a href="/">概览</a>
  <a href="/sectors-table.html">板块表格</a>
  <a href="/sectors-charts.html">板块图表</a>
  <a href="/etf-table.html">ETF 表格</a>
  <a href="/etf-charts.html">ETF 图表</a>
  <a href="/admin.html">管理</a>
</nav>
```

### 5.2 页面线框

#### 页面 1 — 全 A 概览

```text
┌────────────────────────────────────────────┐
│ 近 5 日 A 股成交额    [ECharts 柱图]         │
│ 近 5 日 A 股买入额    [ECharts 柱图]         │
│ 近 5 日 A 股卖出额    [ECharts 柱图]         │
│ 脚注：当前展示 N 个交易日                    │
└────────────────────────────────────────────┘
```

#### 页面 5 — ETF 表格

```text
搜索: [________]  排序: [占比↓▼]   第 1/30 页 [上一页][下一页]

| 代码 | 名称 | 06-09 额 | 06-09 % | … | 06-13 额 | 06-13 % |
```

#### 页面 6 — ETF 图表

```text
筛选: [Top 50▼] [Top 100] [全部]   搜索: [________]

▼ 510300 沪深300ETF
    └─ 近 5 日成交额 [柱图]
▶ 159915 创业板ETF
```

▶ 159915 创业板ETF
```

#### 页面 7 — 管理

```text
┌─ 定时更新 ─────────────────────────────────────────────┐
│ 启用 [x]   执行时间 [21:35]   时区 Asia/Shanghai        │
│ 执行日类型 (•) 交易日  ( ) 自然日          [保存配置]    │
│ 上次定时：2026-06-13 21:35  成功  trade_date=2026-06-13 │
│ [同步交易日历到 DB]  数据源: pandas_market_calendars SSE │
└────────────────────────────────────────────────────────┘

┌─ 手动补数 ─────────────────────────────────────────────┐
│ 开始日期 [2026-06-01 📅]  结束日期 [2026-06-12 📅]      │
│ 预览：共 8 个交易日（06-01 ~ 06-12）                    │
│ [ ] 强制补数（仅单日非交易日）          [开始更新]      │
└────────────────────────────────────────────────────────┘

┌─ 数据日历 ─────────────────────────────────────────────┐
│ [日历视图 | 列表视图]                                   │
│  6月: 10✅ 11✅ 12⚠ 13✅ ...                           │
│  点击日期 → 下载 | 重新采集                              │
└────────────────────────────────────────────────────────┘

┌─ 按日下载 ─────────────────────────────────────────────┐
│ 日期 [2026-06-12 ▼]                   [下载 ZIP]        │
└────────────────────────────────────────────────────────┘

┌─ 任务记录 ─────────────────────────────────────────────┐
│ ID       日期范围              触发   状态    耗时   操作 │
│ abc…    06-01~06-12      手动   失败   26m  [日志][重试]│
│ def…    06-13            定时   成功   18m  [日志]      │
│ ▼ 错误：HTTP 429 …                                     │
│ ▼ 日志尾部：…                                          │
└────────────────────────────────────────────────────────┘
```

**admin.js 要点**

- 保存配置 → `PUT /api/admin/settings`
- 手动补数 → `GET /api/admin/fetch-preview` + `POST /api/admin/fetch` → 轮询 jobs
- 日历 → `GET /api/admin/calendar`；列表按 `trade_date` 降序
- 下载 → `window.location = /api/admin/export/{date}`
- sector 僵尸行 → `python3 scripts/rebuild_sector_aggregates.py`

### 5.3 图表布局

ECharts `grid.containLabel: true`，Y 轴金额（如 `25000.0亿`）自动留足左侧边距，避免裁切。

### 5.4 format.js（万 / 千万 / 亿）

```javascript
export function formatAmount(yuan) {
  const abs = Math.abs(yuan);
  if (abs >= 1e8) return { value: yuan / 1e8, unit: '亿', text: `${(yuan/1e8).toFixed(2)} 亿` };
  if (abs >= 1e7) return { value: yuan / 1e7, unit: '千万', text: `${(yuan/1e7).toFixed(2)} 千万` };
  if (abs >= 1e4) return { value: yuan / 1e4, unit: '万', text: `${(yuan/1e4).toFixed(2)} 万` };
  return { value: yuan, unit: '元', text: `${yuan.toFixed(0)} 元` };
}
```

### 5.5 懒加载策略

| 页面 | 策略 |
|------|------|
| 3 板块图 | Accordion 展开时 `echarts.init`；收起 `dispose` |
| 4 个股图 | 同页面 3；成份股 ~50–200，可接受 |
| 6 ETF 图 | **默认 Top 50**；选「全部」时分批渲染或滚动进入视口再 init |

### 5.6 页面跳转参数

| 页面 | URL 示例 |
|------|----------|
| 3 | `sectors-charts.html?sector=sw1_bank&sort=pct_desc` |
| 4 | `sector-stocks.html?sector=sw1_bank` |
| 5 | `etf-table.html?sort=pct_desc&page=2&q=300` |
| 6 | `etf-charts.html?etf=510300&top=50` |

---

## 6. 依赖

```text
# requirements.txt 追加
fastapi>=0.110
uvicorn[standard]>=0.27
apscheduler>=3.10
pandas_market_calendars>=5.4.0

```html
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
```

---

## 7. 启动

```bash
source .venv/bin/activate
set -a && source .env && set +a

# 确保 history.db 有近 5 日数据
python3 scripts/fetch_by_daily.py --no-all-turnover   # 每日
# 或
python3 scripts/backfill_history.py --days 5 --no-all-turnover

python3 scripts/serve_dashboard.py
# http://127.0.0.1:8080
```

---

## 8. 实施顺序

| 步 | 任务 | 产出 |
|----|------|------|
| 1 | Schema + `history_store.py`（含 etf_daily） | DB 层 |
| 2 | `fetch_by_daily.py` UPSERT 四表 | 每日增量 |
| 3 | `backfill_history.py --days 5` | 买卖 5 日回填 |
| 4 | cron × 5 交易日 | ETF + 成交 5 日齐全 |
| 5 | API `/api/market` … `/api/etf/*` | 后端 |
| 6 | `format.js` + `charts.js` | 前端基础 |
| 7 | 页面 1 | 全 A 三图 |
| 8 | 页面 2、3、4 | 板块链路 |
| 9 | 页面 5、6 | ETF 表格 + 图 |
| 10 | `fetch_jobs` + `scheduler.py` + `fetch_by_date.py` | 任务基础设施 |
| 11 | 管理 API `/api/admin/*` | 后端 |
| 12 | 页面 7 `admin.html` | 管理 UI |
| 13 | 导航、样式、空态、验收 | 交付 |

---

## 9. 风险与对策

| 风险 | 对策 |
|------|------|
| ETF 无历史接口，5 日靠 cron | 文档说明；backfill 只填 A 股；ETF 满 5 天 cron 后可用 |
| 页面 5 1480 行卡顿 | 分页 API + 前端分页；禁止一次渲染全表 |
| 页面 6 1480 图内存爆炸 | 默认 Top 50 + 懒加载 |
| 买卖 vs 成交 trade_date 偏移 | 默认 21:35 采集 |
| 必盈无交易日历 API | 日 K 间接同步；见 BIYING_API.md §9 |
| 自然日模式非交易日空跑 | 管理页标注；job 可能 skipped 或 partial |
| 长任务浏览器超时 | 异步 job + 轮询，不阻塞 HTTP |
| 指定日 ETF 无法补 | job 警告 + calendar partial；文档说明 |
| Admin 误暴露 | 独立 token；/api/admin 中间件校验 |

---

## 10. 测试要点

| 用例 | 预期 |
|------|------|
| 页面 1 三图 | 均为 5 个柱子 |
| ETF table page=2 | 返回第 51–100 条 |
| ETF table q=300 | 过滤代码/名称含 300 |
| ETF charts top=50 | 仅 50 个 Accordion |
| formatAmount(2.5e8) | `2.50 亿` |
| 空库 | 全页「暂无数据，请先运行采集」 |
| PUT schedule_time=22:00 | next_run_at 更新 |
| schedule_run_mode=calendar_day | 周末也触发 |
| is_trading_day(春节) | false（来自 trading_calendar） |
| POST /api/admin/calendar/sync | 返回同步条数 > 0 |
| POST fetch 重复 running | 409 |
| export 无数据日期 | 404 |
| admin 无 token | 401 |

---

## 11. 与 Phase 1 关系

| 现有 | 变更 |
|------|------|
| CSV latest 文件 | 保留，作降级快照 |
| `etf_turnover_latest.csv` | 继续生成，并写入 `etf_daily` |
| `by_common.py` | 复用，不破坏现有 CLI |
