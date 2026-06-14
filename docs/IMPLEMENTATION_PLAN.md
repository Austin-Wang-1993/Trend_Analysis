# 实现方案：TickFlow + 申万行业成交额

> 版本：v1.1  
> 前置：[REQUIREMENTS.md](./REQUIREMENTS.md)

---

## 1. 架构

```
┌─────────────────────┐     ┌──────────────────┐     ┌─────────────┐
│ scripts/            │     │ data/*.csv       │     │ analysis/   │
│ fetch_daily_data.py │ ──► │ 4 表 + README    │ ──► │ 占比/趋势   │
│ tf_common.py        │     │ cache/sw_mapping │     │ (Phase 2+)  │
└─────────────────────┘     └──────────────────┘     └─────────────┘
         ▲
         │ TICKFLOW_API_KEY（可选，免费档仅日K）
    TickFlow API
```

---

## 2. 依赖

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export TICKFLOW_API_KEY=your-api-key   # 当日 quotes 需要
```

- Python **3.10+**
- 包：`tickflow[all]`、`pandas`

---

## 3. 采集流程

### 单日

```
trade_date
  ├─① universes.batch(CN_Equity_SW*)  → industry_stock_mapping.csv（缓存 sw_mapping.json）
  ├─② quotes 或 klines.batch(CN_Equity_A) → 个股 amount
  └─③ 按一级行业汇总 → market / industry / stock CSV
```

### 历史回填

```
start_date ~ end_date 每个工作日
  └─ klines.batch 拉取 amount，用当前申万标的池归类
```

---

## 4. 脚本用法

```bash
# 历史日（免费服务可用）
python scripts/fetch_daily_data.py --date 2024-06-12

# 当日（需 API Key）
export TICKFLOW_API_KEY=...
python scripts/fetch_daily_data.py

# 刷新申万映射缓存
python scripts/fetch_daily_data.py --refresh-mapping

# 历史成交额回填
python scripts/fetch_historical.py --start-date 2024-01-01 --end-date 2024-01-31
```

---

## 5. 输出字段

与 v1.0 保持一致，见 [REQUIREMENTS.md](./REQUIREMENTS.md)。

---

## 6. 与 BigQuant 方案对比

| | BigQuant | TickFlow |
|--|----------|----------|
| SDK 安装 | 需专用 PyPI + Python 3.11 | `pip install tickflow`，支持 3.10 |
| 历史成份 | 日频 `cn_stock_industry_component` | 仅当前申万标的池快照 |
| 历史成交额 | DAI SQL | 日 K `amount` |
| 当日成交额 | DAI SQL | `quotes` 批量 |

---

## 7. 定时任务（Phase 2）

```cron
0 17 * * 1-5 cd ~/Trend_Analysis && .venv/bin/python scripts/fetch_daily_data.py
```
