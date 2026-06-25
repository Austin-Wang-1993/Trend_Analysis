# 神奇九转（TD Sequential 抄底）v4.4

> 状态：**已实现（v4.4）**  
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
| **工程** | 全 A 扫描、五列看板、漏斗统计、**个股九转/十三转明细子页**、管理页可配参数、后台任务 + 进度 |
| **K 线** | **仅日 K**（不复权 `daily`） |

### 2.2 不做（v1）

- 卖出 Setup / 卖出 Countdown（逃顶、红 9/红 13）
- 缩量红 9 降权、主图 K 线叠加 1–9 / 1–13 数字
- 自动下单、止损触发推送
- 分钟 K / 周线 / 复权切换

---

## 3. TD 计算口径（Layer 1，精确公式）

以下均为 **不复权日 K**（Tushare `daily`），索引 `i` 为当前 K 线，`i-4` 表示 4 个交易日之前（非日历日）。

### 3.0 核心原则：九转与十三转两段独立

| 原则 | 说明 |
|------|------|
| **两段独立** | **Setup（九转）** 与 **Countdown（十三转）** 分两段计算；十三转 **仅在九转完成之后** 才开始，起算日为九转完成日的 **下一交易日** |
| **不混用窗口** | 九转逐日比较 `close vs close[i-4]`；十三转逐日比较 `close vs low[i-2]`（及 13/8 规则），两套条件 **互不替代** |
| **仅用最新一组** | 若回溯窗内出现多组九转，**只取 `setup_9_date` 最新的一组** 做列 2–5 判定与明细展示；旧组不参与漏斗 |
| **每股一行** | 扫描结果表每 `(扫描日, 股票)` 至多一行，绑定上述「最新一组」序列 |

```text
时间轴：  … → [Setup 1..9 连续 9 日] → setup_9_date → (下一交易日起) Countdown 1..13 …
                ↑ 区间 A：九转                    ↑ 区间 B：十三转（与 A 分离）
```

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
- 每次 `setup_count == 9` 记录一个 **`SetupCycle`**（含 9 根明细）；完成后 `setup_count` 归零。
- **Countdown 只挂在「当前采用的 SetupCycle」上**（见 §3.0：取最新 `setup_9_date` 的那组）。

### 3.2 买入 Countdown（绿十三）

**前置**：仅当某一 `SetupCycle` 的九转已完成，才从 **`setup_9_date` 的下一交易日** 起，为该周期单独开启 Countdown（与九转区间 **分开、独立** 计数）。

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

### 3.3 多组九转时的选取规则

在扫描日 `T`、回溯窗 `[T − lookback_days, T]` 内：

```text
1. 枚举窗内所有 Setup(9) 完成日 → setup_9_date 列表
2. 取 max(setup_9_date) 作为 active_setup
3. 仅对 active_setup 对应周期：
   - 计算 Countdown 进度 / 十三转完成日
   - 做列 2–5 过滤
   - 生成明细子页数据
4. 更早已完成的九转组：可写入 audit，但不进看板、不进子页
```

若窗内 **无** 九转完成，则该股票不出现在列 1–5。

### 3.4 结构作废（实现建议）

| 事件 | 处理 |
|------|------|
| 窗内出现比 `active_setup` 更新的九转 | 切换到新组；旧组 Countdown 作废 |
| `active_setup` 之后 Countdown 未在配置窗口内推进 | 仍可进列 1–2；列 3 需满足 §4.3 的「距九转 ≤ N 日」 |

### 3.5 最少 K 线根数

| 用途 | 最少交易日 |
|------|------------|
| Setup(9) | 9 + 4 = **13** |
| Countdown(13) | Setup 后视行情，通常再需数十日 |
| MACD(12,26,9) | **≥ 35**（建议缓存 **≥ 120** 日） |

默认缓存深度 `td_history_days = 120`（可配 60–250），与火车轨共用 `train_track_daily_cache` 时取两者较大值写入。

### 3.6 区间 A 与区间 B 之间的「间隔」

九转完成日与十三转起始日是两个独立区间的边界，**间隔**定义为二者在交易日历上的偏移（非日历日）：

