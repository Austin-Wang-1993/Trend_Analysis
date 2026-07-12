# 量价吸筹（v4.6）

全 A 扫描（排除 ST、停牌），在 **120 交易日**窗口内识别「集中放量 → 缩量洗盘」形态。价格用 **前复权（qfq）实体价**（`max/min(Open,Close)`），成交量用 **原始 `vol`** 与 **前 5 日均量 MA5**（不含当日，`shift(1)`）比较。

## 1. 三阶段状态机

### 阶段一 T₁：集中放量

| 规则 | 说明 |
|------|------|
| 触发 T₀ | 当日 `V > vol_expand_trigger × MA5`（默认 2.0） |
| 动态阈值 | 第 k 日（k 从 0 计）要求 `V ≥ M_k × MA5`，`M_k = max(M_start − decay×k, floor)`，默认 `M_start=2.0`、`decay=0.1`、`floor=1.1` |
| 容错 | 累计最多 `expand_max_miss` 天不达标（默认 2）；**连续 3 天**不达标则结束放量段 |
| 价格 | 实体涨幅：段内最高实体价相对 T₀ 实体低价 ≥ `price_rise_min`（默认 30%） |
| 最短天数 | 放量段交易日数 **N ≥ 3** |

### 阶段二 T₂：缩量洗盘（与 T₁ 无缝衔接）

| 规则 | 说明 |
|------|------|
| 观察天数 | `M = int(wash_mult × N)` **向下取整**；`wash_mult` 可配 **1.0～1.5**（默认 1.5） |
| 缩量 | 每日 `V < vol_shrink_max × MA5`（默认 1.1） |
| 超标容忍 | 洗盘期内最多 **1 天**超标；**不能连续 2 天**超标 |
| 重置 | 洗盘期若 `V > vol_reset_trigger × MA5`（默认 2.0）：**旧形态作废**，以该日为新 T₀ 重新扫描 |
| 回撤 | 洗盘低点相对 T₁ 涨幅的回撤比例 ∈ [`drawdown_min`, `drawdown_max`]（默认 60%～90%） |

### 阶段三：输出

- 120 日内若有多组形态，**只保留最近一组**（T₀ 最晚且截至扫描日仍有效）。
- **入选锚点 B**：完成 T₁ 后进入 T₂ **进行中**即入选观察（不必等 M 天走完）；若洗盘已走完，需回撤比例落入区间。

## 2. 数据口径

| 字段 | 来源 |
|------|------|
| Open/Close | Tushare `daily` + `adj_factor` → 前复权（参考日 = 扫描日） |
| Volume | 原始 `vol`（不复权） |
| MA5 | 该股前 5 交易日 `vol` 算术均值（不含当日） |

缓存表：`accum_pattern_daily_cache`（`trade_date, stock_code, open, close, vol, adj_factor`）。

## 3. 可配置参数（管理页 `accum_*`）

见 `accum_pattern_store.py` 中 `ACCUM_PATTERN_SETTINGS_META`。

## 4. 模块清单

| 模块 | 路径 |
|------|------|
| 纯计算 | `scripts/accum_pattern_common.py` |
| 存储 | `scripts/accum_pattern_store.py` |
| 扫描 | `scripts/accum_pattern_scanner.py` |
| 任务 | `scripts/accum_pattern_runner.py` |
| API | `api/server.py` → `/api/accum-pattern/*` |
| 看板 | `dashboard/accum-pattern.html` |
| 明细 | `dashboard/accum-pattern-detail.html` |

## 5. API

- `GET /api/accum-pattern/meta`
- `GET /api/accum-pattern/picks?trade_date=&phase=`
- `GET /api/accum-pattern/stocks/{code}?trade_date=`
- `GET /api/accum-pattern/diagnose?stock_code=&t0_date=&scan_date=` — **形态检测**（见 §6）
- `GET /api/accum-pattern/scan/status`
- `POST /api/admin/accum-pattern/scan`

扫描任务 `progress` 字段：

| 阶段 | 格式 | 示例 |
|------|------|------|
| 补缓存 | `cache:当前/总数` | `cache:45/120` |
| 全市场计算 | `compute:当前/总数` | `compute:1250/4800` |

## 6. 形态检测（调试）

用于验证「我认为该入选但未扫出」的个案：指定 **T₀ 放量日** 与 **扫描日**，返回逐步判定结果。

### 输入

| 参数 | 必填 | 说明 |
|------|------|------|
| `stock_code` | 是 | 6 位代码 |
| `t0_date` | 是 | 您认为放量触发的 T₀（交易日） |
| `scan_date` | 否 | 观察/扫描日，默认最近交易日 |

### 输出步骤（`steps[]`）

1. T₀ 前历史 / T₀ 触发
2. T₁ 放量延续（含逐日量比明细 `days`）
3. T₁ N 天数 / 实体涨幅
4. T₂ 洗盘开始 / 缩量逐日
5. 回撤区间（洗盘完成时）
6. 入选规则（锚点 B）
7. **扫描器对比**：全窗 `find_latest_pattern` 实际采用的 T₀（可能晚于您指定的 T₀）

`status`：`pass` / `fail` / `warn` / `skip`。`failed_at` 为首个失败步骤 id。

### 入口

- 看板页「形态检测」区块
- API：`GET /api/accum-pattern/diagnose?...`

检测前会自动补全该股窗口内缺失的 qfq 缓存（与扫描相同数据源）。
