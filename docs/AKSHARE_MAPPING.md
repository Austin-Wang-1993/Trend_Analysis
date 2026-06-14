# akshare 接口字段映射

参考文档：[akshare 资金流向](https://akshare.akfamily.xyz/data/stock/stock.html#id173)

## 数据源策略

| 优先级 | 标识 | 说明 |
|--------|------|------|
| 1 | `eastmoney` | 东财：分单粒度细，板块/个股/大盘接口全 |
| 2 | `tonghuashun` | 同花顺：含流入/流出/净额、板块个股数；作降级 |

配置：`DATA_SOURCE_PRIORITY=eastmoney,tonghuashun`

## 大盘

| 统一字段 | 东财 `stock_market_fund_flow` | 同花顺（降级） |
|----------|------------------------------|----------------|
| trade_date | 日期 | 由 sync 推断 |
| index_sh_close | 上证-收盘价 | - |
| main_net_inflow | 主力净流入-净额 | 个股流入流出汇总 |
| inflow_amount | - | Σ 个股流入资金 |
| outflow_amount | - | Σ 个股流出资金 |

**限量**：单次约 120 个交易日；仅 sync 最新一日或指定日。

## 板块

### 东财 `stock_sector_fund_flow_rank`

参数：`indicator=今日`, `sector_type=行业资金流|概念资金流|地域资金流`

| 统一字段 | 东财列名 |
|----------|----------|
| sector_name | 名称 |
| pct_chg | 今日涨跌幅 |
| main_net_inflow | 今日主力净流入-净额 |
| main_net_inflow_ratio | 今日主力净流入-净占比 |
| super_large_net_inflow | 今日超大单净流入-净额 |
| ... | 大/中/小单同理 |

### 同花顺 `stock_fund_flow_industry` / `stock_fund_flow_concept`

参数：`symbol=即时`

| 统一字段 | 同花顺列名 | 备注 |
|----------|------------|------|
| sector_name | 行业 | 概念接口列名也为「行业」 |
| stock_count | 公司家数 | |
| pct_chg | 行业-涨跌幅 | 带 % 字符串 |
| inflow_amount | 流入资金 | 单位亿，需转换 |
| outflow_amount | 流出资金 | 单位亿 |
| net_inflow | 净额 | 单位亿 |

## 个股

### 东财 `stock_individual_fund_flow_rank`

参数：`indicator=今日`

| 统一字段 | 东财列名 |
|----------|----------|
| stock_code | 代码 |
| stock_name | 名称 |
| main_net_inflow | 今日主力净流入-净额 |
| pct_chg | 今日涨跌幅 |

### 东财 `stock_sector_fund_flow_summary`（板块内个股，可选扩展）

参数：`symbol=板块名`, `indicator=今日`

用于填充 `sector_name`，当前 MVP 以全市场个股榜为主。

### 同花顺 `stock_fund_flow_individual`

参数：`symbol=即时`

| 统一字段 | 同花顺列名 |
|----------|------------|
| stock_code | 股票代码 |
| inflow_amount | 流入资金 |
| outflow_amount | 流出资金 |
| net_inflow | 净额 |
| turnover | 成交额 |

## ETF

### 东财 `fund_etf_spot_em`

| 统一字段 | 东财列名 |
|----------|----------|
| trade_date | 数据日期 |
| etf_code | 代码 |
| main_net_inflow | 主力净流入-净额 |
| turnover | 成交额 |
| volume | 成交量 |

同花顺无对等 ETF 资金流接口，ETF 固定走东财。

## 历史接口（后续趋势看板）

| 接口 | 用途 |
|------|------|
| `stock_market_fund_flow` | 回补大盘历史 |
| `stock_sector_fund_flow_hist` | 单板块历史 |
| `stock_concept_fund_flow_hist` | 单概念历史 |
| `stock_individual_fund_flow` | 单股近 100 日 |

趋势看板 Phase 2：在现有 `analysis_snapshot` 上按 `trade_date` 聚合即可。
