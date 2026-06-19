# Tushare Pro 接入归档（v4.0 主数据源）

> 官方文档：https://tushare.pro/document/2  
> 产品设计：[TUSHARE_SECTOR_DESIGN.md](./TUSHARE_SECTOR_DESIGN.md)  
> 认证：环境变量 `TUSHARE_TOKEN`（**禁止提交 Git**）

---

## 1. 本项目使用的接口

### 1.1 A 股行情与资金

| 用途 | 接口 | 文档 | 积分 | 更新时间 |
|------|------|------|------|----------|
| 个股日线（成交额） | `daily` | [doc](https://tushare.pro/wctapi/documents/27.md) | 120+ | 15:00–17:00 |
| 个股资金流向（四档买卖） | `moneyflow` | [doc](https://tushare.pro/wctapi/documents/170.md) | 2000 | **19:00 后** |
| 股票列表 | `stock_basic` | [doc](https://tushare.pro/document/2?doc_id=25) | 2000 | — |

**字段映射（→ `stock_daily`）：**

| Tushare | 项目字段 | 换算 |
|---------|----------|------|
| `amount` | `turnover` | × 1000（千元→元） |
| `pct_chg` | `pct_chg` | 直接 |
| `buy_*_amount` 四档之和 | `active_buy` | × 10000（万元→元） |
| `sell_*_amount` 四档之和 | `active_sell` | × 10000 |
| `buy_lg+buy_elg` | `main_buy` | × 10000 |
| `sell_lg+sell_elg` | `main_sell` | × 10000 |

### 1.2 申万行业（`kind=sw_l3`）

| 用途 | 接口 | 文档 | 积分 |
|------|------|------|------|
| 行业树 | `index_classify` | [doc](https://tushare.pro/wctapi/documents/181.md) | 2000 |
| 成份股 | `index_member_all` | [doc](https://tushare.pro/wctapi/documents/335.md) | 2000 |

申万 2021 版：L1×31 · L2×134 · **L3×346**。

### 1.3 中信行业（`kind=ci_l3`）

| 用途 | 接口 | 文档 | 积分 |
|------|------|------|------|
| 成份股 | `ci_index_member` | [doc](https://tushare.pro/wctapi/documents/373.md) | 5000 |
| 指数行情（校验用） | `ci_daily` | [doc](https://tushare.pro/wctapi/documents/308.md) | 5000 |

中信 2020 版：L1×30 · L2×109 · **L3×285**。

### 1.4 东财行业（`kind=dc_ind`）

| 用途 | 接口 | 文档 | 积分 |
|------|------|------|------|
| 板块列表 | `dc_index`（`idx_type=行业板块`） | [doc](https://tushare.pro/wctapi/documents/362.md) | 6000 |
| 成份股 | `dc_member` | [doc](https://tushare.pro/wctapi/documents/363.md) | 6000 |

**不用** `idx_type=概念板块|地域板块`。

### 1.5 同花顺行业（`kind=ths_ind`）

| 用途 | 接口 | 文档 | 积分 |
|------|------|------|------|
| 行业指数列表 | `ths_index`（`type=I`） | [doc](https://tushare.pro/wctapi/documents/259.md) | 6000 |
| 成份股 | `ths_member` | [doc](https://tushare.pro/wctapi/documents/261.md) | 6000 |

**不用** `type=N`（概念）及其他 type。

### 1.6 ETF

| 用途 | 接口 | 文档 | 积分 | 说明 |
|------|------|------|------|------|
| ETF 列表 | `fund_basic`（market=E） | — | 2000 | — |
| 日线成交 | `fund_daily` | [doc](https://tushare.pro/wctapi/documents/127.md) | 5000 | `amount` 千元→元 |
| 份额/规模 | `etf_share_size` | [doc](https://tushare.pro/wctapi/documents/408.md) | 8000 | 份额变化作资金 proxy |

**无** ETF 版 `moneyflow`；ETF 页不提供 A 股同款主买/主卖四档。

---

## 2. 快速开始

```bash
cd ~/Trend_Analysis
source .venv/bin/activate
pip install tushare

# .env
TUSHARE_TOKEN=你的token

python -c "
import tushare as ts, os
pro = ts.pro_api(os.environ['TUSHARE_TOKEN'])
print(pro.daily(trade_date='20250613', fields='ts_code,amount').head())
"
```

---

## 3. MCP（可选）

Tushare 提供 MCP：`https://api.tushare.pro/mcp/?token=…`  
在 Cursor Settings → MCP 配置；Token 与 SDK 共用积分。

---

## 4. 退役接口（必盈）

v4.0 起不再调用：`hszg/*`、`hsrl/*`、`hsstock/history/transaction`、`fd/*`。  
归档见 [BIYING_API.md](./BIYING_API.md)。
