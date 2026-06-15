# 实现方案：历史落库 + Web 看板（六页面）

> 版本：**v3.1**  
> 前置：[REQUIREMENTS.md](./REQUIREMENTS.md)  
> 必盈接口：[BIYING_API.md](./BIYING_API.md)

---

## 1. 总体架构

```text
┌──────────────────────────────────────────────────────────────────────────┐
│  采集层                                                                    │
│  fetch_by_daily.py ──► CSV 快照 + history_store.upsert()                 │
│  backfill_history.py ──► 首次近 5 日回填（可选）                             │
└──────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
                          data/history.db (SQLite)
                     market / sector / stock / etf_daily
                                     │
                                     ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  API 层  FastAPI  /api/*                                                 │
└──────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  展示层  dashboard/*.html + ECharts + format.js                           │
│  页面1 概览 │ 2 板块表 │ 3 板块图 │ 4 个股 │ 5 ETF表 │ 6 ETF图              │
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

**相对 v3.0 的变更**

| 项 | v3.0 | v3.1 |
|----|------|------|
| 页面 1 买卖图 | 30 日 | **5 日**（与成交一致） |
| 历史深度 | 5 + 30 日 | **统一 5 日** |
| ETF 看板 | 不做 | **页面 5、6** |
| 回填脚本 | `--days 30` | **`--days 5`** |

---

## 2. 目录结构

```text
Trend_Analysis/
├── scripts/
│   ├── fetch_by_daily.py       # 扩展：写入 history.db（含 etf_daily）
│   ├── backfill_history.py     # --days 5
│   ├── history_store.py
│   └── serve_dashboard.py
├── api/
│   ├── server.py
│   ├── queries.py
│   └── schemas.py
├── dashboard/
│   ├── index.html              # 页面 1
│   ├── sectors-table.html      # 页面 2
│   ├── sectors-charts.html     # 页面 3
│   ├── sector-stocks.html      # 页面 4
│   ├── etf-table.html          # 页面 5
│   ├── etf-charts.html         # 页面 6
│   └── static/
│       ├── css/dashboard.css
│       └── js/{format,charts,api,nav,table}.js
├── data/
│   └── history.db
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
```

### 3.2 fetch_by_daily.py 扩展

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

### 3.3 backfill_history.py（近 5 日）

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

### 3.4 定时任务

```cron
35 21 * * 1-5 cd ~/Trend_Analysis && set -a && source .env && set +a && \
  .venv/bin/python scripts/fetch_by_daily.py --no-all-turnover >> logs/fetch.log 2>&1
```

连续 **5 个交易日** 后，六页面数据齐全。

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

页面 3 用。返回 31 板块 × 三序列。

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

### 5.3 format.js（万 / 千万 / 亿）

```javascript
export function formatAmount(yuan) {
  const abs = Math.abs(yuan);
  if (abs >= 1e8) return { value: yuan / 1e8, unit: '亿', text: `${(yuan/1e8).toFixed(2)} 亿` };
  if (abs >= 1e7) return { value: yuan / 1e7, unit: '千万', text: `${(yuan/1e7).toFixed(2)} 千万` };
  if (abs >= 1e4) return { value: yuan / 1e4, unit: '万', text: `${(yuan/1e4).toFixed(2)} 万` };
  return { value: yuan, unit: '元', text: `${yuan.toFixed(0)} 元` };
}
```

### 5.4 懒加载策略

| 页面 | 策略 |
|------|------|
| 3 板块图 | Accordion 展开时 `echarts.init`；收起 `dispose` |
| 4 个股图 | 同页面 3；成份股 ~50–200，可接受 |
| 6 ETF 图 | **默认 Top 50**；选「全部」时分批渲染或滚动进入视口再 init |

### 5.5 页面跳转参数

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
```

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
| 9 | 页面 5、6 | ETF 表格 + 图（分页/Top N） |
| 10 | 导航、样式、空态、验收 | 交付 |

---

## 9. 风险与对策

| 风险 | 对策 |
|------|------|
| ETF 无历史接口，5 日靠 cron | 文档说明；backfill 只填 A 股；ETF 满 5 天 cron 后可用 |
| 页面 5 1480 行卡顿 | 分页 API + 前端分页；禁止一次渲染全表 |
| 页面 6 1480 图内存爆炸 | 默认 Top 50 + 懒加载 |
| 买卖 vs 成交 trade_date 偏移 | 21:35 后采集；DB 分字段存储 |
| ETF 占 A 股比极小 | 表格占比保留 4 位小数或科学显示；Tooltip 展示精确值 |
| 板块占比之和 < 100% | 未归类股票；脚注说明 |

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

---

## 11. 与 Phase 1 关系

| 现有 | 变更 |
|------|------|
| CSV latest 文件 | 保留，作降级快照 |
| `etf_turnover_latest.csv` | 继续生成，并写入 `etf_daily` |
| `by_common.py` | 复用，不破坏现有 CLI |
