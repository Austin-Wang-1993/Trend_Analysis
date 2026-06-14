# Trend_Analysis

A 股**申万行业成交额**分析（Phase 1）。

## 文档

- [需求文档](docs/REQUIREMENTS.md)
- [实现方案](docs/IMPLEMENTATION_PLAN.md)

## 环境要求

- **Python 3.10+**（TickFlow SDK 支持 3.9+，推荐 3.10）
- TickFlow API Key（完整服务，含实时行情）；无 Key 可用免费服务拉历史日 K

## 快速开始（腾讯云，交易日 17:00 后）

```bash
cd ~/Trend_Analysis
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 完整服务（推荐）：注册 https://tickflow.org 获取 API Key
export TICKFLOW_API_KEY=tk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# 指定历史交易日（无 API Key 也可用免费服务）
python scripts/fetch_daily_data.py --date 2024-06-12

# 当日采集（需 API Key + quotes）
python scripts/fetch_daily_data.py

ls data/
```

## 数据源（TickFlow）

| 用途 | TickFlow 能力 |
|------|---------------|
| 申万行业 ↔ 个股 | 标的池 `CN_Equity_SW1_*` / `SW2_*` / `SW3_*`（**当前成份快照**） |
| 成交额 | 实时行情 `quotes.amount` 或历史日 K `klines.amount` |
| 全 A 股票列表 | 标的池 `CN_Equity_A` |

> **关于历史成份**：TickFlow 提供申万行业标的池，但是**当前快照**，不像 BigQuant 有逐日 `cn_stock_industry_component`。历史回填时行业归属用当前标的池归类，严格点-in-time 需另寻数据源。

## 常见问题

**`No matching distribution found for bigquant`**

项目已切换至 TickFlow，请 `git pull` 后重装：`pip install -r requirements.txt`

**无 API Key / UnicodeEncodeError**

历史验证不需要 Key：`python scripts/fetch_daily_data.py --date 2024-06-12`

若设置 Key 后报 `UnicodeEncodeError: 'ascii' codec can't encode`，说明环境变量仍是占位符（如 `你的key`），请到 [tickflow.org](https://tickflow.org) 复制真实 Key：

```bash
export TICKFLOW_API_KEY=tf_xxxxxxxx   # 粘贴控制台里的真实字符串
```
