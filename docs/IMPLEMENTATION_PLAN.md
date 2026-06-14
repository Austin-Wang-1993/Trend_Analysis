# 实现方案：A 股行业成交额数据（Phase 1）

> 版本：v0.2（已确认）  
> 前置文档：[REQUIREMENTS.md](./REQUIREMENTS.md)

---

## 1. 方案概述

一个 Python 脚本，调用 **3 类** akshare 接口（共约 88 次请求），输出 4 份 CSV。

```
┌──────────────────────────┐     ┌──────────────────┐     ┌─────────────┐
│ fetch_daily_data.py      │ ──► │  data/*.csv      │ ──► │  人工查看   │
│ 腾讯云 17:00 后执行       │     │  4 表 + README   │     │  验证效果   │
└──────────────────────────┘     └──────────────────┘     └─────────────┘
```

---

## 2. 技术选型

| 项 | 选择 |
|----|------|
| 语言 | Python 3.10+ |
| 依赖 | `akshare`, `pandas` |
| 存储 | CSV（UTF-8） |
| 环境 | 腾讯云国内 CVM |
| 调度 | Phase 1 手动；Phase 2 cron/systemd 每日 17:00 |

---

## 3. 采集流程

### 3.1 顺序

```
Step 1  stock_board_industry_name_em()          → 行业列表
Step 2  对每个行业 stock_board_industry_cons_em(symbol=industry_code)
        → industry_stock_mapping
        → stock_turnover_daily
        → 按行业 groupby SUM → industry_turnover_daily
Step 3  stock_zh_a_spot_em()                    → market_turnover_daily
Step 4  写 data/README.md + 校验报告
```

**不调用** `stock_board_industry_spot_em`。

### 3.2 伪代码

```python
snapshot_time = now_cst()
trade_date = infer_trade_date(snapshot_time)
industries = ak.stock_board_industry_name_em()

mapping, stocks = [], []
for code, name in industries:
    cons = ak.stock_board_industry_cons_em(symbol=code)
    for row in cons:
        mapping.append({...})
        stocks.append({..., turnover: row["成交额"]})

industry_turnover = (
    pd.DataFrame(stocks)
    .groupby(["industry_code", "industry_name"])
    .agg(turnover=("turnover", "sum"), stock_count=("stock_code", "count"))
)

market = ak.stock_zh_a_spot_em()
total = market["成交额"].sum()
```

### 3.3 请求量

| 接口 | 次数 | 间隔 |
|------|------|------|
| `stock_board_industry_name_em` | 1 | - |
| `stock_board_industry_cons_em` | ~86 | 0.5～1s |
| `stock_zh_a_spot_em` | 1 | - |

预计耗时：**2～4 分钟**（较原方案减少 86 次 spot 请求）。

---

## 4. 输出规范

### 4.1 目录

```
data/
├── README.md
├── industry_stock_mapping.csv
├── market_turnover_daily.csv
├── industry_turnover_daily.csv
└── stock_turnover_daily.csv
```

### 4.2 格式

- 编码：UTF-8
- 分隔符：逗号
- 金额：浮点数，单位元

### 4.3 元数据

| 列 | 说明 |
|----|------|
| `trade_date` | `YYYY-MM-DD`，采集日或最近交易日 |
| `snapshot_time` | `YYYY-MM-DDTHH:MM:SS+08:00` |

---

## 5. 数据校验

| 校验项 | 规则 |
|--------|------|
| 映射完整 | 每个行业 ≥ 1 只成份股 |
| 大盘成交额 | `total_turnover > 0` |
| 行业 = 个股之和 | `industry.turnover == SUM(stock.turnover)` 同学业内 |
| 行数一致 | `len(mapping) == len(stock_turnover)` |
| 行业合计 vs 大盘 | 打印比值作参考（**不要求相等**，口径不同） |

---

## 6. 腾讯云部署

```bash
git clone https://github.com/Austin-Wang-1993/Trend_Analysis.git
cd Trend_Analysis
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 交易日 17:00 后执行
python scripts/fetch_daily_data.py
```

### 定时任务（Phase 2 可选）

```cron
0 17 * * 1-5 cd /opt/trend_analysis && .venv/bin/python scripts/fetch_daily_data.py
```

---

## 7. 阶段状态

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 1a | 需求 + 方案 | ✅ 已确认 |
| Phase 1b | 下载脚本 + CSV | 🔄 进行中 |
| Phase 1c | 腾讯云执行验证 | 待 Phase 1b |
| Phase 2 | 定时归档 | 待定 |
| Phase 3 | 占比 / 趋势看板 | 待定 |

---

## 8. 已确认决策

- [x] 当日 = 采集时刻最近交易日快照
- [x] 大盘成交额 = `stock_zh_a_spot_em` 求和
- [x] 行业成交额 = 成份股求和（不用 `stock_board_industry_spot_em`）
- [x] 映射每交易日 17:00 后全量刷新
- [x] CSV 交付，暂不需要 Excel
- [x] 腾讯云国内节点执行
