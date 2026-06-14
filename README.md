# Trend_Analysis

A 股**行业板块成交额**分析（Phase 1）。

## 文档

- [需求文档](docs/REQUIREMENTS.md)
- [实现方案](docs/IMPLEMENTATION_PLAN.md)

## 环境要求

- **Python 3.11+**（BigQuant SDK 要求，[安装文档](https://bigquant.com/wiki/doc/vac4qwmQr4)）
- **BigQuant AK/SK**，且账号已开通 **SDK 使用权限**
- 安装需使用 BigQuant 官方 PyPI 源

## 快速开始（BigQuant，推荐）

```bash
cd ~/Trend_Analysis
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -i https://pypi.bigquant.com/simple/

# 认证（任选其一）
export BIGQUANT_APIKEY=你的AK.你的SK
# 或：bq auth --apikey 你的AK.你的SK

# 最近交易日（默认自动探测）
python scripts/fetch_bq_daily.py

# 指定历史交易日
python scripts/fetch_bq_daily.py --date 2024-06-12

# 切换行业标准：sw2021（默认）/ sw2014 / cs（中信）
python scripts/fetch_bq_daily.py --industry sw2021

ls data/
```

### 输出文件

| 文件 | 说明 |
|------|------|
| `sectors.csv` | 全量行业分类明细（`cn_stock_industry`） |
| `sector_stock_mapping.csv` | 板块 ↔ 个股映射（`cn_stock_industry_component`，逐日） |
| `stock_turnover_latest.csv` | 个股成交额 + 行业归属（`cn_stock_bar1d`） |
| `sector_turnover_daily.csv` | 一级行业成交额汇总 |
| `unmapped_stocks.csv` | 有成交额但无行业归属（遗漏检查） |

### 数据源

| 用途 | BigQuant 表 |
|------|-------------|
| 行业分类明细 | [cn_stock_industry](https://bigquant.com/data/datasources/cn_stock_industry) |
| 板块 ↔ 个股（逐日） | [cn_stock_industry_component](https://bigquant.com/data/datasources/cn_stock_industry_component) |
| 个股成交额 | [cn_stock_bar1d](https://bigquant.com/data/datasources/cn_stock_bar1d) 字段 `amount` |

## 常见问题

**`请先申请SDK使用权限`**

AK/SK 已配置但仍报错时，需到 [BigQuant](https://bigquant.com) 个人中心申请开通 **SDK 本地使用权限**。

**`No matching distribution found for bigquant`**

必须从官方源安装：

```bash
pip install bigquant -i https://pypi.bigquant.com/simple/
```

**Python 3.10 无法安装**

BigQuant SDK 要求 Python **3.11+**。腾讯云上可安装 `python3.11` 后重建 venv。

**检查未归类股票**

```bash
python scripts/list_unmapped_stocks.py
```

## 其他方案（旧）

- TickFlow 申万标的池：`scripts/fetch_daily_data.py`
- StockAPI 东财 BK 板块：`scripts/fetch_sector_data.py`
