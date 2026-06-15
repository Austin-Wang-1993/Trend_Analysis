# 实现方案：必盈 API + 申万行业成交额

> 版本：v2.0  
> 前置：[REQUIREMENTS.md](./REQUIREMENTS.md)  
> 必盈接口归档：[BIYING_API.md](./BIYING_API.md)

---

## 1. 架构

```
┌─────────────────────────┐     ┌──────────────────────┐     ┌─────────────┐
│ scripts/                │     │ data/*.csv           │     │ analysis/   │
│ fetch_by_daily.py       │ ──► │ 5 表 + README        │ ──► │ 占比/趋势   │
│ by_common.py            │     │ cache/*.json         │     │ (Phase 2+)  │
└─────────────────────────┘     └──────────────────────┘     └─────────────┘
         ▲
         │ BIYING_LICENCE
    必盈 API (api.biyingapi.com)
```

---

## 2. 依赖

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# 编辑 BIYING_LICENCE=...
set -a && source .env && set +a
```

- Python **3.10+**
- 包：`pandas`、`requests`

BigQuant 备选见 `requirements-bigquant.txt`（Python 3.11+）。

---

## 3. 采集流程

### 3.1 单日（主流程）

```
① hslt/list              → 全 A 股票列表
② hszg/list              → 筛申万一级 (type2=0, isleaf=1)
③ hszg/gg × N            → sector_stock_mapping.csv
④ hsrl/ssjy_more 分批    → 个股 cje 成交额
⑤ merge + groupby        → sector_turnover_daily.csv
⑥ 全 A − 映射            → unmapped_stocks.csv
```

### 3.2 缓存策略

| 缓存文件 | 内容 | 刷新 |
|----------|------|------|
| `cache/sector_tree.json` | hszg/list | `--refresh-mapping` 或 `--fresh` |
| `cache/sector_mapping_l1.json` | hszg/gg 汇总 | 同上 |

`--turnover-only`：跳过 ②③，仅用 cache 映射 + 重拉 ④。

---

## 4. 脚本用法

```bash
# 日常更新
python3 scripts/fetch_by_daily.py --no-all-turnover

# 全量重拉
python3 scripts/fetch_by_daily.py --fresh --no-all-turnover

# 清 CSV 保留 cache
python3 scripts/fetch_by_daily.py --fresh --keep-cache --no-all-turnover

# 仅成交额
python3 scripts/fetch_by_daily.py --no-all-turnover --turnover-only

# 申万二级
python3 scripts/fetch_by_daily.py --level l2 --no-all-turnover

# 查看未归类
python3 scripts/list_unmapped_stocks.py
```

---

## 5. 模块说明

| 模块 | 职责 |
|------|------|
| `by_common.py` | 必盈 HTTP 客户端：list / hszg / ssjy_more |
| `fetch_by_daily.py` | CLI 入口、CSV 写出、校验报告 |
| `list_unmapped_stocks.py` | 未归类股票摘要 |

`by_common.py` 另含 `hslt/primarylist` + `hslt/sectors` 备用函数（指数池路由，非主路径）。

---

## 6. 输出字段要点

### stock_turnover_latest.csv

| 字段 | 来源 |
|------|------|
| `stock_code` | hslt/list |
| `turnover` | ssjy_more `cje` |
| `sector_code`, `sector_name` | 映射 merge |
| `trade_date` | ssjy_more `t` |

### sector_turnover_daily.csv

| 字段 | 说明 |
|------|------|
| `sector_name` | 申万一级 |
| `turnover` | 行业成份成交额之和 |
| `stock_count` | 有归属且有权重的股票数 |

---

## 7. 方案对比

| | 必盈（当前） | BigQuant | TickFlow |
|--|-------------|----------|----------|
| Python | 3.10+ | 3.11+ | 3.10+ |
| 申万映射覆盖 | ~99.8%（实测） | 高（逐日成份） | ~85% |
| 成交额 | ssjy_more `cje` | bar1d `amount` | quotes/kline |
| 历史成份 | 快照 | 日频 | 快照 |
| 证书 | BIYING_LICENCE | AK/SK + SDK 权限 | API Key |

---

## 8. 定时任务（Phase 2 规划）

```cron
# 交易日 16:30
30 16 * * 1-5 cd ~/Trend_Analysis && .venv/bin/python scripts/fetch_by_daily.py --no-all-turnover >> logs/fetch.log 2>&1
```

---

## 9. 归档脚本

| 脚本 | 说明 |
|------|------|
| `fetch_daily_data.py` | TickFlow 方案 |
| `fetch_historical.py` | TickFlow 历史回填 |
| `fetch_sector_data.py` | StockAPI 东财板块 |
| `fetch_bq_daily.py` | BigQuant DAI |

保留供参考，**不再作为主路径维护**。
