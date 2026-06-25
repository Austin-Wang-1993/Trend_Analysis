# 神奇九转（TD Sequential 抄底）v4.4

> 状态：**需求已澄清，待开发**  
> 数据源：**Tushare Pro**（复用火车轨 OHLCV 缓存）  
> 范围：**仅抄底买入**（下跌 Setup + 买入 Countdown）；**v1 不做逃顶**

---

## 1. 功能定位

**盘后扫描观察池**：在每个交易日收盘后，对 **全 A**（排除 ST、停牌）计算德马克 TD 序列 **买入侧** 信号，按 **五列漏斗** 由宽到严展示，辅助判断「下跌动能衰竭 → 潜在抄底」时机。

| 对比项 | 火车轨选股 v4.3 | 神奇九转 v4.4 |
|--------|-----------------|---------------|
| 目的 | 强势回踩、顺势 | 超跌衰竭、逆势抄底 |
| 核心算法 | SXHCG + RPS | TD Setup(9) + Countdown(13) |
| 展示 | 单表 + 漏斗统计 | **五列递进漏斗** |
| 缓存 | `train_track_daily_cache` | **复用同表**（不新建日线缓存） |

定位：**警报器**，非自动交易开关；单边暴跌市中信号可能连续失效（见 §8）。

---

## 2. v1 范围边界

### 2.1 做

| 层级 | 内容 |
|------|------|
| **Layer 1（核心）** | 标准德马克 **买入 Setup(9)** + **买入 Countdown(13)** 状态机 |
| **Layer 2（过滤器）** | 第 9 转当日的 **量价形态**（缩量/放量、上下影线） |
| **Layer 3（过滤器）** | Countdown **临近 13**（可配置窗口） |
| **Layer 4（过滤器）** | Countdown **已完成 13** |
| **Layer 5（过滤器）** | 绿 13 日 **MACD 底背离** |
| **工程** | 全 A 扫描、五列看板、漏斗统计、管理页可配参数、后台任务 + 进度 |

### 2.2 不做（v1）

- 卖出 Setup / 卖出 Countdown（逃顶、红 9/红 13）
- 缩量红 9 降权、K 线主图叠加 1–9 / 1–13 数字
- 自动下单、止损触发推送
- 单股详情页改造（可链到现有 `stock-detail.html`）

---

## 3. TD 计算口径（Layer 1，精确公式）

以下均为 **不复权** 日线，索引 `i` 为当前 K 线，`i-4` 表示 4 个交易日之前（非日历日）。

### 3.1 买入 Setup（绿九转）

**状态变量**：`setup_count ∈ {0,1,…,9}`，中断则归零。

对每个交易日 `i`（需 `i ≥ 4`）：

```text
若 close[i] < close[i-4]：
    setup_count += 1
否则：
    setup_count = 0

当 setup_count == 9 的当日，记为 setup_9 完成：
    setup_9_date = trade_date[i]
    setup_9_close / setup_9_low / setup_9_vol 等快照字段落库
```

**约束**：

- 9 根 K 线必须 **连续** 满足条件；任一日不满足则从 1 重新计数。
- Setup 完成后 `setup_count` 归零，并 **启动** 买入 Countdown（见下）；同一轮下跌周期内不重复计第二个 Setup，直至 Countdown 完成或结构作废（实现时用显式状态机）。

### 3.2 买入 Countdown（绿十三）

Setup(9) 完成后的 **下一交易日** 起进入 Countdown 阶段。

**状态变量**：`cd_count ∈ {0,1,…,13}`，对应满足条件的 K 线日期列表 `cd_dates[]`。

对每个交易日 `j`（需 `j ≥ 2`）：

```text
若 close[j] <= low[j-2]：
    候选计入 cd_count（非连续；同一日只计一次）
```

**第 13 根附加条件（标准德马克，与主流软件对齐）**：

```text
设第 8 次计数日为 cd_dates[7]，其收盘价为 C8
第 13 次候选日 T13 除满足 close[T13] <= low[T13-2] 外，还须：
    low[T13] <= C8
若不满足，cd_count 停在 12，继续等待下一根满足 close<=low[-2] 的 K 线再试
```

当 `cd_count == 13`：

```text
countdown_13_date = trade_date[j]
```

### 3.3 结构作废（实现建议）

以下情况 **结束当前序列**，不再向更高列晋级，但历史快照保留供审计：

