# Trend_Analysis

A 股**行业板块成交额**分析（Phase 1）。

## 文档

- [需求文档](docs/REQUIREMENTS.md)
- [实现方案](docs/IMPLEMENTATION_PLAN.md)

## 环境要求

- **Python 3.10+**
- **必盈 API 证书**（推荐）：https://www.biyingapi.com/doc_hs
- 或 BigQuant AK/SK（需 Python 3.11+ 与 SDK 权限）

## 快速开始（必盈 API，推荐）

```bash
cd ~/Trend_Analysis
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# BigQuant 用户额外安装（需 Python 3.11+ 且使用官方 PyPI 源）：
# pip install -r requirements-bigquant.txt -i https://pypi.bigquant.com/simple/

export BIYING_LICENCE=你的licence

# 交易日收盘后（数据约 16:20 后更新）
# 无包年/白金证书时必须加 --no-all-turnover
python3 scripts/fetch_by_daily.py --no-all-turnover

# 清空旧数据后全量重拉
python3 scripts/fetch_by_daily.py --fresh --no-all-turnover

# 申万二级行业映射
python3 scripts/fetch_by_daily.py --level l2 --no-all-turnover

ls data/
```

### 输出文件

| 文件 | 必盈接口 |
|------|----------|
| `sectors.csv` | `hszg/list` 行业/概念树 |
| `sector_stock_mapping.csv` | `hszg/gg/{板块代码}` |
| `stock_turnover_latest.csv` | `hsrl/ssjy/all` 或 `ssjy_more` 的 `cje` |
| `sector_turnover_daily.csv` | 一级行业成交额汇总 |
| `unmapped_stocks.csv` | 遗漏检查 |

### 套餐说明

| 套餐 | 全市场成交额 | 每日调用 |
|------|-------------|----------|
| 免费版 | ❌ 需 `ssjy_more` 分批 | 200 次（不够跑全市场） |
| 包年版 ¥688/年 | ✅ `ssjy/all` 一次拉全 | 不限 |

## 快速开始（BigQuant）

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