```text
countdown_start_date =
    若已有 Countdown 计数 → countdown_bars[0].trade_date（首次计数日）
    否则 → setup_9_date 的下一交易日（阶段起算日，尚未计数时）

gap_setup_to_cd_days = trading_days_offset(setup_9_date, countdown_start_date)
```

**示例**：九转于 `2026-05-28` 完成，十三转首次计数于 `2026-05-29` → `gap_setup_to_cd_days = 1`。

另有一指标 **`days_setup_to_scan`** = `trading_days_offset(setup_9_date, 扫描日 T)`，用于列 3「九转后短期内即将数完」的窗口判定（见 §4.3），**不等于**区间间隔。

| 字段 | 含义 | 典型用途 |
|------|------|----------|
| `gap_setup_to_cd_days` | 九转结束 → 十三转开始 | 明细摘要、校验两段衔接 |
| `days_setup_to_scan` | 九转完成 → 扫描日 | 列 3 过滤 `≤ countdown_after_setup_days` |
| `days_since_setup`（库列，兼容） | 同 `gap_setup_to_cd_days` | 旧 API/看板字段名 |

---

## 4. 五列漏斗定义

页面为 **横向五列**；每只股票 **只出现在其达到的最高列**。列间为 **子集关系**：

```text
列5 ⊂ 列4 ⊂ 列3 ⊂ 列2 ⊂ 列1
```

### 4.0 统一回溯窗（列 1–5 共用）

所有列的「事件是否入选」均看该事件日期是否落在：

```text
event_date ∈ [T − lookback_days, T]
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `td_lookback_days` | **20** | 自扫描日 `T` 向前回溯的 **交易日** 数；窗内达成的九转 / 十三转均统计进对应列 |

- **列 1**：`setup_9_date` 在回溯窗内（且为窗内 **最新** 一组九转）。
- **列 4**：`countdown_13_date` 在回溯窗内（同一 `active_setup`）。
- 管理页可改 `lookback_days`（建议 5–60）。

> 取代原 `setup_fresh_days` / `countdown_fresh_days` 两套偏移，统一为一个回溯参数。

### 列 1 — 达成九转（Setup 完成）

| 项 | 规则 |
|----|------|
| 入选 | `active_setup` 的 `setup_9_date ∈ [T − lookback_days, T]` |
| 展示字段 | 代码、名称、行业、九转日、收盘、涨跌幅 |

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

在列 2 基础上，Countdown **尚未到 13**，且处于「九转后短期内即将数完」：

```text
cd_count >= countdown_near_min          # 默认 10
cd_count <= countdown_near_max          # 默认 12
cd_count < 13
trading_days_between(setup_9_date, T) <= countdown_after_setup_days   # 默认 5
```

含义：

- 十三转区间 **已开始**（九转完成次日即起算），与九转区间 **独立**；
- **默认**：自九转完成日至扫描日 `T` 不超过 **5 个交易日**（`countdown_after_setup_days`，字段 `days_setup_to_scan`）；
- 在此窗口内 Countdown 已计 10–12 次，视为「临近 13」。

展示：`cd_count`、`cd_remain = 13 - cd_count`、最近计数日、`gap_setup_to_cd_days`（区间间隔）、`days_setup_to_scan`（距扫描日）。

### 列 4 — 列 2 + 已达成十三转

在列 2 基础上，`cd_count == 13`，且：

```text
countdown_13_date ∈ [T − lookback_days, T]
```

（**不要求**曾出现在列 3。）

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

行点击：跳转 **神奇九转个股明细子页**（见 §6.6），**非**通用 `stock-detail.html`。

### 6.4 交互

| 操作 | 行为 |
|------|------|
| 进入页面 | `GET /api/td-sequential/board?trade_date=` 拉五列 + 漏斗（应用 `lookback_days`） |
| 立即重算 | `POST /api/admin/td-sequential/scan` → 轮询 `GET /api/td-sequential/scan/status` |
| 空列 | 显示「暂无」+ 链到管理页调参 |
| 点击股票行 | `td-sequential-detail.html?code=xxxxxx&trade_date=` |

### 6.5 管理页配置块

锚点 `#td-sequential-config`，分组：

