# 交易信号：反包打板（v4.2）

> 状态：**已确认** · 方案 B（纯 Tushare `rt_min`，不看主力资金）  
> 前置：[TUSHARE_API.md](./TUSHARE_API.md) · [BRANCHING.md](./BRANCHING.md)

---

## 1. 信号定义（一句话）

**交易日 09:30–09:40** 内，**沪主板 `60` + 深主板 `00`** 个股同时满足：

1. **涨幅**：`(现价 - 昨收) / 昨收 × 100 ≥ 9.8%`（封板单独标注）
2. **反包走弱**：T-1 为阴线 / 十字星 / 长上影之一，且今日按配置的反包口径反包 T-1

**两条全中** → `signal_hit`（反包打板）；`score` 为命中条数（0–2），用于盯 **1/2 临界票**。

> **v4.2 明确不做**：盘中主力资金净流入（Tushare 无盘中 `moneyflow`）。

---

## 2. 数据源（Tushare only）

| 用途 | 接口 | 说明 |
|------|------|------|
| 盘中现价 / 今开 | **`rt_min`** `freq=1MIN` | 通配 `6*.SH`、`0*.SZ` 分批拉取；`close` 作现价 |
| T-1 日 K（形态） | **`daily`** | 不复权；盘前/首轮扫描预加载上一交易日 |
| 昨收 | **`daily.pre_close`** | 与 `rt_min` 配套算涨幅；不一致时剔除 |
| 涨停价 | **`stk_limit`** | 当日 `up_limit`，现价 ≥ 涨停价 → `is_limit_up` |
| 股票池 / ST | **`stock_basic`** | 仅 `60/00` 主板，名称含 ST 排除 |
| 停牌 | **`suspend_d`** | 当日停牌剔除 |

数据层抽象：`scripts/signal_feed.py`（`RtMinFeed`），便于日后换 `rt_k` 等实现。

---

## 3. 计算口径

### 3.1 T-1 走弱形态

几何量（不复权 OHLC）：

- `body = |close - open|`
- `amplitude = high - low`
- `upper_shadow = high - max(open, close)`

| 形态 | 条件 |
|------|------|
| 阴线 | `close < open` |
| 十字星 | `amplitude > 0` 且 `body / amplitude ≤ cross_body_ratio`（默认 0.1） |
| 长上影 | `body > 0` 且 `upper_shadow / body ≥ long_upper_ratio`（默认 1.0） |

任一命中 → `is_weak_t1`；`t1_shape` 为逗号拼接标签。

### 3.2 反包

| 模式 | 条件 |
|------|------|
| **high**（默认） | `last_price > pre_high` |
| **body** | `today_open ≤ pre_close` 且 `last_price ≥ pre_open` |

须 **同时** `is_weak_t1` 且反包成立，才计 `hit_pattern`。

`today_open`：当日首条 `rt_min` 的 `open`，扫描过程中缓存。

### 3.3 涨幅与封板

- `pct_change = (last_price - pre_close) / pre_close * 100`
- `hit_pct`：`pct_change ≥ pct_threshold`（默认 9.8）
- `is_limit_up`：`last_price ≥ up_limit - 1e-4`（有 `stk_limit` 时）

### 3.4 score

| score | 含义 | 展示 |
|-------|------|------|
| 2 | 两条全中 | 高亮（`signal_hit`） |
| 1 | 临界 | 灰色 |
| 0 | 不展示 | — |

列表默认 **`score ≥ 1`**。

---

## 4. 调度与窗口

| 项 | 默认 |
|----|------|
| 后端轮询时段 | 交易日 **09:25–09:45** |
| 信号记入窗口 | **09:30–09:40**（仅此时可 **新增** 标的） |
| 09:40 后 | 不再新增；可更新已入选行的最新价/涨幅；支持 **手动刷新** 看最终态 |
| 刷新间隔 | **15 秒** |
| 数据新鲜度 | `rt_min.time` 与当前时间差 > `data_stale_sec`（默认 120s）→ 跳过该票 |

配置键见 `app_settings`（管理页「信号参数」）。

---

## 5. 存储

表 `signal_hit_v4`（每股每交易日一行）：

| 字段 | 说明 |
|------|------|
| `trade_date`, `stock_code` | 主键 |
| `stock_name` | |
| `first_hit_at` | 首次 score≥1 时间 |
| `last_seen_at` | 最近扫描时间 |
| `last_price`, `pct_change`, `max_pct` | |
| `pre_close`, `pre_high`, `pre_open`, `today_open` | |
| `t1_shape`, `engulf_type` | |
| `is_limit_up` | 0/1 |
| `score`, `signal_hit` | |
| `hit_pct`, `hit_pattern` | 分项 0/1 |

---

## 6. API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/signals/meta` | 窗口状态、最近扫描、是否冻结 |
| GET | `/api/signals/today?min_score=1` | 当日信号列表 |
| POST | `/api/admin/signals/scan` | 手动触发一轮扫描 |

---

## 7. 前端

- 路由：`/signals.html`
- 顶栏：**交易信号**（在「股票清单」之后）
- 表格：代码、名称、涨幅、涨停、T-1 形态、反包类型、score、首次触发时间
- 非信号时段：展示当日已触发列表 + 状态说明；盘中 15s 自动轮询 API

---

## 8. 验收

1. 交易日 09:30–09:40 内，满足条件的股票进入列表；2/2 行高亮，1/2 灰色。
2. 09:40 后不再出现新代码；手动刷新可更新已入选行价格。
3. ST、停牌、创业板/科创板不出现。
4. 管理页可改阈值/窗口/反包模式并持久化。
