# 实现方案：历史落库 + Web 看板

> 版本：**v3.0**  
> 前置：[REQUIREMENTS.md](./REQUIREMENTS.md)  
> 必盈接口：[BIYING_API.md](./BIYING_API.md)

---

## 1. 总体架构

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                         数据采集层（已有 + 扩展）                          │
│  fetch_by_daily.py  ──►  CSV 快照（latest）                               │
│       │                                                                   │
│       └──► history_store.py ──► SQLite data/history.db                    │
│              ▲                                                            │
│  backfill_history.py（一次性 30 日回填）                                    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         服务层（新增）                                    │
│  api/server.py（FastAPI）                                                 │
│    GET /api/market?days=5|30                                            │
│    GET /api/sectors/table?days=5&sort=pct_desc                          │
│    GET /api/sectors/charts?days=5                                       │
│    GET /api/sectors/{code}/stocks?days=5                                │
│    GET /api/meta/trading-days?days=5                                    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         展示层（新增）                                    │
│  dashboard/                                                               │
│    index.html          → 页面 1 全 A 概览                                │
│    sectors-table.html  → 页面 2 板块表格                                  │
│    sectors-charts.html → 页面 3 板块图表                                  │
│    sector-stocks.html  → 页面 4 个股图表                                  │
│    static/js/format.js → 万/千万/亿格式化                                 │
│    static/js/charts.js → ECharts 封装                                    │
│    static/js/api.js    → 请求 API                                        │
└─────────────────────────────────────────────────────────────────────────┘
```

**技术选型**

| 层 | 选型 | 理由 |
|----|------|------|
| 历史存储 | **SQLite** | 单机部署简单，SQL 聚合方便，无额外服务 |
| API | **FastAPI** | 轻量、自动 OpenAPI、与 Python 采集同栈 |
| 图表 | **Apache ECharts 5** | 柱状图成熟、Tooltip 自定义友好 |
| 前端 | **原生 JS + 多页 MPA** | 无构建链，腾讯云上一键部署；后续可迁 Vue |
| 静态服务 | FastAPI `StaticFiles` | 单进程同时提供 API + 页面 |

---

## 2. 目录结构（规划）

```text
Trend_Analysis/
├── scripts/
│   ├── fetch_by_daily.py      # 扩展：采集后写入 history.db
│   ├── backfill_history.py    # 新增：30 日历史回填
│   ├── history_store.py       # 新增：SQLite CRUD / UPSERT
│   └── serve_dashboard.py     # 新增：启动看板（uvicorn）
├── api/
│   ├── server.py              # FastAPI 路由
│   ├── queries.py             # SQL 查询
│   └── schemas.py             # Pydantic 响应模型
├── dashboard/
│   ├── index.html
│   ├── sectors-table.html
│   ├── sectors-charts.html
│   ├── sector-stocks.html
│   └── static/
│       ├── css/dashboard.css
│       └── js/{format,charts,api,nav}.js
├── data/
│   ├── history.db             # gitignore
│   └── …（现有 CSV）
└── docs/
    ├── REQUIREMENTS.md        # v3.0
    └── IMPLEMENTATION_PLAN.md # 本文档
```

---

## 3. Phase 2：历史落库

### 3.1 数据库 Schema

```sql
-- 交易日历（可选，用于对齐「近 N 交易日」）
CREATE TABLE IF NOT EXISTS trading_calendar (
    trade_date TEXT PRIMARY KEY,
    is_trading  INTEGER NOT NULL DEFAULT 1
);

-- 全 A 日汇总
CREATE TABLE IF NOT EXISTS market_daily (
    trade_date    TEXT PRIMARY KEY,
    turnover      REAL NOT NULL,
    active_buy    REAL,
    active_sell   REAL,
    net_active    REAL,
    stock_count   INTEGER,
    snapshot_time TEXT
);

-- 板块日汇总
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

-- 个股日明细
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

CREATE INDEX IF NOT EXISTS idx_sector_daily_date ON sector_daily(trade_date);
CREATE INDEX IF NOT EXISTS idx_stock_daily_sector ON stock_daily(trade_date, sector_code);
CREATE INDEX IF NOT EXISTS idx_stock_daily_code ON stock_daily(stock_code, trade_date);
```

### 3.2 history_store.py 核心接口

```python
def upsert_market_day(row: dict) -> None: ...
def upsert_sector_day(rows: list[dict]) -> None: ...
def upsert_stock_day(rows: list[dict]) -> None: ...

def get_recent_trading_days(n: int) -> list[str]: ...
def get_market_series(days: int, fields: list[str]) -> list[dict]: ...
def get_sector_table(days: int, sort: str) -> dict: ...
def get_sector_charts(days: int) -> list[dict]: ...
def get_sector_stocks(sector_code: str, days: int) -> dict: ...
```

### 3.3 fetch_by_daily.py 扩展

采集成功写 CSV 后，追加：

```python
from history_store import HistoryStore