| 分组 | 参数 |
|------|------|
| **调度** | 开关、自动扫描时刻、历史 K 线天数 |
| **回溯** | `lookback_days`（窗内事件统计） |
| **量价（列2）** | 缩量/放量比、下影/十字/大阴阈值、合格逻辑（或/且） |
| **Countdown（列3–4）** | `countdown_near_min/max`、`countdown_after_setup_days`（默认 5） |
| **MACD（列5）** | fast/slow/signal、背离参考字段 |
| **风控展示** | `stop_loss_pct` |

元数据字典 `TD_SEQUENTIAL_SETTINGS_META` 与火车轨 `TRAIN_TRACK_SETTINGS_META` 同模式。

### 6.6 个股明细子页（`td-sequential-detail.html`）

从五列看板点击某股进入，**只展示「最新一组九转」** 的完整计算过程（窗内若有多组，见 §3.3）。

#### 路由

| 项 | 值 |
|----|-----|
| 页面 | `dashboard/td-sequential-detail.html` |
| API | `GET /api/td-sequential/stocks/{stock_code}?trade_date=` |

#### 页面结构

```text
┌──────────────────────────────────────────────────────────────┐
│ ← 返回看板    600519 贵州茅台    扫描日 T    回溯 N 日        │
├──────────────────────────────────────────────────────────────┤
│ 摘要：九转日 / 十三转日 / 当前列级 / 量价标签 / 背离 / 止损参考  │
├──────────────────────────────────────────────────────────────┤
│ 【区间 A】九转 Setup 1→9（连续 9 日）                         │
│  表格：序号 | 日期 | 收盘 | 比较日(4日前) | 比较日收盘 | 是否满足 │
├──────────────────────────────────────────────────────────────┤
│ 【区间 B】十三转 Countdown（九转次日起到第 13 次，非连续）     │
│  表格：序号 | 日期 | 收盘 | 比较日(2日前低) | 比较日最低 | 是否满足 │
│        | 第13次附加：当日最低 vs 第8次收盘 | 是否满足            │
├──────────────────────────────────────────────────────────────┤
│ 【过滤器结果】（均针对 active_setup）                          │
│  · 第9日量价：缩量/放量、上下影比、是否合格/是否大阴剔除        │
│  · 列3：cd_count、区间间隔、距扫描日、是否临近13                    │
│  · 列5：九转日 vs 十三转日 收盘、MACD 柱/DIF、是否底背离        │
└──────────────────────────────────────────────────────────────┘
```

#### 明细 API 响应（`detail_json` 结构草案）

```json
{
  "stock_code": "600519",
  "stock_name": "贵州茅台",
  "scan_trade_date": "2026-06-20",
  "lookback_days": 20,
  "active_setup_9_date": "2026-06-18",
  "countdown_start_date": "2026-06-19",
  "gap_setup_to_cd_days": 1,
  "days_setup_to_scan": 3,
  "setup_bars": [
    {
      "seq": 1,
      "trade_date": "2026-06-06",
      "close": 1420.5,
      "ref_date": "2026-05-29",
      "ref_close": 1450.0,
      "condition": "close < ref_close",
      "passed": true
    }
  ],
  "countdown_bars": [
    {
      "seq": 1,
      "trade_date": "2026-06-19",
      "close": 1410.0,
      "ref_date": "2026-06-17",
      "ref_low": 1412.0,
      "condition": "close <= ref_low",
      "passed": true,
      "extra_13v8": null
    }
  ],
  "filters": {
    "vol_price": { "passed": true, "vol_tag": "shrink", "lower_ratio": 0.55 },
    "near13": {
      "passed": false,
      "cd_count": 8,
      "gap_setup_to_cd_days": 1,
      "days_setup_to_scan": 19,
      "countdown_start_date": "2026-06-19"
    },
    "macd_div": { "passed": false }
  },
  "max_col": 2
}
```

