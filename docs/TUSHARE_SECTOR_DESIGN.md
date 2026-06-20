# Tushare 换源与四套行业看板设计（v4.0）

> 状态：**已确认，待开发**  
> 确认日期：2026-06-18  
> 前置：[REQUIREMENTS.md](./REQUIREMENTS.md) · [TUSHARE_API.md](./TUSHARE_API.md)  
> 分支策略：[BRANCHING.md](./BRANCHING.md)

---

## 1. 目标摘要

| 项 | 决策 |
|----|------|
| 数据源 | **Tushare Pro** 替代必盈（`BIYING_LICENCE` 退役） |
| 认证 | `TUSHARE_TOKEN`（仅存 `.env`，**禁止提交 Git**） |
| 账号积分 | **10100**（四套行业 + ETF 历史均满足） |
| 板块视角 | **仅行业细分**，移除热门概念 / 概念板块 / 主题标签 |
| 行业体系 | 申万三级 · 中信三级 · 东财行业 · 同花顺行业（4 Tab） |
| 历史库 | **方案 A**：换源后 `history.db` **清空重拉** |
| 补数上限 | **≤400 交易日**（不变） |

---

## 2. 看板结构

### 2.1 页面 2 — 行业表格

**Tab 顺序（固定 4 个）：**

| 顺序 | Tab 名称 | API `kind` | 默认 |
|------|----------|------------|------|
| 1 | 申万三级 | `sw_l3` | **是（默认打开）** |
| 2 | 中信三级 | `ci_l3` | |
| 3 | 东财行业 | `dc_ind` | |
| 4 | 同花顺行业 | `ths_ind` | |

**移除：** `sw_l2`、`hot`、`board` 及所有概念/热门 Tab。

**名称展示：**

| 体系 | 卡片标题格式 | 示例 |
|------|-------------|------|
| 申万三级 | `{L1} > {L2} > {L3}` | `电子 > 元器件 > PCB` |
| 中信三级 | `{L1} > {L2} > {L3}` | `电子 > 元器件 > …` |
| 东财行业 | `{name}`（单层，无路径） | `半导体` |
| 同花顺行业 | `{name}`（`ths_index` type=I） | `半导体` |

**时间范围（页面 2）：** 默认 **5 日**；可选 **5 / 15 / 30** 个交易日（与页面 3 一致）。

**搜索：** 保留现有板块名称搜索（`card-search.js`）。

**排序（板块列表）：** 默认 **当日成交占全 A 比 ↓**（`turnover_pct_desc`，与现网一致）。  
后续可增：上涨家数占比 ↓、下跌家数占比 ↓（见 §4.3）。

**页脚：** 标注当前 N 个交易日；各体系 **未分类** 股票数量（若有）。

---

### 2.2 页面 3 — 行业图表

- Tab 与页面 2 **一一对应**（4 Tab，`kind` 相同）
- **搜索**：同页面 2
- **时间范围**：**5 / 15 / 30** 个交易日可选
- 图表指标：成交额、主买、主卖（与页面 1 风格一致，按选中行业展示）

---

### 2.3 页面 1 — 全 A 概览

- 保留：全 A **成交额、主买、主卖** 序列
- **新增时间维度**：**5 / 15 / 30** 个交易日可选（API `days=5|15|30`）

---

### 2.4 页面 4 — 成份股 / 个股

**成份股列表（从某 Tab 下钻）：**

- 仅展示 **当前 Tab 体系** 下该行业的股票
- **默认排序**：成交占全 A 比 ↓（`turnover_pct_desc`）
- **新增排序**：
  - 上涨比例 ↓（`up_ratio_desc`：涨家数 / 成份总数，按单股当日涨跌幅 `pct_chg>0`）
  - 下跌比例 ↓（`down_ratio_desc`：`pct_chg<0`）

**个股详情页：**

- 保留：近 N 日成交额 / 主买 / 主卖柱图
- **新增**：同时展示 **四套行业归属**（申万 / 中信 / 东财 / 同花顺；无归属显示「—」）

---

### 2.5 页面 5 / 6 — ETF（独立 Tab，不接行业四 Tab）

