# 需求文档：A 股申万行业成交额分析（Phase 1）

> 版本：v1.1（TickFlow + 申万标的池）  
> 状态：**数据源已确认**

---

## 1. 项目目标

基于 **申万 2021 行业分类**，构建 A 股 **成交额** 三层分析能力：

1. 行业 ↔ 个股映射
2. 大盘 / 行业 / 个股成交额
3. 支持指定历史交易日查询，并为后续趋势看板积累数据

---

## 2. 数据源

| 角色 | 平台 | 说明 |
|------|------|------|
| 数据提供 | [TickFlow](https://tickflow.org) | REST API + Python SDK |
| 部署 | 腾讯云国内 CVM | `pip install tickflow`，`TICKFLOW_API_KEY` |
| 更新频率 | 每交易日 **17:00 后** | 拉取当日已收盘数据 |

文档：https://docs.tickflow.org/zh-Hans/api-reference/introduction

---

## 3. 数据能力映射

### 3.1 个股与申万行业映射

**来源**：TickFlow **标的池（Universe）** 申万系列

| 标的池 ID 模式 | 层级 | 示例 |
|----------------|------|------|
| `CN_Equity_SW1_{code}` | 一级 | `CN_Equity_SW1_280205` → SW1汽车 |
| `CN_Equity_SW2_{code}` | 二级 | `CN_Equity_SW2_410108` → SW2电力 |
| `CN_Equity_SW3_{code}` | 三级 | `CN_Equity_SW3_110404` → SW3宠物食品 |

通过 `tf.universes.list()` + `tf.universes.batch()` 获取各行业成份股列表，在本地合并为个股 → L1/L2/L3 映射表。

**成份口径（重要）**

- TickFlow 申万标的池为 **当前成份快照**
- **不提供** BigQuant 式逐日历史成份表（`cn_stock_industry_component`）
- 历史成交额回填时，行业归属使用**拉取时的当前标的池**归类

### 3.2 个股成交额

| 场景 | TickFlow 接口 | 字段 |
|------|---------------|------|
| 当日（17:00 后） | `tf.quotes.get(universes=["CN_Equity_A"])` | `amount` |
| 历史指定日 | `tf.klines.batch(..., period="1d")` | `amount` |
| 无 API Key | `TickFlow.free()` 仅支持历史日 K | `amount` |

### 3.3 板块汇总

- **默认按一级申万行业**（`CN_Equity_SW1_*`）汇总成份股 `amount` 之和

---

## 4. 衍生逻辑

### 4.1 大盘成交额

```text
SUM(stock.turnover)  # 全 A 或映射覆盖的股票
```

### 4.2 行业成交额

```text
GROUP BY industry_l1_code, industry_l1_name
SUM(stock.turnover)
```

### 4.3 占比（分析层，Phase 3）

| 指标 | 公式 |
|------|------|
| 行业占大盘 | `industry.turnover / market.total_turnover` |
| 个股占行业 | `stock.turnover / industry.turnover` |
| 个股占大盘 | `stock.turnover / market.total_turnover` |

---

## 5. 交付物（CSV）

| 文件 | 内容 |
|------|------|
| `industry_stock_mapping.csv` | 申万行业-个股映射（L1/L2/L3） |
| `market_turnover_daily.csv` | 大盘成交额 |
| `industry_turnover_daily.csv` | 一级行业成交额 |
| `stock_turnover_daily.csv` | 个股成交额 + 行业归属 |
| `data/README.md` | 采集元数据 |
| `data/cache/sw_mapping.json` | 申万映射缓存 |

---

## 6. 已确认决策

| 项 | 决策 |
|----|------|
| 数据源 | TickFlow |
| 行业体系 | 申万（标的池 `CN_Equity_SW*`） |
| 板块层级 | 一级行业汇总 |
| 主指标 | 成交额 `amount` |
| 历史成份 | 当前标的池快照（非逐日） |
| 交付格式 | CSV |
| 采集时间 | 每交易日 17:00 后 |
| Python | 3.10+ |

---

## 7. 前置条件

1. `pip install "tickflow[all]" pandas`
2. 注册 TickFlow 获取 API Key（当日实时行情需要）
3. `export TICKFLOW_API_KEY=...`

---

## 8. 阶段规划

| 阶段 | 内容 |
|------|------|
| Phase 1 | 指定日期拉取 + CSV 验证 |
| Phase 2 | 每日定时 sync 落库 |
| Phase 3 | 占比分析 + 趋势看板 |