store = HistoryStore(DATA_DIR / "history.db")
store.upsert_from_snapshot(
    market_df=market_df,
    sector_turnover_df=sector_df,
    sector_flow_df=sector_ff_df,
    stock_df=stock_df,
)
```

- **幂等**：同一 `trade_date` 重复跑覆盖更新。
- **turnover_pct**：写入时计算 `sector.turnover / market.turnover`。

### 3.4 backfill_history.py（30 日回填）

```bash
# 一次性：拉取每只股票最近 30 条 transaction，写入 stock_daily，再聚合 sector/market
python3 scripts/backfill_history.py --days 30 --no-all-turnover
```

流程：

```text
hslt/list → 5208 codes
for each code:
    GET history/transaction/{code}?lt=30
    → parse → stock_daily rows（含 active_buy/sell）
    sleep 0.21s（频率控制）

按 trade_date 聚合 → sector_daily, market_daily
成交额回填策略：
  - 优先：若 stock_daily 已有 turnover（来自每日 cron 积累），不覆盖
  - 否则：backfill 仅写买卖，turnover 留空；或二次调用日 K 接口（若后续接入）
```

**说明**：30 日 **买卖** 可一次回填；**成交额** 5 日图依赖至少 5 次每日 cron 或额外历史 K 线接口。MVP 可先保证买卖 30 日 + 成交 5 日（5 天 cron 后自然满足）。

### 3.5 定时任务

```cron
# 交易日 21:35（买卖 21:30 更新后再跑）
35 21 * * 1-5 cd ~/Trend_Analysis && set -a && source .env && set +a && \
  .venv/bin/python scripts/fetch_by_daily.py --no-all-turnover >> logs/fetch.log 2>&1
```

---

## 4. Phase 3：API 设计

### 4.1 通用响应

```json
{
  "meta": {
    "days_requested": 5,
    "days_actual": 5,
    "trade_dates": ["2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12", "2026-06-13"],
    "unit_hint": "display uses 万/千万/亿; values in yuan"
  },
  "data": { ... }
}
```

所有金额字段 API 返回 **元（number）**，格式化仅在前端。

### 4.2 GET /api/market

| 参数 | 默认 | 说明 |
|------|------|------|
| `turnover_days` | 5 | 成交额序列长度 |
| `flow_days` | 30 | 买卖序列长度 |

响应 `data`：

```json
{
  "turnover_series": [{"trade_date": "2026-06-13", "value": 2.03e12}],
  "active_buy_series": [{"trade_date": "...", "value": ...}],
  "active_sell_series": [{"trade_date": "...", "value": ...}]
}
```

### 4.3 GET /api/sectors/table

| 参数 | 默认 | 说明 |
|------|------|------|
| `days` | 5 | |
| `sort` | `pct_desc` | `pct_asc` \| `pct_desc` \| `amount_desc` \| `name_asc` |

响应：板块列表 + 每板块 `days` 长度的 `{date, turnover, turnover_pct}` 数组。

### 4.4 GET /api/sectors/charts

返回全部板块的近 N 日三序列（成交额 / 主买 / 主卖），供页面 3 批量渲染（折叠懒加载）。

### 4.5 GET /api/sectors/{sector_code}/stocks

返回板块元信息 + 成份股列表，每股含近 N 日三序列。

---

## 5. Phase 3：前端设计

### 5.1 页面线框

#### 页面 1 `/` — 全 A 概览

```text
┌──────────────────────────────────────────────────────────────┐
│  Trend Analysis    [概览] [板块表格] [板块图表]                  │
├──────────────────────────────────────────────────────────────┤
│  近 5 日 A 股成交额                                            │
│  ████████████████████  ECharts 柱状图                         │
├──────────────────────────────────────────────────────────────┤
│  近 30 日 A 股主买额                                           │
│  ████████████████████                                         │
├──────────────────────────────────────────────────────────────┤
│  近 30 日 A 股主卖额                                           │
│  ████████████████████                                         │
└──────────────────────────────────────────────────────────────┘
```

#### 页面 2 `/sectors-table.html`

```text
排序: [占比↓] [占比↑] [成交额↓] [名称A-Z]

| 板块 | 06-09 额 | 06-09 % | 06-10 额 | 06-10 % | … |
|------|----------|---------|----------|---------|---|
| 银行 | 1234 亿  | 12.34%  | …        | …       |   |
```

#### 页面 3 `/sectors-charts.html`

Accordion + 每卡片右侧 `[查看个股]` 按钮。

#### 页面 4 `/sector-stocks.html?sector=sw_bank`

面包屑 + KPI 条 + 个股 Accordion。

### 5.2 单位格式化（format.js）

```javascript
/**
 * @param {number} yuan 金额（元）
 * @returns {{ value: number, unit: string, text: string }}
 */
export function formatAmount(yuan) {
  const abs = Math.abs(yuan);
  if (abs >= 1e8)  return fmt(yuan / 1e8,  '亿');
  if (abs >= 1e7)  return fmt(yuan / 1e7,  '千万');
  if (abs >= 1e4)  return fmt(yuan / 1e4,  '万');
  return fmt(yuan, '元');
}

