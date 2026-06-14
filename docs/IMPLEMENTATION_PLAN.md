# 实现方案：BigQuant + 申万行业成交额

> 版本：v1.0  
> 前置：[REQUIREMENTS.md](./REQUIREMENTS.md)

---

## 1. 架构

```
┌─────────────────────┐     ┌──────────────────┐     ┌─────────────┐
│ sync/               │     │ data/*.csv       │     │ analysis/   │
│ bigquant_fetch.py   │ ──► │ 4 表 + README    │ ──► │ 占比/趋势   │
│ (DAI SQL)           │     │                  │     │ (Phase 2+)  │
└─────────────────────┘     └──────────────────┘     └─────────────┘
         ▲
         │ AK/SK
   BigQuant 云端
```

- **sync**：只负责 BigQuant 查询与落 CSV
- **analysis**：读本地数据，不算 API（后续实现）

---

## 2. 依赖

```bash
pip install bigquant pandas -i https://pypi.bigquant.com/simple/
bq auth --apikey <你的AK.SK>
```

> 注意：须从 BigQuant 官方 PyPI 源安装，公共 PyPI 上的 `bigquant` 包并非本 SDK。

配置文件默认：`~/.bigquant/config.json`

---

## 3. 采集流程

### 单日采集

```
输入 trade_date（默认最近交易日）
  │
  ├─① cn_stock_industry_component  → industry_stock_mapping.csv（当日历史成份）
  │
  ├─② cn_stock_bar1d               → 大盘 SUM(amount)
  │       JOIN 当日 component      → industry_turnover_daily.csv
  │                               → stock_turnover_daily.csv
  │
  └─③ 写 data/README.md + 校验报告
```

### 历史回填

```
输入 start_date ~ end_date（默认 2023-07-05 ~ 最近交易日）
  │
  ├─ 按月分块查询 cn_stock_industry_component → industry_stock_mapping_history.csv
  ├─ 按月分块 JOIN 当日成份汇总成交额         → market/industry_turnover_history.csv
  └─ 可选 --include-stocks                    → stock_turnover_history.csv
```

**关键**：历史成交额必须用 `b.date = c.date` 点-in-time JOIN，不能用最新成份回算。

单次运行：**3 条 SQL**（无东财式 86 次轮询）。

---

## 4. 脚本用法

```bash
cd ~/Trend_Analysis
source .venv/bin/activate
pip install -r requirements.txt
bq auth --apikey <AK.SK>

# 指定日期
python scripts/fetch_daily_data.py --date 2024-06-12

# 不指定则取最近一个工作日
python scripts/fetch_daily_data.py
```

### 历史成份回填

```bash
# 完整历史申万成份 + 大盘/行业成交额（默认 2023-07-05 ~ 最近交易日）
python scripts/fetch_historical.py

# 指定区间，仅拉成份映射
python scripts/fetch_historical.py --start-date 2024-01-01 --end-date 2024-12-31 --mode mapping

# 含个股级历史成交额（数据量大）
python scripts/fetch_historical.py --start-date 2024-01-01 --end-date 2024-03-31 --include-stocks
```

输出目录：`data/history/`。按月分块查询，避免单次 SQL 过大。

---

## 5. 输出字段

### industry_stock_mapping.csv

`trade_date, stock_code, stock_name, industry_l1_code, industry_l1_name, industry_l2_code, industry_l2_name, industry_l3_code, industry_l3_name, industry_name`

### market_turnover_daily.csv

`trade_date, snapshot_time, total_turnover, stock_count`

### industry_turnover_daily.csv

`trade_date, snapshot_time, industry_l1_code, industry_l1_name, turnover, volume, stock_count`

### stock_turnover_daily.csv

`trade_date, snapshot_time, stock_code, stock_name, industry_l1_code, industry_l1_name, turnover, volume, turnover_rate, pct_chg`

---

## 6. 校验

| 项 | 规则 |
|----|------|
| 映射行数 = 个股行数 | JOIN 后应一致 |
| 行业成交额之和 vs 大盘 | 应接近（JOIN 后股票子集，可能略小于全市场） |
| 每行业 stock_count ≥ 1 | 无空行业 |

---

## 7. 定时任务（Phase 2）

```cron
0 17 * * 1-5 cd /opt/Trend_Analysis && .venv/bin/python scripts/fetch_daily_data.py
```

---

## 8. 与东财方案对比

| | 东财 akshare | BigQuant 申万 |
|--|--------------|---------------|
| 稳定性 | 差 | 好 |
| 历史 | 需自积累 | SQL 指定日期 |
| 行业 | 东财 BK 板块 | 申万 2021 |
| 请求次数/日 | ~88+ | 3 条 SQL |

东财相关脚本（`em_client.py`）已废弃，可删除。
