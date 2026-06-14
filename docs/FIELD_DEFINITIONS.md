# 领域字段定义

本文档定义产品内部统一字段，与具体数据源（akshare / 付费数据）解耦。同步层负责映射，分析层只读统一模型。

## 1. 大盘 `market_fund_flow`

| 字段 | 类型 | 说明 | 单位 |
|------|------|------|------|
| trade_date | date | 交易日 | - |
| index_sh_close | float | 上证收盘价 | 点 |
| index_sh_pct_chg | float | 上证涨跌幅 | % |
| index_sz_close | float | 深证收盘价 | 点 |
| index_sz_pct_chg | float | 深证涨跌幅 | % |
| inflow_amount | float | 买入/流入资金 | 元 |
| outflow_amount | float | 卖出/流出资金 | 元 |
| net_inflow | float | 净流入（优先主力净额，否则流入-流出） | 元 |
| main_net_inflow | float | 主力净流入 | 元 |
| main_net_inflow_ratio | float | 主力净流入占成交额比 | % |
| super_large_net_inflow | float | 超大单净流入 | 元 |
| large_net_inflow | float | 大单净流入 | 元 |
| medium_net_inflow | float | 中单净流入 | 元 |
| small_net_inflow | float | 小单净流入 | 元 |
| data_source | string | 数据来源标识 | - |

**用途**：观察 A 股整体活跃度与资金方向。

## 2. 板块 `sector_fund_flow`

| 字段 | 类型 | 说明 |
|------|------|------|
| trade_date | date | 交易日 |
| sector_type | enum | `industry` 行业 / `concept` 概念 / `region` 地域 |
| sector_name | string | 板块名称 |
| stock_count | int | 板块内个股数量（同花顺源提供，东财需另行统计） |
| pct_chg | float | 板块涨跌幅 % |
| inflow_amount | float | 流入资金（元） |
| outflow_amount | float | 流出资金（元） |
| net_inflow | float | 净流入（元） |
| main_net_inflow* | float | 主力净流入及分单字段（同大盘） |
| data_source | string | 数据来源 |

**分析层衍生字段**（`analysis_snapshot`）：

- `rank_no`：板块净流入排名
- `market_share`：板块净流入 / 大盘净流入 × 100%

## 3. 个股 `stock_fund_flow`

| 字段 | 类型 | 说明 |
|------|------|------|
| trade_date | date | 交易日 |
| stock_code | string | 6 位代码 |
| stock_name | string | 简称 |
| sector_name | string | 所属板块（东财板块个股接口可填充） |
| price / pct_chg | float | 最新价、涨跌幅 |
| turnover | float | 成交额（元） |
| inflow_amount / outflow_amount / net_inflow | float | 买卖流量 |
| main_net_inflow* | float | 主力及分单 |
| data_source | string | 数据来源 |

**分析层衍生**：

- `market_share`：个股净流入 / 大盘净流入
- `parent_share`：个股净流入 / 所属板块净流入

## 4. ETF `etf_fund_flow`

| 字段 | 类型 | 说明 |
|------|------|------|
| trade_date | date | 交易日 |
| etf_code / etf_name | string | ETF 代码与名称 |
| volume / turnover | float | 成交量、成交额 |
| main_net_inflow* | float | 主力及分单净流入 |
| data_source | string | 数据来源 |

**分析层衍生**：`market_share` = ETF 主力净流入 / 大盘净流入。

## 5. 历史与趋势限制（降级方案）

| 层级 | akshare 当日快照 | 历史日线 |
|------|------------------|----------|
| 大盘 | 东财 `stock_market_fund_flow` 最近约 120 日 | 可每日定时落库积累 |
| 板块排名 | 今日 / 5 日 / 10 日 | 单板块历史：`stock_sector_fund_flow_hist` |
| 个股排名 | 今日 / 3 / 5 / 10 日 | 单股历史：`stock_individual_fund_flow` 约 100 日 |
| ETF | `fund_etf_spot_em` 当日 | 需每日落库 |

**结论**：无全市场「历史每日截面」免费接口；通过 **每日收盘后 sync 落库** 自建历史，后续可替换付费数据源而不改分析层。

## 6. 金额单位约定

- 库内统一 **元（float）**
- 同花顺接口常见「亿」「万」字符串，由 `core.utils.parse_money_yuan` 转换
- 东财接口一般为数值型元