// ECharts axisLabel / tooltip 共用
export function axisFormatter(value) {
  return formatAmount(value).text;
}
```

规则与 [REQUIREMENTS.md §3.1.1](./REQUIREMENTS.md) 一致。

### 5.3 图表配置要点

| 项 | 配置 |
|----|------|
| 类型 | `bar`，单系列 |
| X 轴 | `trade_dates`，`axisLabel: { rotate: 30 }` |
| Y 轴 | `axisLabel: { formatter: axisFormatter }` |
| Tooltip | `formatter` 展示：日期 + 格式化金额 + 原始元（可选） |
| 懒加载 | Accordion `展开` 事件里 `echarts.init` + `setOption`，避免一次 31×3 实例 |

### 5.4 页面路由与参数

| 页面 | 文件 | URL 参数 |
|------|------|----------|
| 1 | `index.html` | — |
| 2 | `sectors-table.html` | `sort=pct_desc` |
| 3 | `sectors-charts.html` | `sort=`, `expand=sector_code` |
| 4 | `sector-stocks.html` | `sector=sector_code`（必填） |

---

## 6. 依赖变更

### requirements.txt 新增

```text
fastapi>=0.110
uvicorn[standard]>=0.27
```

前端 ECharts 使用 CDN：

```html
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
```

---

## 7. 启动与部署

### 7.1 本地开发

```bash
cd ~/Trend_Analysis
source .venv/bin/activate
pip install -r requirements.txt

# 确保 history.db 有数据（至少跑 5 天 cron 或 backfill）
python3 scripts/backfill_history.py --days 30 --no-all-turnover

# 启动看板
python3 scripts/serve_dashboard.py
# 默认 http://127.0.0.1:8080
```

### 7.2 腾讯云生产

```text
方案 A（推荐）：systemd 守护 uvicorn + Nginx 反代
  - Nginx :80 → 127.0.0.1:8080
  - Basic Auth 或 IP 白名单

方案 B：cron 生成静态 JSON + nginx 纯静态
  - 适合只读、无实时 API 需求
  - 每交易日 22:00 跑 build_dashboard_json.py
```

### 7.3 serve_dashboard.py 骨架

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from api.server import router

app = FastAPI(title="Trend Analysis Dashboard")
app.include_router(router, prefix="/api")
app.mount("/", StaticFiles(directory="dashboard", html=True), name="dashboard")
# uvicorn api.server:app --host 0.0.0.0 --port 8080
```

---

## 8. 实施顺序

| 步骤 | 任务 | 产出 | 依赖 |
|------|------|------|------|
| 1 | `history_store.py` + Schema | SQLite 读写 | — |
| 2 | `fetch_by_daily.py` 接入 UPSERT | 每日增量 | 1 |
| 3 | `backfill_history.py` | 30 日买卖 | 1 |
| 4 | cron 配置 + 跑满 5 个交易日 | 5 日成交序列 | 2 |
| 5 | FastAPI `/api/*` | JSON API | 1 |
| 6 | `format.js` + ECharts 封装 | 图表组件 | — |
| 7 | 页面 1 | 全 A 三图 | 5, 6 |
| 8 | 页面 2 | 表格 + 排序 | 5, 6 |
| 9 | 页面 3 | 板块 Accordion | 5, 6 |
| 10 | 页面 4 | 个股下钻 | 5, 6 |
| 11 | 样式 / 导航 / 验收 | 可交付看板 | 7–10 |

---

## 9. 风险与对策

| 风险 | 对策 |
|------|------|
| 历史不足 30 日 | API 返回 `days_actual`；前端显示提示条 |
| 页面 3 同时渲染 93 个图表卡顿 | Accordion 懒加载；同时最多保留 3–5 个 ECharts 实例 |
| 买卖与成交 trade_date 不一致 | DB 分字段存储；展示层按各自最新日期对齐，README 说明 |
| 未归类股票导致占比 < 100% | 表格增加 footnote；可选「其他/未归类」行 |
| 必盈 API 限频 | backfill 分批次；sleep + 断点续传 |
| ETF 无买卖 | 本期不做 ETF 页；REQUIREMENTS 已排除 |

---

## 10. 测试要点

| 用例 | 预期 |
|------|------|
| `formatAmount(1.23e10)` | `123.00 亿` |
| `formatAmount(5.6e7)` | `5,600 万` 或 `5600 万`（千分位可选） |
| market API days=5 | 返回 5 个 trade_date |
| sector table sort=pct_asc | 占比升序 |
| sector-stocks 非法 code | 404 + 友好页 |
| 空数据库 | 各页展示「暂无历史数据，请先运行采集」 |

---

## 11. 与 Phase 1 脚本关系

| 现有 | 变更 |
|------|------|
| `fetch_by_daily.py` | 保留 CSV 输出；**追加** history.db UPSERT |
| `by_common.py` | 不变；backfill 复用 `fetch_fund_flow_single` |
| CSV latest 文件 | 继续作为 cron 失败时的降级可读快照 |
| `etf_turnover_latest.csv` | 不看板展示；Phase 4 可选 |

---

## 12. 归档脚本

不变，见 v2.0 说明。
