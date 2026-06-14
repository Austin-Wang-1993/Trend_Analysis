# 实现方案：A 股行业成交额数据（Phase 1）

> 版本：v0.1（待确认）  
> 前置文档：[REQUIREMENTS.md](./REQUIREMENTS.md)

---

## 1. 方案概述

Phase 1 采用**最简实现**：一个 Python 脚本，调用 akshare 四个接口，输出 4 份 CSV。  
不做数据库、不做定时任务、不做 Web，确保你先**看到真实数据**再迭代。

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────┐
│  fetch_data.py  │ ──► │  data/*.csv      │ ──► │  人工查看   │
│  (一次性采集)    │     │  4 张表 + README │     │  验证效果   │
└─────────────────┘     └──────────────────┘     └─────────────┘
```

确认需求后再拆分为 `sync/`（采集）与 `analysis/`（汇总占比），与后续资金流量模块解耦。

---

## 2. 技术选型

| 项 | 选择 | 理由 |
|----|------|------|
| 语言 | Python 3.10+ | akshare 生态 |
| 数据源 | akshare（东财） | 需求指定 |
| 存储 | CSV | 直观、易检查、零依赖 |
| 运行环境 | 腾讯云国内 CVM | 东财接口需国内 IP |
| 依赖 | `akshare`, `pandas` | 最小集 |

---

## 3. 采集流程

### 3.1 总体顺序

```
Step 1  拉取行业列表          stock_board_industry_name_em()
Step 2  遍历行业：
        2a  拉取成份股         stock_board_industry_cons_em(symbol=industry_code)
            → 写入 mapping + stock_turnover
        2b  拉取行业成交额     stock_board_industry_spot_em(symbol=industry_name)
            → 写入 industry_turnover
Step 3  拉取全 A 行情          stock_zh_a_spot_em()
        → 汇总成交额写入 market_turnover
Step 4  写 metadata           trade_date, snapshot_time
```

### 3.2 伪代码

```python
snapshot_time = now()
industries = ak.stock_board_industry_name_em()

mapping_rows, stock_rows, industry_rows = [], [], []

for _, ind in industries.iterrows():
    code, name = ind["板块代码"], ind["板块名称"]

    cons = ak.stock_board_industry_cons_em(symbol=code)
    for _, row in cons.iterrows():
        mapping_rows.append({industry_code: code, industry_name: name,
                             stock_code: row["代码"], stock_name: row["名称"]})
        stock_rows.append({..., turnover: row["成交额"]})

  spot = ak.stock_board_industry_spot_em(symbol=name)
    turnover = spot.loc[spot["item"] == "成交额", "value"].iloc[0]
    industry_rows.append({industry_code: code, industry_name: name, turnover})

market = ak.stock_zh_a_spot_em()
total = market["成交额"].sum()

save_csv(...)
```

### 3.3 请求节奏

| 接口 | 调用次数 | 建议间隔 |
|------|----------|----------|
| `stock_board_industry_name_em` | 1 | - |
| `stock_board_industry_cons_em` | ~86 | 0.5～1 秒/次 |
| `stock_board_industry_spot_em` | ~86 | 0.5～1 秒/次 |
| `stock_zh_a_spot_em` | 1 | - |

预计总耗时：**3～5 分钟**（含网络与限流等待）。

### 3.4 重试策略

- 单接口失败：最多重试 3 次，间隔 3 秒；
- 单个行业失败：记录日志并跳过，不阻断全行业；
- 脚本结束输出成功/失败行业清单。

---

## 4. 输出文件规范

### 4.1 目录结构（确认后生成）

```
data/
├── README.md                      # 数据说明、采集时间
├── industry_stock_mapping.csv
├── market_turnover_daily.csv
├── industry_turnover_daily.csv
└── stock_turnover_daily.csv
```

### 4.2 文件格式

- 编码：UTF-8 with BOM（Excel 友好）或 UTF-8
- 分隔符：逗号
- 金额：保留 2 位小数或科学计数法统一为浮点元

### 4.3 公共元数据列

每张交易表均包含：

| 列 | 示例 |
|----|------|
| `trade_date` | `2026-06-12` |
| `snapshot_time` | `2026-06-12T16:35:00+08:00` |

`trade_date` 获取策略（按优先级）：

1. `stock_zh_a_spot_em` 若后续版本有日期字段则直接用；
2. 否则取 `snapshot_time` 所在日期，若早于 15:00 则回退到上一交易日（简易日历）；
3. Phase 1 可简化为：**用户运行脚本当日日期**，并在 README 注明。

---

## 5. 数据校验（自动）

脚本结束时打印校验报告：

| 校验项 | 规则 | 预期 |
|--------|------|------|
| 映射完整性 | 每个行业 ≥ 1 只成份股 | 86 行业均有数据 |
| 大盘成交额 | `total_turnover > 0` | 通过 |
| 行业求和 | `sum(industry_turnover)` vs 成份股按行业求和 | 口径不同，仅作参考 |
| 交叉校验 | `sum(stock_turnover)` 按行业聚合 vs `industry_spot_em` | 记录偏差 % |
| 个股数 | mapping 行数 vs stock_turnover 行数 | 应相等 |

---

## 6. 部署与执行（腾讯云）

### 6.1 环境准备

```bash
git clone https://github.com/Austin-Wang-1993/Trend_Analysis.git
cd Trend_Analysis
python3 -m venv .venv
source .venv/bin/activate
pip install akshare pandas
```

### 6.2 执行（确认后提供脚本）

```bash
python scripts/fetch_daily_data.py
ls -la data/
```

### 6.3 建议运行时间

- **交易日 15:30 之后**（收盘数据稳定）
- 避免开盘前运行（会拿到上一交易日盘中不完整数据）

---

## 7. 接口可达性验证

| 接口 | 海外 CI 实测 | 国内服务器预期 |
|------|--------------|----------------|
| `stock_board_industry_name_em` | ❌ 连接失败 | ✅ |
| `stock_board_industry_cons_em` | ❌ 连接失败 | ✅ |
| `stock_board_industry_spot_em` | ❌ 连接失败 | ✅ |
| `stock_zh_a_spot_em` | ❌ 连接失败 | ✅ |

> 验证依据：akshare 文档字段已在需求文档中对齐；海外失败为东财 IP 限制，**不代表接口不可用**。  
> **最终验证必须在腾讯云国内节点执行。**

---

## 8. 阶段规划

| 阶段 | 内容 | 前置条件 |
|------|------|----------|
| **Phase 1a**（当前） | 需求 + 方案文档 | 你确认本文档 ✅ |
| **Phase 1b** | 一次性下载脚本 + CSV 交付 | Phase 1a 确认 |
| **Phase 1c** | 腾讯云拉取，你查看数据效果 | Phase 1b |
| **Phase 2** | 每日定时 sync + SQLite/CSV 归档 | 数据效果满意 |
| **Phase 3** | 占比分析 + 趋势看板 | 积累若干交易日 |
| **Phase 4** | 资金流量、付费历史数据 | 独立需求 |

---

## 9. 与旧方案的区别

此前 MVP 围绕**资金流量**（主力净流入），使用 `stock_market_fund_flow` 等接口，与当前需求**不同**。

当前需求聚焦：

- **成交额**（非资金流）
- **行业板块**（东财 `stock_board_industry_*` 体系）
- **最小交付**（CSV 可查看）

旧代码已全部移除，避免混淆。

---

## 10. 请你确认后我们执行的动作

- [ ] 确认需求文档字段与接口映射无误
- [ ] 确认「当日 = 采集日快照」可接受
- [ ] 确认 CSV 交付格式
- [ ] 确认在腾讯云国内节点执行

**你回复「确认」或逐条修改意见后**，我再：

1. 编写 `scripts/fetch_daily_data.py`；
2. 在可访问东财的环境执行（或你在腾讯云执行）；
3. 提交 `data/*.csv` 供你查看（`data/` 可 gitignore 大文件，通过 Release 或手动下载提供）。
