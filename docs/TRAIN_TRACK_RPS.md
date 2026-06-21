# 火车轨选股（顺向火车轨 + RPS）v4.3

> 状态：**已确认**  
> 数据源：**Tushare Pro**（`daily` + `daily_basic`）  
> 参考：陶博士 RPS 体系 / 顺向火车轨 SXHCG 公式

---

## 1. 功能定位

**盘后选股观察池**（与盘中「交易信号」互补）：

- 每个交易日收盘后（默认 **16:30**）扫描 **全 A**（排除 ST、停牌）
- 同时满足 **SXHCG 五条件** + **近 20 日涨幅 < 阈值**（没大涨）
- 默认按 **RPS250 降序**，展示前 20（可切全部）
- 附加 **距 MA5/MA10** 与回踩标签，辅助「缩量回踩均线」手工买点

---

## 2. SXHCG 五条件（默认阈值可配）

### SXHCG1 — RPS 强度

```text
RPS120 + RPS250 > rps_sum_min（默认 185）
```

RPS 自算：全池 N 日涨幅百分位 × 99（见 §4）。

### SXHCG2 — 均线强势

| 子条件 | 默认 | 含义 |
|--------|------|------|
| C > MA20 | — | 收盘站上 20 日线 |
| COUNT(C>MA250, 30) ≥ | 25 | 近 30 日至少 25 日收盘在 250 日线上方 |
| COUNT(C>MA200, 30) ≥ | 25 | 近 30 日至少 25 日收盘在 200 日线上方 |
| COUNT(C>MA20, 10) ≥ 9 **或** (COUNT(C>MA10,4)≥3 且 COUNT(C>MA20,4)≥3) | — | 短期贴在均线上 |

### SXHCG3 — 强势未深调

| 子条件 | 默认 | 含义 |
|--------|------|------|
| C / HHV(C, 20) ≥ | 1 − drawdown_20_max（0.75） | 距 20 日收盘高点回撤 ≤ 25% |
| C / HHV(C, 250) > | near_high_250_min（0.8） | 收盘在 250 日高点 80% 以上 |

### SXHCG4 — 均线多头

满足其一即可：

- **A**：MA20 连 5 日上升，且 MA10 连续 5 日在 MA20 上方
- **B**：MA10、MA20 连 5 日上升，且 MA10 > MA20

### SXHCG5 — 换手

```text
turnover_rate < turnover_max（默认 10%）
```

优先 `daily_basic.turnover_rate`；**缺失时不因本条剔除**（无法判断是否过热）。

---

## 3. 方案 C 扩展

| 项 | 规则 |
|----|------|
| 没大涨 | 近 **20 交易日** 涨幅 < `recent_20d_pct_max`（默认 30%） |
| 距 MA5/MA10 | `dist_maX_pct = (close − MAx) / MAx × 100` |
| 回踩标签 | 距 MA5 或 MA10 在 `±ma_touch_band_pct`（默认 2%）内 → 标 `ma5` / `ma10` / `both` |

---

## 4. RPS 算法

对扫描日全 A 有效股票：

```text
ret_120 = close / close_120d_ago − 1
ret_250 = close / close_250d_ago − 1
RPS120 = percent_rank(ret_120) × 99
RPS250 = percent_rank(ret_250) × 99
```

与通达信扩展数据口径近似，非逐字相同。

---

## 5. 数据与调度

| 项 | 说明 |
|----|------|
| 历史深度 | 至少 **250 交易日** `daily` |
| 缓存表 | `train_track_daily_cache`（按日落库，增量更新） |
| 缓存写入 | **日常手动补数 / 定时采集**（`fetch_ts_daily`）会同步写入 OHLC+换手；扫描仅补缺失日 |
| 结果表 | `train_track_pick_v4`（每股扫描日一行） |
| 任务表 | `train_track_scan_jobs`（后台扫描进度） |
| 定时 | 默认 **16:30** 交易日（`train_track_enabled`） |
| 手动 | 管理页 / 选股页「立即重算」（后台任务，可轮询进度） |

**首次初始化建议**：在管理页「手动补数」选约 250 个交易日区间跑一遍（与看板数据一并更新），再在选股页点「立即重算」——此时多数日期已有缓存，进度会很快到「计算 RPS/SXHCG」。

---

## 6. API

| 方法 | 路径 |
|------|------|
| GET | `/api/train-track/meta` |
| GET | `/api/train-track/picks?limit=20&sort=rps250` |
| GET | `/api/train-track/scan/status?job_id=` |
| POST | `/api/admin/train-track/scan` → `{ job_id, status }` |

---

## 7. 管理页参数说明

见 `train_track_store.TRAIN_TRACK_SETTINGS_META`（代码内注释与 admin 页 footnote 一致）。

---

## 8. 验收

1. 收盘后列表为通过 SXHCG1–5 且近 20 日涨幅低于阈值的股票。
2. 默认按 RPS250 降序前 20；可展开全部。
3. 回踩标签在距 MA5/MA10 在带宽内时显示。
4. 管理页改阈值后下次扫描生效；参数旁有中文说明。