| 事件 | 处理 |
|------|------|
| Setup 完成后、Countdown 未结束前，又出现新的 Setup(9) | 以 **最新 Setup** 为准，旧 Countdown 作废 |
| 扫描日距 `setup_9_date` 超过 `setup_max_age_days` 仍未 Countdown 完成 | 移出「临近 13」列，可保留在第 1–2 列（可配） |

### 3.4 最少 K 线根数

| 用途 | 最少交易日 |
|------|------------|
| Setup(9) | 9 + 4 = **13** |
| Countdown(13) | Setup 后视行情，通常再需数十日 |
| MACD(12,26,9) | **≥ 35**（建议缓存 **≥ 120** 日） |

默认缓存深度 `td_history_days = 120`（可配 60–250），与火车轨共用 `train_track_daily_cache` 时取两者较大值写入。

---

## 4. 五列漏斗定义

页面为 **横向五列**；每只股票 **只出现在其达到的最高列**（避免重复刷屏）。列间为 **子集关系**：

```text
列5 ⊂ 列4 ⊂ 列3 ⊂ 列2 ⊂ 列1
```

### 列 1 — 达成九转（Setup 完成）

| 项 | 规则 |
|----|------|
| 入选 | 在扫描日 `T` 上，存在 **刚完成** 的买入 Setup(9) |
| 时间窗 | `setup_9_date ∈ [T − setup_fresh_days, T]`（默认 `setup_fresh_days = 0`，即仅 **扫描当日** 标出第 9 根；可改为 1–5 以放宽） |
| 展示字段 | 代码、名称、行业、`setup_9_date`、收盘、涨跌幅、Setup 历时 |

### 列 2 — 九转 + 第 9 日量价形态

在列 1 基础上，**`setup_9_date` 当日** 通过量价形态过滤器。

**几何量**（`setup_9` 当日 OHLC）：

```text
range = high - low
body = |close - open|
lower_shadow = min(open, close) - low
upper_shadow = high - max(open, close)
lower_ratio = lower_shadow / range   （range=0 时视为十字星，lower_ratio=1）
upper_ratio = upper_shadow / range
body_ratio = body / range
```

**成交量**（优先 `vol`，缺失时用 `turnover_rate`）：

```text
vol_ma5 = mean(vol[setup_9-5 : setup_9-1])   # 前 5 日不含当日
shrink = vol[setup_9] < vol_ma5 * vol_shrink_ratio     # 默认 ratio=0.8
expand = vol[setup_9] > vol_ma5 * vol_expand_ratio     # 默认 ratio=1.2
```

**合格（可抄底关注）** — 默认 **满足其一** 即可（可配为「须同时」）：

| 标签 | 条件 |
|------|------|
| `缩量` | `shrink == true` |
| `锤子/十字` | `lower_ratio >= shadow_lower_min`（默认 0.5）**或** `body_ratio <= cross_body_max`（默认 0.15） |

**不合格（显式剔除，不进列 2）**：

| 标签 | 条件 |
|------|------|
| `放量大阴` | `expand` **且** `lower_ratio < bear_lower_max`（默认 0.2）**且** `close` 接近最低价：` (close-low)/range < 0.1 ` |

列 2 额外展示：`vol_tag`（缩量/放量/中性）、`lower_ratio`、`upper_ratio`、`body_ratio`。

### 列 3 — 列 2 + 临近十三转

在列 2 基础上，Countdown **尚未到 13**，但 **接近完成**：

```text
cd_count >= countdown_near_min          # 默认 10
cd_count <= countdown_near_max          # 默认 12
trade_date 距 setup_9_date 的交易日数 <= countdown_window_days   # 默认 30
```

含义：已在 Countdown 阶段且 **最多还差 3 次计数**（默认），并在 Setup 后合理时间窗内。

展示：`cd_count`、`cd_remain = 13 - cd_count`、最近计数日。

### 列 4 — 列 3 基础 + 已达成十三转

在列 2 基础上（**不要求经过列 3 的「临近」状态**），`cd_count == 13` 且 `countdown_13_date` 落在：

```text
countdown_13_date ∈ [T − countdown_fresh_days, T]    # 默认 countdown_fresh_days = 0
```

展示：`countdown_13_date`、`setup_9` 至 `countdown_13` 间隔 K 线数、参考止损价（见下）。

**参考止损（仅展示，不执行）**：

```text
stop_loss = setup_9_low * (1 - stop_loss_pct)    # 默认 stop_loss_pct = 0.03
```

### 列 5 — 列 4 + 绿 13 底背离

在列 4 基础上，MACD 底背离：