| 项 | 说明 |
|----|------|
| 定位 | 与行业 Tab **分离**，仍为 ETF 专用页 |
| 历史成交 | Tushare [`fund_daily`](https://tushare.pro/wctapi/documents/127.md)（`amount` 千元 → 元） |
| 列表 | [`fund_basic`](https://tushare.pro/document/2) 过滤 ETF |
| 份额/规模 | [`fund_share`](https://tushare.pro/document/2?doc_id=207)（**2000 积分起**；输出 `fd_share` 单位「万份」，差分作资金 proxy） |
| **主买/主卖/大单** | **Tushare 无 ETF 版 `moneyflow`**，**不提供**与 A 股一致的四档主动买卖 |
| 替代指标 | 成交额、涨跌幅、`pct_chg`、份额日变化（`fd_share` 差分）、占全 A 比 |
| 时间范围 | 5 / 15 / 30 日（与页面 1 对齐） |

> 若后续 Tushare 上线 ETF 资金流接口，在 `etf_daily` 表扩展字段即可；当前规格 **不阻塞 v4.0**。

---

## 3. 行业卡片指标（页面 2）

在现有「成交 / 买入 / 卖出 / 净值 + 占比」基础上，扩展为：

| # | 指标 | 存储字段（建议） | 占比分母 |
|---|------|-----------------|----------|
| 1 | 当日成交额 | `turnover` | 全 A 成交额 → `turnover_pct` |
| 2 | 主动买入金额 | `active_buy` | 全 A 主动买入 → `buy_pct` |
| 3 | 主动卖出金额 | `active_sell` | 全 A 主动卖出 → `sell_pct` |
| 4 | 净流入/流出 | `net_active` | 全 A 净流入总额 → `net_pct`（净出为负） |
| 5 | **主力买入**成交额 | `main_buy` | 全 A 主力买入 → `main_buy_pct` |
| 6 | **主力卖出**成交额 | `main_sell` | 全 A 主力卖出 → `main_sell_pct` |
| 7 | 上涨家数 | `up_count` | 板块成份数 → `up_ratio` |
| 8 | 下跌家数 | `down_count` | 板块成份数 → `down_ratio` |
| 9 | （可选展示）平盘家数 | `flat_count` | `flat_ratio` |

**口径定义（Tushare `moneyflow`，单位统一为「元」）：**

| 业务名 | 计算 |
|--------|------|
| 主动买入 | `(buy_sm + buy_md + buy_lg + buy_elg)_amount × 10000` |
| 主动卖出 | `(sell_sm + sell_md + sell_lg + sell_elg)_amount × 10000` |
| 主力买入 | `(buy_lg + buy_elg)_amount × 10000`（大单 + 特大单） |
| 主力卖出 | `(sell_lg + sell_elg)_amount × 10000` |
| **总净流入** | **`net_mf_amount × 10000`**（Tushare 直接给；**不要**用 `主买−主卖`，那个恒为 0） |
| **主力净流入** | `主力买入 − 主力卖出`（大单+特大单净额） |
| 成交额 | `daily.amount × 1000`（千元 → 元） |

> **实测校验（20250613）：** `sum(buy 四档) ≡ sum(sell 四档) ≡ 成交额`，故 `主买−主卖 ≡ 0`。净流入必须取 `net_mf_amount`；行业净流入与涨跌家数方向一致（如 IT服务 −68亿 / 涨13跌117，军工航空 +19亿 / 涨39跌9）。

**涨跌家数：** 成份股当日 `daily.pct_chg`：`>0` 上涨，`<0` 下跌，`=0` 或缺失计平盘。

**四档原子字段（可选落库）：** 继续保留 8 档 `zmb*`/`zms*` 映射至 Tushare 四档买卖，供详情页与导出；汇总规则与 v3.6 一致。

> **⚠ 口径迁移提示（已用真实数据核实，2026-06-20）：** v3.6 的 `active_buy/active_sell` 来自必盈 **L2 真实主动性买/卖盘（内外盘）**；v4.0 改用 Tushare `moneyflow` 四档买/卖金额之和，二者**语义不同**：
>
> - 实测（000001.SZ 20250613）：`buy 四档之和 ≈ sell 四档之和 ≈ 当日成交额`，即 **`active_buy ≈ active_sell ≈ turnover`、`active_buy + active_sell ≈ 2×成交额`**。Tushare `moneyflow` 的 buy/sell 是**按单规模拆分的买方/卖方成交总额**，不是内外盘主动盘。
> - 因此**主买/主卖的绝对值与占比对每个行业都 ≈ 成交额/成交占比，缺乏区分度**，不宜作为核心展示。
> - **真正有信号的是净额**：`净流入 = active_buy − active_sell`（= `net_mf_amount`）、`主力净流入 = main_buy − main_sell`。看板应以 **净流入 / 主力净流入及其占比** 为主指标；`active_buy/active_sell` 仅作明细/导出保留。
> - `main_buy/main_sell`（大单+特大单各方向）可分别展示，但同样建议突出其**净额**。
> - 因「方案 A 清空重拉」，新旧不混库；但前端文案需说明该口径变化，避免沿用 v3.6「主动盘」的理解。

---

## 4. 四套行业数据源

### 4.1 映射表

| kind | 分类来源 | 列表接口 | 成份接口 | 展示粒度 | 积分 |
|------|----------|----------|----------|----------|------|
| `sw_l3` | 申万 2021 | `index_classify` | `index_member_all` | L3（约 346） | 2000 |
| `ci_l3` | 中信 2020 | —（从 member 反推） | `ci_index_member` | L3（约 285） | 5000 |
| `dc_ind` | 东财 | `dc_index`（`idx_type=行业板块`） | `dc_member` | 行业板块最细层 | 6000 |
| `ths_ind` | 同花顺 | `ths_index`（`type=I` **仅行业**） | `ths_member`（见注） | 行业指数最细层 | 6000 |

> **注（`ths_member`）：** 官方文档（261）标题为「概念板块成分」，示例用概念指数；用于 `type=I` 行业指数成份属可行但未被官方明确背书。**开发第 1 步须先做连通性验证**：传一个行业指数 `ts_code` 确认能返回成份，否则改用 `ths_index` 列表 + 逐板块拉取或回退到其它三套。

**明确排除：**

- 同花顺 `type=N`（概念）、`ST/S/TH/R`（风格/主题/地域）
- 东财 `idx_type=概念板块|地域板块`
- 必盈 `type2=2|3` 及 `concept_*` 表（换源后废弃或只读归档）

**一股一行归属（每体系）：**

- 申万 / 中信：每体系 **一股一个主行业（L3）**
- 东财 / 同花顺：每体系 **一股一个主行业板块**（从 member 取当前归属）
- 无归属 → 归入 **`未分类`**（`sector_code=UNMAPPED`），汇总单独一行，页脚提示数量

**历史归属的口径与局限（重要）：**

| 体系 | 历史成份字段 | 历史回溯能力 |
|------|-------------|-------------|
| 申万 `index_member_all` | 含 `in_date/out_date` | 可按时点回溯，但官方数据存在**部分个股历史区间缺失/不连贯**（已知 issue），需对缺口做兜底 |
| 中信 `ci_index_member` | 含 `in_date/out_date` | 可按时点回溯 |
| 东财 `dc_member` | 支持 `trade_date` 历史查询 | 可按交易日回溯 |
| 同花顺 `ths_member` | `in_date/out_date/weight` 官方标注 **「暂无」**，仅 `is_new` 当前快照 | **无法按时点回溯**，400 日补数只能用**当前成份近似历史**（存在幸存者偏差） |

> 即：v4.0 的「行业归属」整体采用**当前快照映射**（每周刷新）作为主口径；申万/中信/东财可选做历史时点修正，**同花顺仅有当前快照**。看板页脚或文档需说明历史区间的归属为近似值。

**路径字段（申万/中信）：** 落库 `sector_path` 或拼接 `l1_name > l2_name > l3_name` 供前端展示。

---

### 4.2 聚合原则

```
daily(trade_date)           → 个股 turnover、pct_chg
moneyflow(trade_date)       → 个股四档买卖（19:00 后完整）
member 接口（每周刷新）      → 行业归属（当前快照为主口径，见 §4.1 历史局限表）
        ↓ 本地聚合
sector_daily(kind=…)        → 四套行业各自一张逻辑表（或 sector_kind 列）
market_daily                → 全 A 汇总（含主力买卖合计，供占比分母）
```

**不采用**板块指数自带成交额（`ci_daily`/`ths_daily`）作为主数据，仅作校验抽样。

**涨跌家数校验：** 本地按成份股 `daily.pct_chg` 聚合 `up_count/down_count`。东财 `dc_index` 自带官方 `up_num/down_num`，可作抽样校验；因停牌、成份口径、当日新上市等差异，**本地值与官方值允许小幅偏差**（建议阈值 ±2 家或 ±2%），不强制完全一致。

---

### 4.3 排序枚举（API `sort`）

**板块表 / 图表：**

| 值 | 说明 |
|----|------|
| `turnover_pct_desc` | 当日成交占全 A ↓（**默认**） |
| `turnover_pct_asc` | 当日成交占全 A ↑ |
| `up_ratio_desc` | 上涨家数占比 ↓（**新增**） |
| `down_ratio_desc` | 下跌家数占比 ↓（**新增**） |

**成份股：**

| 值 | 说明 |
|----|------|
| `turnover_pct_desc` | **默认** |
| `up_ratio_desc` | 按涨跌幅是否为正（单股无 ratio 时用 `pct_chg_desc` 代理上涨强度） |
| `down_ratio_desc` | 按 `pct_chg_asc`（跌幅靠前） |

> 成份股「上涨/下跌比例排序」在单股粒度实现为：**按 pct_chg 排序**；板块卡片上的 `up_ratio`/`down_ratio` 为 **家数占比**。

---

## 5. 采集与调度

### 5.1 Tushare 更新时间（据官方文档）

| 接口 | 更新时间 | 调度建议 |
|------|----------|----------|
| `daily` | 交易日 **15:00–17:00** | 最早 **17:30** 后拉取 |
| `moneyflow` | 交易日 **19:00** 后 | 最早 **19:30** 后拉取 |
| `fund_daily` | 盘后 | **19:30** 后与 A 股同批或略晚 |
| `fund_share` | 次日 **08:30** 左右（交易所） | **09:00** 单独 job 或并入次日晨间 |
| 行业映射 | 低频 | **每周日 02:00** `refresh_sector_mappings.py` |

**默认日采 cron：** **21:35**（与 v3.6 相同，已覆盖 moneyflow 就绪时间）。  
管理页可配置；文档默认写 **21:35 Asia/Shanghai**。

### 5.2 脚本规划

| 脚本 | 职责 | 状态 |
|------|------|------|
| `scripts/ts_common.py` | Token/.env、限频重试、换算、moneyflow 聚合（含 `net_mf_amount` 净流入） | ✅ |
| `scripts/ts_sectors.py` | 四套行业映射归一化 + 联网拉取（分页/缓存） | ✅ |
| `scripts/ts_aggregate.py` | 行业聚合（净流入/主力净/涨跌家数/各占比/未分类/零成份占位） | ✅ |
| `scripts/ts_store.py` | v4 SQLite 层（`*_v4` 表）+ 看板读取 | ✅ |
| `scripts/fetch_ts_daily.py` | 采集编排：daily+moneyflow+四套聚合+ETF；`--start/--end`、`--kinds`、`--mapping-only`、`--refresh-mapping` | ✅ |

**调度接线（`api/job_worker.py` + `scripts/scheduler.py`）：**

- 每日 **21:35**：`job_worker` spawn `fetch_ts_daily`（缓存映射，约 8 秒），管理页补数同路径。
- 每周日 **02:00**：`scheduler` 调 `fetch_ts_daily --mapping-only` 刷新四套映射（含同花顺，约 8 分钟）。
- 首次/换源建库：`fetch_ts_daily --mapping-only` 后 `fetch_ts_daily --start --end`（≤400 交易日）。

### 5.3 换源迁移（方案 A）

1. 备份 `data/history.db` → `history.db.bak.biying`
2. 删除或清空 `history.db`
3. 跑映射刷新 → 区间补数（≤400 日）→ 验证看板
4. `.env`：`TUSHARE_TOKEN=…`；`BIYING_LICENCE` 可注释

---

## 6. 数据库变更（概要）

| 表 | 变更 |
|----|------|
| `sector_daily` | 增加 `kind`（`sw_l3|ci_l3|dc_ind|ths_ind`）；扩展 `main_buy/main_sell/up_count/down_count/…`；`sector_path` |
| `stock_daily` | 增加 `main_buy/main_sell/pct_chg`；四套行业 code/name 字段或 JSON `industry_tags` |
| `concept_*` | **停用**（不再写入） |
| `etf_daily` | 用 `fund_daily` + 可选 `fund_share`（`fd_share` 万份）字段 |
| `app_settings` | 默认 `days` 选项支持 5/15/30 |

---

## 7. API 变更（概要）

| 端点 | 变更 |
|------|------|
| `GET /api/market?days=5|15|30` | 扩展 days（沿用现网端点名，不新增 `/series`） |
| `GET /api/sectors/table?kind=sw_l3|ci_l3|dc_ind|ths_ind&days=&sort=` | 新 kind；响应含新指标 |
| `GET /api/sectors/{code}/stocks` | 新 sort；仅当前 kind |
| `GET /api/stocks/{code}` | 返回四套行业归属 |
| `GET /api/etf/...` | Tushare 源；days 5/15/30 |

---

## 8. 验收标准

| # | 项 | 标准 |
|---|-----|------|
| 1 | 四套 Tab | 各有数据，默认申万三级；无 hot/board |
| 2 | 申万/中信标题 | 含 `L1 > L2 > L3` 路径 |
| 3 | 卡片指标 | §3 共 8 类指标 + 占比正确 |
| 4 | 未分类 | 有则单独统计，页脚可见 |
| 5 | 页面 1/2/3 | 5/15/30 日切换正常 |
| 6 | 成份股排序 | 成交占比 / 涨跌幅排序可用 |
| 7 | 个股页 | 四套行业归属展示 |
| 8 | ETF | 历史成交额 + 份额变化；**无** ETF 主买卖（文档说明） |
| 9 | 补数 | 单次 ≤400 交易日 |
| 10 | 定时 | 映射每周 + 日采 21:35 |

---

## 9. 已确认的产品决策（归档）

- [x] 4 Tab 顺序：申万三级 \| 中信三级 \| 东财行业 \| 同花顺行业；默认申万三级  
- [x] 页面 3 同 4 Tab + 搜索 + 5/15/30 日  
- [x] 申万/中信卡片名称带完整路径  
- [x] 卡片指标：成交/主动买卖/净流/主力买卖/涨跌家数及占比  
- [x] 板块默认排序：当日成交占比 ↓  
- [x] 成份股：默认成交占比；增加涨跌相关排序  
- [x] 下钻仅当前体系；个股页展示四套归属  
- [x] 未分类单独一行 + 页脚提示  
- [x] history.db 清空重拉  
- [x] 补数 ≤400 交易日  
- [x] 映射每周 + 日采按 Tushare 更新时间（默认 21:35）  
- [x] 积分 10100，四套全开  
- [x] Token 由运维写入 `.env`（不入库）  
- [x] ETF 独立页；历史成交 + 份额；无 ETF 主买卖  
- [x] 页面 1 增加 5/15/30 日  

---

## 10. 开发顺序建议

1. `ts_common.py` + Token 读 `.env` + 单日试点  
2. 申万 L3 映射 + 聚合 + 页面 2 单 Tab 打通  
3. 扩展指标（主力、涨跌家数）+ 5/15/30 日  
4. 中信 / 东财 / 同花顺三 Tab  
5. 页面 3、成份股、个股四套归属  
6. ETF `fund_daily` + 份额  
7. 弃用必盈脚本路径、更新部署文档  
