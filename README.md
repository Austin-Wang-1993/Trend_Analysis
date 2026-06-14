# Trend Analysis — A 股板块资金流量趋势分析

基于 akshare 的 **板块 / 个股 / ETF 资金流量** 采集与分析 MVP。同步层与 analysis 层解耦，便于后续替换付费数据源。

## 架构

```
sync/          # 定时拉取 akshare → 落库（可换数据源）
analysis/      # 读库计算排名、占比、趋势快照
core/          # 配置、模型、数据库
docs/          # 字段定义与接口映射
scripts/       # 验证与部署脚本
```

## 功能范围（Phase 1）

| 维度 | 内容 |
|------|------|
| 大盘 | 流入 / 流出 / 主力净流入、指数涨跌 |
| 板块 | 行业 + 概念排名、个股数量、占大盘比例 |
| 个股 | 全市场个股流量、TOP 排名与占比 |
| ETF | 全市场 ETF 主力净流入与大盘占比 |

**历史数据策略**：akshare 免费接口以「当日 + 短周期回溯」为主；通过 **每日收盘 sync 落库** 自建历史。详见 [docs/FIELD_DEFINITIONS.md](docs/FIELD_DEFINITIONS.md)。

## 快速开始（本地 / 腾讯云）

```bash
git clone https://github.com/Austin-Wang-1993/Trend_Analysis.git
cd Trend_Analysis
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# 单日端到端验证：同步 + 分析 + 报告
python scripts/verify_one_day.py
```

### 分步命令

```bash
# 初始化库
python -m sync.cli all --init-db

# 仅同步
python -m sync.cli all
python -m sync.cli sector
python -m sync.cli etf

# 生成分析快照并查看日报
python -m analysis.cli build
python -m analysis.cli report
```

### 定时同步

```bash
python -m sync.scheduler
# 或使用 scripts/deploy_tencent_cloud.sh 配置 systemd timer
```

## 腾讯云部署

在 **已安装 git 的空服务器** 上：

```bash
export REPO_URL=https://github.com/Austin-Wang-1993/Trend_Analysis.git
export BRANCH=cursor/sector-fund-flow-mvp-df9e   # 合并 main 后改为 main
bash scripts/deploy_tencent_cloud.sh
```

建议：

- 使用 **国内 CVM**（东财接口在海外易限流，同花顺作降级）
- 交易日 **16:30 后** 执行 sync（收盘数据更完整）
- 数据库默认 SQLite；生产可改 `DATABASE_URL` 为 PostgreSQL

## 数据源

| 优先级 | 来源 | 接口示例 |
|--------|------|----------|
| 1 | 东方财富 | `stock_market_fund_flow`, `stock_sector_fund_flow_rank`, `fund_etf_spot_em` |
| 2 | 同花顺 | `stock_fund_flow_industry`, `stock_fund_flow_individual` |

映射说明：[docs/AKSHARE_MAPPING.md](docs/AKSHARE_MAPPING.md)

## Phase 2 规划（趋势看板）

- [ ] 基于 `analysis_snapshot` 按日期序列出图（Streamlit / Grafana）
- [ ] 单板块 / 单股历史回补任务
- [ ] 付费数据源 adapter（实现 `FundFlowSource` 接口即可）
- [ ] 板块内个股明细 sync（`stock_sector_fund_flow_summary`）

## 许可证

MIT