```text
close[countdown_13] < close[setup_9]              # 价创新低（相对九转日）
macd_ref[countdown_13] > macd_ref[setup_9]        # MACD 未创新低
```

`macd_ref` 可配（默认 **`macd_hist`** = 2×(DIF−DEA)）：

| 选项 | 字段 |
|------|------|
| `hist`（默认） | MACD 柱 |
| `dif` | DIF 线 |
| `both` | 柱与 DIF 均抬高 |

MACD 参数：`macd_fast=12, macd_slow=26, macd_signal=9`（可配）。

---

## 5. 数据源验证

### 5.1 字段需求 vs 现网

| 计算项 | 需要字段 | `train_track_daily_cache` | Tushare 来源 |
|--------|----------|---------------------------|--------------|
| Setup(9) | `close` | ✅ | `daily.close` |
| Countdown(13) | `close`, `low` | ✅ | `daily` |
| 第 13 vs 第 8 | `low`, `close` | ✅ | `daily` |
| 量价形态 | `open`, `high`, `low`, `close`, `vol` | ✅ | `daily` |
| 缩量（备选） | `turnover_rate` | ✅ | `daily_basic.turnover_rate` |
| MACD | `close` 序列 | ✅ | 自算 |
| 股票池 | 代码、名称 | ✅ | `stock_basic` |
| 排除停牌 | — | — | `suspend_d` |
| 排除 ST | 名称 | — | `stock_basic.name` |

**结论：数据源充分，无需新增 Tushare 接口；复用火车轨缓存即可。**

### 5.2 采集与缓存策略

1. **日常采集**：`fetch_ts_daily.py` 已写入 `train_track_daily_cache`（`open,high,low,close,vol` + `turnover_rate`）。
2. **扫描补洞**：与火车轨相同，按 `td_history_days` 检查缺失交易日，逐日 `daily` + `daily_basic` 补写缓存。
3. **限频**：沿用 `ts_common.call_api` 全局限频与退避；全 A 补 120 日空洞约 120 次 `daily` 调用/股票池 1 次/日，与火车轨扫描合并时需注意总时长（后台任务 + 进度条）。

### 5.3 与 `stock_daily_v4` 的关系

`stock_daily_v4` **仅有** `turnover`（成交额）和 `pct_chg`，**无 OHLC**，**不能**用于 TD 计算。必须使用 `train_track_daily_cache`。

---

## 6. 页面框架

### 6.1 路由与导航

| 项 | 值 |
|----|-----|
| 页面 | `dashboard/td-sequential.html` |
| 路由 | `GET /td-sequential.html` |
| 导航 | 插入在「火车轨选股」与「ETF 表格」之间，文案 **神奇九转** |
| API 前缀 | `/api/td-sequential/*` |

### 6.2 布局（线框）

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ 神奇九转（TD 抄底）                                    [立即重算] 扫描日 T  │
├─────────────────────────────────────────────────────────────────────────────┤
│ 漏斗：全A可评估 n → 列1 a → 列2 b → 列3 c → 列4 d → 列5 e                  │
├──────────┬──────────┬──────────┬──────────┬──────────┐
│ ① 九转   │ ② 量价   │ ③ 临近13 │ ④ 十三转 │ ⑤ 底背离 │
│  (a只)   │  (b只)   │  (c只)   │  (d只)   │  (e只)   │
├──────────┼──────────┼──────────┼──────────┼──────────┤
│ 股票列表 │ 股票列表 │ 股票列表 │ 股票列表 │ 股票列表 │
│ (滚动)   │          │          │ 含止损价 │ 含MACD  │
└──────────┴──────────┴──────────┴──────────┴──────────┘
│ 图例 / 口诀：抄底等缩量长腿…                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.3 列内表格字段

| 列 | 列头 | 字段 |
|----|------|------|
| 1 | 九转 | 代码、名称、行业、九转日、收盘、涨跌幅 |
| 2 | 量价 | + 量标签、下影比、上影比、实体比 |
| 3 | 临近13 | + 当前计数、剩余次数、最近计数日 |
| 4 | 十三转 | + 十三转日、间隔天数、止损参考 |
| 5 | 底背离 | + MACD 柱(9/13)、背离类型 |

行点击：跳转 `stock-detail.html?code=xxxxxx`（现有页）。

### 6.4 交互

| 操作 | 行为 |
|------|------|
| 进入页面 | `GET /api/td-sequential/board?trade_date=` 拉五列 + 漏斗 |
| 立即重算 | `POST /api/admin/td-sequential/scan` → 轮询 `GET /api/td-sequential/scan/status` |
| 空列 | 显示「暂无」+ 链到管理页调参 |

