# Trend_Analysis

A 股**申万二级行业**成交额 + 买卖分析 + Web 看板（近 5 交易日）。

## 文档

| 文档 | 说明 |
|------|------|
| [文档索引](docs/README.md) | 全部文档入口 |
| [需求文档](docs/REQUIREMENTS.md) | **v3.4** 目标、看板、管理页 |
| [实现方案](docs/IMPLEMENTATION_PLAN.md) | 架构、API、部署 |
| [**必盈 API 归档**](docs/BIYING_API.md) | 接口、L2 映射、命令 |

**必盈官方文档**：https://www.biyingapi.com/doc_hs

## 环境要求

- **Python 3.10+**
- **必盈 API 证书**：https://www.biyingapi.com/doc_hs

## 快速开始（采集）

```bash
cd ~/Trend_Analysis
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
set -a && source .env && set +a

# 日常更新（默认申万二级，约 20–25 分钟含买卖+ETF）
python3 scripts/fetch_by_daily.py --no-all-turnover
```

## Web 看板

```bash
# 若 DB 为旧 L1 数据，先迁移（无需重打 API）
python3 scripts/build_sector_mapping.py --level l2   # 首次约 2–3 分钟
python3 scripts/migrate_sectors_to_l2.py           # 无 L2 缓存时会自动尝试 build

python3 scripts/serve_dashboard.py
# http://127.0.0.1:8080
```

生产部署：`bash deploy/install.sh`

| 页面 | 路径 |
|------|------|
| 全 A 概览 | `/` |
| 申万二级表格/图表 | `/sectors-table.html` `/sectors-charts.html` |
| ETF | `/etf-table.html` `/etf-charts.html` |
| 管理 | `/admin.html` |

## 板块层级

| 层级 | 板块数 | 默认 |
|------|--------|------|
| 申万一级 | 31 | 否 |
| **申万二级** | **131** | **是** |
| 申万三级 | — | 必盈无 |

配置：`scripts/sector_config.py` → `DEFAULT_SECTOR_LEVEL = "l2"`

## 输出文件

| 文件 | 说明 |
|------|------|
| `data/history.db` | SQLite 历史库（看板数据源） |
| `stock_turnover_latest.csv` | 个股成交 + 买卖 + **L2** 归属 |
| `sector_turnover_daily.csv` | **二级**行业成交额汇总 |
| `etf_turnover_latest.csv` | ETF 成交额 |
| `data/cache/sector_mapping_l2.json` | L2 映射缓存 |

## 常见问题

**已有 L1 数据，如何切 L2？**

```bash
# 确保有 L2 映射缓存（首次约 2–3 分钟，仅 hszg/gg，不拉成交）
python3 scripts/build_sector_mapping.py --level l2
python3 scripts/migrate_sectors_to_l2.py
```

**手动补数选了周末？** 管理页会拒绝非交易日；运行中任务可点 **取消**。

## 其他方案（归档）

- BigQuant：`scripts/fetch_bq_daily.py`（含 L1/L2/L3）
- TickFlow：`scripts/fetch_daily_data.py`