实现：扫描时把 `detail_json` 写入 `td_sequential_pick_v4`；子页优先读库，缺省可按 code+date 即时重算。

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
    days_since_setup INTEGER,             -- 兼容：同 gap_setup_to_cd_days
    gap_setup_to_cd_days INTEGER,         -- 九转结束 → 十三转开始
    days_setup_to_scan INTEGER,           -- 九转完成 → 扫描日

    detail_json TEXT,                     -- 子页：九转/十三转逐日明细 + 过滤器

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
| `td_history_days` | `120` | 调度 | 缓存最少交易日（日 K） |
| `td_lookback_days` | `20` | 回溯 | 扫描日向前统计九转/十三转的交易日窗 |
| `td_vol_shrink_ratio` | `0.8` | 量价 | 低于前 5 日均量比例 → 缩量 |
| `td_vol_expand_ratio` | `1.2` | 量价 | 高于前 5 日均量比例 → 放量 |
| `td_shadow_lower_min` | `0.5` | 量价 | 下影线占比下限（锤子） |
| `td_cross_body_max` | `0.15` | 量价 | 十字实体占比上限 |
| `td_bear_lower_max` | `0.2` | 量价 | 大阴线：下影过小阈值 |
| `td_vol_price_mode` | `or` | 量价 | 合格条件：`or` / `and` |
| `td_countdown_near_min` | `10` | Countdown | 临近 13：最少已计数 |
| `td_countdown_near_max` | `12` | Countdown | 临近 13：最多已计数 |
| `td_countdown_after_setup_days` | `5` | Countdown | 列3：自九转完成日至扫描日最大交易日数 |
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
| GET | `/api/td-sequential/board` | `{ lookback_days, funnel, columns: { "1": [...], …, "5": [...] } }` |
| GET | `/api/td-sequential/stocks/{stock_code}` | 个股明细（`setup_bars` / `countdown_bars` / `filters`） |
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
dashboard/td-sequential-detail.html   # 个股九转/十三转明细
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
| 计算口径 | Layer 1 标准 TD + Layer 2–5 过滤器；**仅抄底**；**仅日 K** |
| 股票池 | 全 A，排除 ST、停牌 |
| 页面形态 | **五列递进漏斗** + **个股明细子页** |
| 逃顶 | v1 **不做** |
| 日线缓存 | **复用** `train_track_daily_cache` |
| 列内去重 | 每股 **仅出现在最高达标列** |
| 回溯统计 | 统一 `lookback_days`：窗内达成的九转/十三转均入选对应列（默认 20 交易日） |
| 九转 vs 十三转 | **两段独立**；十三转自九转完成 **次日** 起算 |
| 多组九转 | 只取 **`setup_9_date` 最新一组** 做判定与展示 |
| 列 3 时间窗 | 自九转完成至扫描日 ≤ **5** 个交易日（`countdown_after_setup_days`） |
| 明细子页 | 逐日列出九转 9 天、十三转各计数日及比较价、过滤器结果 |

---

## 11. 风险与已知局限

1. **单边暴跌**：绿 9/13 可能连续出现仍继续下跌；文档与 UI 需提示「警报器」定位。
2. **与通达信差异**：部分软件 Countdown 起算日、13/8 规则有简化实现；本项目以 §3 公式为准，上线后用样本股人工比对 1–2 只校验。
3. **扫描耗时**：全 A × 120 日状态机，预计与火车轨同量级；必须后台任务 + 进度，避免 HTTP 超时。
4. **列 3 窗口较紧**：九转后 5 日内要数到 10–12 次较苛刻，样本可能很少；可调 `countdown_near_min` 或 `countdown_after_setup_days`。

---

## 12. 验收标准（开发完成后）

- [ ] 单测覆盖：Setup 连续/中断、Countdown 非连续、13/8 规则、**多组九转取最新**、量价过滤器、MACD 背离
- [ ] 全 A 扫描落库，`funnel_json` 五列计数与列内列表一致（`lookback_days` 窗）
- [ ] 看板五列展示，管理页可改参数并重算
- [ ] 个股明细子页：九转/十三转逐日表 + 过滤器结果，仅展示最新一组
- [ ] 日常 `fetch_ts_daily` 后缓存满足 `td_history_days`
- [ ] 导航可达；空池时有友好提示

---

## 13. 参考口诀（产品文案）

> 抄底等缩量长腿，逃顶等放量滞涨；缩量涨出九别慌，放量跌出九别抢。

v1 页面仅展示 **前半句（抄底）** 相关提示。