### 6.5 管理页配置块

锚点 `#td-sequential-config`，分组：

| 分组 | 参数 |
|------|------|
| **调度** | 开关、自动扫描时刻、历史 K 线天数 |
| **Setup** | `setup_fresh_days` |
| **量价（列2）** | 缩量/放量比、下影/十字/大阴阈值、合格逻辑（或/且） |
| **Countdown（列3–4）** | `countdown_near_min/max`、`countdown_window_days`、`countdown_fresh_days` |
| **MACD（列5）** | fast/slow/signal、背离参考字段 |
| **风控展示** | `stop_loss_pct` |

元数据字典 `TD_SEQUENTIAL_SETTINGS_META` 与火车轨 `TRAIN_TRACK_SETTINGS_META` 同模式。

---

## 7. 数据结构

### 7.1 复用表

```sql
-- 已有，不新建
train_track_daily_cache (
  trade_date, stock_code, open, high, low, close, vol, turnover_rate
)
```

### 7.2 新增表

#### `td_sequential_pick_v4` — 扫描结果（每股票每日至多一行）

```sql
CREATE TABLE IF NOT EXISTS td_sequential_pick_v4 (
    trade_date TEXT NOT NULL,           -- 扫描日
    stock_code TEXT NOT NULL,
    stock_name TEXT,
    sector_path TEXT,

    -- Layer 1 快照
    setup_9_date TEXT,
    setup_9_close REAL,
    setup_9_low REAL,
    setup_9_vol REAL,
    setup_9_turnover_rate REAL,

    -- Countdown 进度
    cd_count INTEGER NOT NULL DEFAULT 0,
    cd_last_date TEXT,
    countdown_13_date TEXT,

    -- 列晋级标记（便于 API 过滤）
    col1_setup9 INTEGER NOT NULL DEFAULT 0,
    col2_vol_price INTEGER NOT NULL DEFAULT 0,
    col3_near13 INTEGER NOT NULL DEFAULT 0,
    col4_cd13 INTEGER NOT NULL DEFAULT 0,
    col5_macd_div INTEGER NOT NULL DEFAULT 0,
    max_col INTEGER NOT NULL DEFAULT 0,   -- 1–5，展示列

    -- 列2 衍生
    vol_tag TEXT,                         -- shrink / expand / neutral
    lower_shadow_ratio REAL,
    upper_shadow_ratio REAL,
    body_ratio REAL,

    -- 列5 衍生
    macd_hist_setup9 REAL,
    macd_hist_cd13 REAL,
    macd_div_type TEXT,                   -- hist / dif / both

    -- 列4 衍生
    bars_setup_to_cd13 INTEGER,
    stop_loss_price REAL,

    updated_at TEXT,
    PRIMARY KEY (trade_date, stock_code)
);
CREATE INDEX IF NOT EXISTS idx_td_pick_date_col ON td_sequential_pick_v4(trade_date, max_col);
```

#### `td_sequential_scan_log` — 漏斗快照

```sql
CREATE TABLE IF NOT EXISTS td_sequential_scan_log (
    trade_date TEXT PRIMARY KEY,
    last_scan_at TEXT,
    universe_count INTEGER,
    funnel_json TEXT,                     -- 各列计数 + 子项
    error_message TEXT
);
```

#### `td_sequential_scan_jobs` — 后台任务（对齐火车轨）

```sql
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
```

### 7.3 `funnel_json` 示例

```json
{
  "evaluated": 5120,
  "col1_setup9": 42,
  "col2_vol_price": 18,
  "col3_near13": 7,
  "col4_cd13": 3,
  "col5_macd_div": 1,
  "vol_price_reject_expand_bear": 9,
  "missing_vol": 2
}
```

### 7.4 配置项（`app_settings` 键名草案）

