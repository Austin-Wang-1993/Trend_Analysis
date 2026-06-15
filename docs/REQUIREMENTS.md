# 需求文档：A 股申万行业成交额分析（Phase 1）

> 版本：v2.0（必盈 API + 申万 hszg）  
> 状态：**Phase 1 已跑通**  
> 必盈接入详情：[BIYING_API.md](./BIYING_API.md)

---

## 1. 项目目标

基于 **申万行业分类**，构建 A 股 **成交额** 三层分析能力：

1. 行业 ↔ 个股映射（尽量全量、可查漏）
2. 大盘 / 行业 / 个股成交额
3. 为后续历史序列与趋势看板积累数据（Phase 2/3）

---

## 2. 数据源（当前主方案）

| 角色 | 平台 | 说明 |
|------|------|------|
| 数据提供 | [必盈 API](https://www.biyingapi.com) | REST，证书 `BIYING_LICENCE` |
| 文档 | [doc_hs](https://www.biyingapi.com/doc_hs) | 沪深 A 股接口 |
| 部署 | 腾讯云 Ubuntu + Python 3.10 | `pip install -r requirements.txt` |
| 采集时间 | 每交易日 **16:20 后** | 成交额当日更新 |

---

## 3. 数据能力映射

### 3.1 全 A 股列表

| 接口 | 字段 |
|------|------|
| `hslt/list/{licence}` | `dm` 代码, `mc` 名称, `jys` 交易所 |

用途：全量对照、未归类检查。

### 3.2 申万行业分类与映射

| 步骤 | 接口 | 说明 |
|------|------|------|
| 行业树 | `hszg/list/{licence}` | 筛 `type2=0`（申万一级）、`isleaf=1` |
| 成份股 | `hszg/gg/{code}/{licence}` | 逐板块拉取映射 |

- 默认 **申万一级**（31 个行业）
- 支持 `--level l2` 申万二级
- 映射更新：每周六（文档说明）

**实测覆盖（2026-06-15）**：全 A 5208 只，未归类 **10** 只。

### 3.3 个股成交额

| 场景 | 接口 | 字段 |
|------|------|------|
| 常规定额证书 | `hsrl/ssjy_more/{licence}?stock_codes=` | `cje` = 成交额 |
| 包年/白金 | `all.biyingapi.com/hsrl/ssjy/all/{licence}` | 一次拉全市场 |

### 3.4 板块汇总

```text
GROUP BY sector_code, sector_name
SUM(stock.turnover)   # turnover 来自 cje
```

---

## 4. 衍生逻辑

### 4.1 大盘成交额

```text
SUM(stock.turnover)   # 全 A 有行情股票
```

### 4.2 行业成交额

```text
GROUP BY 申万一级 sector
SUM(stock.turnover)
```

### 4.3 占比（Phase 3，未实现）

| 指标 | 公式 |
|------|------|
| 行业占大盘 | `sector.turnover / market.total` |
| 个股占行业 | `stock.turnover / sector.turnover` |
| 个股占大盘 | `stock.turnover / market.total` |

---

## 5. 交付物（CSV）

| 文件 | 内容 |
|------|------|
| `sectors.csv` | 行业/概念分类树 |
| `sector_stock_mapping.csv` | 板块 ↔ 个股映射 |
| `stock_turnover_latest.csv` | 个股成交额 + 主行业 |
| `sector_turnover_daily.csv` | 一级行业成交额汇总 |
| `unmapped_stocks.csv` | 全 A 中未出现在映射里的股票 |
| `data/README.md` | 采集元数据 |
| `data/cache/sector_tree.json` | 行业树缓存 |
| `data/cache/sector_mapping_l1.json` | 映射缓存 |

---

## 6. 已确认决策

| 项 | 决策 |
|----|------|
| **主数据源** | 必盈 API |
| 行业体系 | 申万（`hszg/list` + `hszg/gg`） |
| 板块层级 | 一级行业汇总（默认） |
| 主指标 | 成交额 `cje` |
| 历史成份 | 当前映射快照（非逐日历史成份） |
| 交付格式 | CSV |
| 采集时间 | 每交易日 16:20 后 |
| Python | 3.10+ |

---

## 7. 前置条件

```bash
pip install -r requirements.txt
export BIYING_LICENCE=你的licence   # 见 .env.example
python3 scripts/fetch_by_daily.py --no-all-turnover
```

---

## 8. 备选 / 归档方案

| 方案 | 脚本 | 适用场景 |
|------|------|----------|
| BigQuant DAI | `fetch_bq_daily.py` | 需逐日历史成份 + Python 3.11 |
| TickFlow 申万池 | `fetch_daily_data.py` | 旧方案，~85% 覆盖 |
| StockAPI 东财 | `fetch_sector_data.py` | 旧方案，非申万 |

---

## 9. 阶段规划

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 1 | 最近交易日拉取 + CSV 验证 | ✅ 完成 |
| Phase 2 | 每日 cron 定时采集、历史落库 | 待做 |
| Phase 3 | 占比分析 + 趋势看板 | 待做 |
