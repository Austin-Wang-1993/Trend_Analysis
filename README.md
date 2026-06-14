# Trend_Analysis

A 股**申万行业成交额**分析（Phase 1）。

## 文档

- [需求文档](docs/REQUIREMENTS.md) — BigQuant + 申万 2021
- [实现方案](docs/IMPLEMENTATION_PLAN.md)

## 环境要求

- **Python 3.11+**（BigQuant SDK `0.1.10` 要求 `>=3.11,<3.14`；系统自带 3.10 不可用）
- BigQuant AK/SK
- 须从官方 PyPI 源安装：`https://pypi.bigquant.com/simple/`

## 快速开始（腾讯云国内节点，交易日 17:00 后）

```bash
# 若 python3 --version 低于 3.11，先安装 3.11（Ubuntu 22.04 示例）
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev

cd ~/Trend_Analysis
rm -rf .venv
python3.11 -m venv .venv && source .venv/bin/activate
python --version   # 应显示 3.11.x

pip install -r requirements.txt -i https://pypi.bigquant.com/simple/
# 将下方 AK.SK 替换为你在 BigQuant 平台获取的真实凭证（不要保留尖括号）
bq auth --apikey AK.xxxxxxxxxxxxxxxx.SK.xxxxxxxxxxxxxxxx

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

## 常见问题

**`No matching distribution found for bigquant>=1.0.0`**

BigQuant 官方 PyPI 当前最新版约为 `0.1.10`，请 `git pull` 后重装：

```bash
pip install -r requirements.txt -i https://pypi.bigquant.com/simple/
```

**`bash: syntax error near unexpected token 'newline'`**

说明 `bq auth` 行仍包含占位符 `<你的AK.SK>`，需换成真实 AK/SK。

**`ModuleNotFoundError: No module named 'bigquant'`**

通常是上一步 pip 安装失败，先确认 `pip show bigquant` 有输出再运行脚本。