| 键 | 默认 | 分组 | 说明 |
|----|------|------|------|
| `td_enabled` | `true` | 调度 | 交易日自动扫描 |
| `td_time` | `16:45` | 调度 | 扫描时刻（在火车轨之后） |
| `td_history_days` | `120` | 调度 | 缓存最少交易日 |
| `td_setup_fresh_days` | `0` | Setup | 九转完成日距扫描日最大偏移 |
| `td_vol_shrink_ratio` | `0.8` | 量价 | 低于前 5 日均量比例 → 缩量 |
| `td_vol_expand_ratio` | `1.2` | 量价 | 高于前 5 日均量比例 → 放量 |
| `td_shadow_lower_min` | `0.5` | 量价 | 下影线占比下限（锤子） |
| `td_cross_body_max` | `0.15` | 量价 | 十字实体占比上限 |
| `td_bear_lower_max` | `0.2` | 量价 | 大阴线：下影过小阈值 |
| `td_vol_price_mode` | `or` | 量价 | 合格条件：`or` / `and` |
| `td_countdown_near_min` | `10` | Countdown | 临近 13：最少已计数 |
| `td_countdown_near_max` | `12` | Countdown | 临近 13：最多已计数 |
| `td_countdown_window_days` | `30` | Countdown | Setup 后 Countdown 有效窗口 |
| `td_countdown_fresh_days` | `0` | Countdown | 十三转完成日距扫描日偏移 |
| `td_macd_fast` | `12` | MACD | |
| `td_macd_slow` | `26` | MACD | |
| `td_macd_signal` | `9` | MACD | |
| `td_macd_div_ref` | `hist` | MACD | `hist` / `dif` / `both` |
| `td_stop_loss_pct` | `0.03` | 风控 | 止损展示：九转最低价下方比例 |

---

## 8. API 草案

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/td-sequential/meta` | 扫描日、最近任务、默认参数摘要 |
| GET | `/api/td-sequential/board` | `{ funnel, columns: { "1": [...], …, "5": [...] } }` |
| GET | `/api/td-sequential/scan/status` | 后台任务进度 |
| POST | `/api/admin/td-sequential/scan` | 触发重算（409 若已有任务） |

查询参数：`trade_date`（可选）、`column`（可选，只拉单列）。

---

## 9. 代码模块（开发清单）

```text
scripts/td_sequential_common.py    # TD 状态机 + 量价 + MACD + 列判定（纯函数，单测）
scripts/td_sequential_store.py     # 表结构 + pick/log/jobs + 读缓存
scripts/td_sequential_scanner.py   # 全 A 扫描编排（复用 train_track 缓存补洞）
scripts/td_sequential_runner.py    # 后台任务入队
tests/test_td_sequential_common.py
dashboard/td-sequential.html
dashboard/static/js/nav.js         # +1 导航项
dashboard/admin.html + admin.js    # 配置块
api/server.py                      # 路由 + SettingsUpdate 字段
scripts/scheduler.py               # 定时扫描（td_time）
```

**依赖**：读取 `train_track_daily_cache`；**不修改** TD 公式逻辑在 `fetch_ts_daily` 中。

---

## 10. 已澄清的需求决策

| 问题 | 决策 |
|------|------|
| 计算口径 | Layer 1 标准 TD + Layer 2–5 过滤器；**仅抄底** |
| 股票池 | 全 A，排除 ST、停牌 |
| 页面形态 | **五列递进漏斗**，非单股 K 线画数字 |
| 逃顶 | v1 **不做** |
| 日线缓存 | **复用** `train_track_daily_cache` |
| 列内去重 | 每股 **仅出现在最高达标列** |
| 九转时效 | 默认仅 **扫描当日** 完成九转（`setup_fresh_days=0`），可配放宽 |
| 十三转时效 | 默认仅 **扫描当日** 完成十三转（`countdown_fresh_days=0`） |

---

## 11. 风险与已知局限

1. **单边暴跌**：绿 9/13 可能连续出现仍继续下跌；文档与 UI 需提示「警报器」定位。
2. **与通达信差异**：部分软件 Countdown 起算日、13/8 规则有简化实现；本项目以 §3 公式为准，上线后用样本股人工比对 1–2 只校验。
3. **扫描耗时**：全 A × 120 日状态机，预计与火车轨同量级；必须后台任务 + 进度，避免 HTTP 超时。
4. **`setup_fresh_days=0` 时列 1 可能很窄**：属预期；放宽参数可增加样本量。

---

## 12. 验收标准（开发完成后）

- [ ] 单测覆盖：Setup 连续/中断、Countdown 非连续、13/8 规则、量价过滤器、MACD 背离
- [ ] 全 A 扫描落库，`funnel_json` 五列计数与列内列表一致
- [ ] 看板五列展示，管理页可改参数并重算
- [ ] 日常 `fetch_ts_daily` 后缓存满足 `td_history_days`
- [ ] 导航可达；空池时有友好提示

---

## 13. 参考口诀（产品文案）

> 抄底等缩量长腿，逃顶等放量滞涨；缩量涨出九别慌，放量跌出九别抢。

v1 页面仅展示 **前半句（抄底）** 相关提示。
