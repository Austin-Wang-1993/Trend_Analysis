# Trend_Analysis

A 股**申万行业成交额**分析（Phase 1）。

## 文档

- [需求文档](docs/REQUIREMENTS.md) — BigQuant + 申万 2021
- [实现方案](docs/IMPLEMENTATION_PLAN.md)

## 快速开始（腾讯云国内节点，交易日 17:00 后）

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -i https://pypi.bigquant.com/simple/
bq auth --apikey <你的AK.SK>

# 指定历史交易日
python scripts/fetch_daily_data.py --date 2024-06-12

# 不指定则取最近一个工作日
python scripts/fetch_daily_data.py

# 完整历史申万成份回填（2023-07-05 起）
python scripts/fetch_historical.py --start-date 2024-01-01 --end-date 2024-12-31

ls data/
ls data/history/
```

## 数据源

| 用途 | BigQuant 表 |
|------|-------------|
| 个股 ↔ 申万行业映射（**每日历史成份**） | `cn_stock_industry_component`（`industry = sw2021`） |
| 个股成交额 / 成交量 | `cn_stock_bar1d`（`amount` 为主指标） |

历史成交额汇总必须与**当日成份** JOIN（`b.date = c.date`），不能用最新成份回算历史。

输出见 `data/*.csv`（单日）与 `data/history/*.csv`（历史回填）。
