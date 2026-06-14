# 需求文档：A 股申万行业成交额分析（Phase 1）

> 版本：v1.0（BigQuant + 申万 2021）  
> 状态：**数据源已确认**

---

## 1. 项目目标

基于 **申万 2021 行业分类**，构建 A 股 **成交额** 三层分析能力：

1. 行业 ↔ 个股映射（按交易日）
2. 大盘 / 行业 / 个股成交额
3. 支持指定历史交易日查询，并为后续趋势看板积累数据

---

## 2. 数据源

| 角色 | 平台 | 说明 |
|------|------|------|
| 数据提供 | [BigQuant](https://bigquant.com) | 云端 DAI SQL，SDK 拉取 |
| 部署 | 腾讯云国内 CVM | `pip install bigquant` + AK/SK 认证 |
| 更新频率 | 每交易日 **17:00 后** | 拉取当日已收盘数据 |

不再使用东财 akshare 作为主数据源（接口不稳定）。

---

## 3. 数据表

### 3.1 个股与板块映射

**表名**：`cn_stock_industry_component`  
**文档**：https://bigquant.com/data/datasources/cn_stock_industry_component

| 属性 | 说明 |
|------|------|
| 频率 | **日频**（每个交易日一条成份记录） |
| 行业标准 | 固定使用 `industry = 'sw2021'`（申万 2021） |
| 主键 | `date` + `instrument` + `industry` |

**核心字段（平台 → 统一字段）**

| 平台字段 | 统一字段 | 说明 |
|----------|----------|------|
| `date` | `trade_date` | 交易日 |
| `instrument` | `stock_code` | 如 `600519.SH` |
| `industry_level1_code` | `industry_l1_code` | 一级行业代码 |
| `industry_level1_name` | `industry_l1_name` | 一级行业名称 |
| `industry_level2_code` | `industry_l2_code` | 二级行业代码 |
| `industry_level2_name` | `industry_l2_name` | 二级行业名称 |
| `industry_level3_code` | `industry_l3_code` | 三级行业代码 |
| `industry_level3_name` | `industry_l3_name` | 三级行业名称 |
| `industry_name` | `industry_name` | 股票所属行业简称（叶子行业） |

**板块层级约定（Phase 1）**

- **板块汇总默认按一级行业**（`industry_l1_code` / `industry_l1_name`）
- 映射表保留二、三级字段，便于后续下钻

**历史成份约定（已确认）**

- 使用 `cn_stock_industry_component` **日频全量记录**，每个交易日反映当日真实成份
- 历史成交额必须与 `b.date = c.date` 点-in-time JOIN，**禁止**用最新成份回算历史
- 成份表可用起始日：**2023-07-05**（此前无日频成份数据）
- 行业进出事件（非日频）可参考 `cn_stock_industry_change`

### 3.2 个股及板块交易行情

**表名**：`cn_stock_bar1d`（股票后复权日行情）  
**文档**：https://bigquant.com/data/datasources/cn_stock_bar1d

| 属性 | 说明 |
|------|------|
| 频率 | 日频 |
| 主键 | `date` + `instrument` |
| 历史 | 约 2005 年起 |

**本阶段使用字段**

| 平台字段 | 统一字段 | 说明 |
|----------|----------|------|
| `date` | `trade_date` | 交易日 |
| `instrument` | `stock_code` | 证券代码 |
| `name` | `stock_name` | 证券简称 |
| `volume` | `volume` | 成交量（股） |
| `amount` | `turnover` | **成交金额（元）** — 主指标 |
| `turn` | `turnover_rate` | 换手率 |
| `change_ratio` | `pct_chg` | 涨跌幅（后复权） |

> 说明：口语中的「交易量」在本项目中 **以 `amount`（成交额）为主指标**；`volume`（成交量）一并落库备用。

### 3.3 辅助表（可选）

**`cn_stock_industry`**：申万行业代码层级字典（静态），用于校验行业列表。  
https://bigquant.com/data/datasources/cn_stock_industry

---

## 4. 衍生数据逻辑

### 4.1 大盘成交额

```sql
SELECT SUM(amount) AS total_turnover, COUNT(*) AS stock_count
FROM cn_stock_bar1d
WHERE date = '{trade_date}'
```

### 4.2 行业成交额（一级申万行业）

```sql
SELECT
    c.industry_level1_code,
    c.industry_level1_name,
    SUM(b.amount) AS turnover,
    COUNT(DISTINCT b.instrument) AS stock_count
FROM cn_stock_bar1d b
JOIN cn_stock_industry_component c
  ON b.date = c.date AND b.instrument = c.instrument
WHERE b.date = '{trade_date}'
  AND c.industry = 'sw2021'
GROUP BY 1, 2
```

### 4.3 个股成交额（带行业归属）

```sql
SELECT
    b.date, b.instrument, b.name, b.amount, b.volume,
    c.industry_level1_code, c.industry_level1_name,
    c.industry_level3_code, c.industry_level3_name
FROM cn_stock_bar1d b
JOIN cn_stock_industry_component c
  ON b.date = c.date AND b.instrument = c.instrument
WHERE b.date = '{trade_date}'
  AND c.industry = 'sw2021'
```

### 4.4 占比（分析层）

| 指标 | 公式 |
|------|------|
| 行业占大盘 | `industry.turnover / market.total_turnover` |
| 个股占行业 | `stock.turnover / industry.turnover` |
| 个股占大盘 | `stock.turnover / market.total_turnover` |

---

## 5. 交付物（CSV）

| 文件 | 内容 |
|------|------|
| `industry_stock_mapping.csv` | 某日行业-个股映射（含 L1/L2/L3） |
| `market_turnover_daily.csv` | 大盘成交额 |
| `industry_turnover_daily.csv` | 一级行业成交额 |
| `stock_turnover_daily.csv` | 个股成交额 + 行业归属 |
| `data/README.md` | 采集元数据 |

**历史回填（`data/history/`）**

| 文件 | 内容 |
|------|------|
| `industry_stock_mapping_history.csv` | 完整历史日频申万成份 |
| `market_turnover_history.csv` | 历史每日大盘成交额 |
| `industry_turnover_history.csv` | 历史每日一级行业成交额 |
| `stock_turnover_history.csv` | 历史每日个股成交额（可选，`--include-stocks`） |

---

## 6. 已确认决策

| 项 | 决策 |
|----|------|
| 数据源 | BigQuant DAI |
| 行业体系 | 申万 2021（`sw2021`） |
| 历史成份 | 日频 `cn_stock_industry_component`，点-in-time JOIN |
| 板块层级 | 一级行业汇总 |
| 主指标 | 成交额 `amount` |
| 映射表 | `cn_stock_industry_component` |
| 行情表 | `cn_stock_bar1d` |
| 当日定义 | 指定 `trade_date` 查询历史日线 |
| 交付格式 | CSV |
| 采集时间 | 每交易日 17:00 后 |
| 部署 | 腾讯云 + BigQuant AK/SK |

---

## 7. 前置条件

1. BigQuant 账号 + API Key（AK/SK）
2. 服务器执行：`bq auth --apikey <AK.SK>`
3. 确认账号对 `cn_stock_industry_component`、`cn_stock_bar1d` 有查询权限

---

## 8. 阶段规划

| 阶段 | 内容 |
|------|------|
| Phase 1 | 指定日期拉取 + CSV 验证 |
| Phase 2 | 每日定时 sync 落库（SQLite/CSV 归档） |
| Phase 3 | 占比分析 + 趋势看板 |
