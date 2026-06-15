# 必盈 API 接入归档

> 版本：v1.1  
> 更新：2026-06-15  
> 主脚本：`scripts/fetch_by_daily.py`  
> 共享模块：`scripts/by_common.py`

---

## 1. 官方文档

| 资源 | 地址 |
|------|------|
| 官网 | https://www.biyingapi.com |
| **沪深 A 股 API 文档（主文档）** | https://www.biyingapi.com/doc_hs |
| 文档中心 | https://www.biyingapi.com/doc-center |
| 常见问题 | https://www.biyingapi.com/ask |
| 注册 / 获取证书 | https://www.biyingapi.com （个人中心） |

---

## 2. 本项目使用的接口

### 2.1 总览

| 步骤 | 用途 | 接口 | 代码函数 |
|------|------|------|----------|
| ① | 全 A 股列表 | `GET /hslt/list/{licence}` | `fetch_stock_list()` |
| ② | 行业/概念树 | `GET /hszg/list/{licence}` | `fetch_sector_tree()` |
| ③ | 板块成份股 | `GET /hszg/gg/{code}/{licence}` | `fetch_sector_constituents()` |
| ④ | 个股成交额（常规） | `GET /hsrl/ssjy_more/{licence}?stock_codes=` | `fetch_turnover_batch()` |
| ④' | 全市场成交额（包年/白金） | `GET all.biyingapi.com/hsrl/ssjy/all/{licence}` | `fetch_turnover_all()` |
| ⑤ | 个股买卖/资金流（日级） | `GET /hsstock/history/transaction/{code}/{licence}?lt=` | `fetch_fund_flow_batch()` |
| ⑥ | ETF 列表 | `GET /fd/list/etf/{licence}` | `fetch_etf_list()` |
| ⑥' | ETF 成交额 | `GET /fd/real/time/{code}/{licence}` | `fetch_etf_turnover_batch()` |

**域名**

- 常规：`https://api.biyingapi.com`
- 全市场成交：`https://all.biyingapi.com`

**认证**：路径末尾拼接 `licence`，环境变量 `BIYING_LICENCE`。

### 2.2 接口详情

#### 股票列表

```
GET https://api.biyingapi.com/hslt/list/{licence}
```

| 字段 | 说明 |
|------|------|
| `dm` | 股票代码（如 `000001.SZ`） |
| `mc` | 股票名称 |
| `jys` | 交易所（`SH` / `SZ`） |

#### 指数、行业、概念树

```
GET https://api.biyingapi.com/hszg/list/{licence}
```

文档章节：[doc_hs — 指数、行业、概念树](https://www.biyingapi.com/doc_hs)

| 字段 | 说明 |
|------|------|
| `code` | 板块代码（如 `sw_mt`） |
| `name` | 板块名称 |
| `type2` | `0`=申万一级（31），`1`=**申万二级（131，默认）** |
| `isleaf` | `1`=叶子节点，可作为 `hszg/gg` 参数 |
| `level`, `pcode`, `pname` | 层级与父节点 |

**更新频率**：每周六 03:05

#### 板块成份股

```
GET https://api.biyingapi.com/hszg/gg/{板块code}/{licence}
```

文档章节：[doc_hs — 根据指数、行业、概念找相关股票](https://www.biyingapi.com/doc_hs)

| 字段 | 说明 |
|------|------|
| `dm` | 股票代码 |
| `mc` | 股票名称 |
| `jys` | 交易所 |

**更新频率**：每周六 11:00

#### 股票反查行业（备用，脚本未默认使用）

```
GET https://api.biyingapi.com/hszg/zg/{股票代码}/{licence}
```

示例：`/hszg/zg/000001/{licence}` → 返回该股票所属行业/概念列表。

#### 多股实时成交（成交额）

```
GET https://api.biyingapi.com/hsrl/ssjy_more/{licence}?stock_codes=000001,600000
```

文档章节：[doc_hs — 实时交易数据（多股）](https://www.biyingapi.com/doc_hs)

| 字段 | 说明 |
|------|------|
| `cje` | **成交额（元）** ← 本项目使用 |
| `v` | 成交量 |
| `p` | 最新价 |
| `t` | 更新时间 → 截取为 `trade_date` |
| `dm` | 股票代码 |

限制：每批最多 **20** 只；全 A 约 261 批。

#### 全市场实时成交（包年/白金）

```
GET https://all.biyingapi.com/hsrl/ssjy/all/{licence}
```

非包年证书会报错，需加 `--no-all-turnover` 改用 `ssjy_more`。

#### 个股资金流向（日级主买/主卖）

```
GET https://api.biyingapi.com/hsstock/history/transaction/{code}/{licence}?lt=1
```

文档章节：[doc_hs — 资金流向数据](https://www.biyingapi.com/doc_hs)

| 汇总字段 | 来源 |
|----------|------|
| `active_buy` | `zmbtdcje + zmbddcje + zmbzdcje + zmbxdcje`（主买） |
| `active_sell` | `zmstdcje + zmsddcje + zmszdcje + zmsxdcje`（主卖） |
| `net_active` | 主买 − 主卖 |
| `passive_buy` / `passive_sell` | `bdmb*` / `bdms*` |
| `large_buy` / `large_sell` | 特大单 + 大单 |

**更新频率**：每日 21:30。**无批量接口**，全 A 约 5208 次/日（体验版约 17 分钟）。

**限制**：仅适用于 A 股个股；ETF 调用返回空数组。

#### ETF 列表与成交额

```
GET https://api.biyingapi.com/fd/list/etf/{licence}
GET https://api.biyingapi.com/fd/real/time/{code}/{licence}
```

| 字段 | 说明 |
|------|------|
| `cje` | ETF 成交额 |
| `v` | 成交量 |

**限制**：必盈暂无 ETF 资金流向/买卖拆分接口；`hsstock/history/transaction` 对 ETF 代码返回 `[]`。

---

## 3. 采集流程

```
hslt/list          → 全 A 5208 只（对照 / 未归类检查）
hszg/list          → 筛 type2=1 & isleaf=1 → **131 个申万二级**（看板默认）
hszg/gg × 131      → sector_stock_mapping.csv
hsrl/ssjy_more     → stock_turnover_latest.csv（cje）
history/transaction → 主买/主卖 merge 进 stock_turnover_latest.csv
本地聚合            → sector_turnover_daily.csv + sector_fund_flow_daily.csv
全 A 汇总           → market_summary_daily.csv
fd/list/etf        → etf_turnover_latest.csv（仅成交额）
全 A − 映射         → unmapped_stocks.csv
```

---

## 4. 输出文件

| 文件 | 来源 |
|------|------|
| `data/sectors.csv` | `hszg/list` 全树或目标层级 |
| `data/sector_stock_mapping.csv` | `hszg/gg` 汇总 |
| `data/stock_turnover_latest.csv` | `ssjy_more` + `transaction` + 映射 merge |
| `data/sector_turnover_daily.csv` | 本地按**申万二级** SUM(cje) |
| `data/sector_fund_flow_daily.csv` | 本地按**申万二级** SUM(主买/主卖) |
| `data/market_summary_daily.csv` | 全 A 成交 + 买卖汇总（单行） |
| `data/etf_turnover_latest.csv` | ETF 成交额（无买卖拆分） |
| `data/unmapped_stocks.csv` | 全 A − 映射覆盖 |
| `data/README.md` | 本次采集元数据 |
| `data/cache/sector_tree.json` | 行业树缓存 |
| `data/cache/sector_mapping_l1.json` | 一级映射缓存（可选） |
| `data/cache/sector_mapping_l2.json` | **二级映射缓存（默认）** |

---

## 5. 运行命令

```bash
cd ~/Trend_Analysis
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # 填入 BIYING_LICENCE
set -a && source .env && set +a

# 日常更新（默认申万二级）
python3 scripts/fetch_by_daily.py --no-all-turnover

# 若 history.db 为旧 L1 数据，迁移为 L2（无需重打 API）
python3 scripts/build_sector_mapping.py --level l2
python3 scripts/migrate_sectors_to_l2.py

# 申万一级（仅当需要 L1 时）
python3 scripts/fetch_by_daily.py --level l1 --no-all-turnover

# 申万二级（显式，与默认相同）
python3 scripts/fetch_by_daily.py --level l2 --no-all-turnover

# 清空 CSV + cache 后全量重拉
python3 scripts/fetch_by_daily.py --fresh --no-all-turnover

# 只清 CSV、保留 cache
python3 scripts/fetch_by_daily.py --fresh --keep-cache --no-all-turnover

# 仅更新成交额（需已有 cache 映射，跳过资金流与 ETF）
python3 scripts/fetch_by_daily.py --no-all-turnover --turnover-only

# 跳过资金流（约 5200 次请求 / ~17 分钟）
python3 scripts/fetch_by_daily.py --no-all-turnover --no-fund-flow

# 跳过 ETF（约 1500 次请求）
python3 scripts/fetch_by_daily.py --no-all-turnover --no-etf

# 申万二级映射（默认）
python3 scripts/fetch_by_daily.py --level l2 --no-all-turnover
```

---

## 6. 实测记录

### 2026-06-15 全量采集

| 指标 | 数值 |
|------|------|
| trade_date | 2026-06-15 |
| 全 A 股票 | 5208 |
| 申万一级行业 | 31 |
| **申万二级行业** | **131（看板默认）** |
| 映射覆盖股票 | 5510 / 5208（99.81%） |
| 未归类（L1/L2 相同） | 10（多为新股，待周六 hszg 更新） |
| 映射记录 | 5510（含跨板块重复） |
| 未归类 | **10** |
| 大盘成交额 | 2.03 万亿元 |
| 行业合计 / 大盘 | **99.84%** |

### 接口可用性历史

| 日期 | hszg/list | 说明 |
|------|-----------|------|
| 2026-06-14 | ❌ 404 | 服务端故障或权限临时不可用 |
| 2026-06-15 | ✅ 200 | 恢复，1464 条行业树 |

---

## 7. 备用接口（未作为主路径）

### hslt 券商数据路由

适用于指数成份池场景，**不能替代全 A 申万映射**：

| 接口 | 说明 |
|------|------|
| `hslt/primarylist/{licence}` | 一级市场板块名称 |
| `hslt/sectors/{板块名称}/{licence}` | 板块成份 |

`1000SW1*` 前缀仅覆盖中证 1000 成份（约 999 只），代码保留于 `by_common.py` 但未启用。

### hszg 故障回退

若 `hszg/*` 再次 404，可临时考虑：

- 联系必盈客服确认证书权限
- 使用 `--turnover-only` 保留已有 cache 仅更新成交额
- 备选：AKShare 申万映射 + 必盈成交额（未集成，需另行开发）

---

## 8. 交易日历（pandas_market_calendars 为主）

### 8.1 结论

| 方案 | 说明 |
|------|------|
| **主方案（推荐）** | `pandas_market_calendars` 的 **`SSE` / `XSHG`** 日历 |
| 必盈独立 list API | ❌ 不存在（`hslt/jyrl` 等实测 404） |
| **必盈日 K（备用）** | `hsstock/history/{code}.SZ/d/n/{licence}` 提取 `t` 作校验 |

**实测（2026-06-15）**：PMC 与必盈 `000001.SZ` 日 K 在 2025-06、2026-06、春节窗口 **100% 一致**。

### 8.2 项目模块

```bash
# 最近 5 个交易日
python3 scripts/trading_calendar.py recent --days 5

# 是否交易日
python3 scripts/trading_calendar.py is-trading 2026-06-15

# 对比 PMC vs 必盈
python3 scripts/trading_calendar.py verify --start 2026-06-01 --end 2026-06-15

# 写入 SQLite 缓存（data/history.db）
python3 scripts/trading_calendar.py sync-db data/history.db --start 2026-01-01 --end 2026-12-31
```

代码：`scripts/trading_calendar.py`

| 函数 | 用途 |
|------|------|
| `is_trading_day(date)` | 调度器 `trading_day` 模式 |
| `get_recent_trading_days(n)` | 看板「近 N 交易日」 |
| `should_run_scheduled_task(mode)` | `trading_day` / `calendar_day` |
| `compare_with_biying(...)` | 校验 |
| `sync_pmc_to_sqlite(...)` | 可选本地缓存 |

### 8.3 必盈日 K（校验 / 兜底）

```
GET https://api.biyingapi.com/hsstock/history/000001.SZ/d/n/{licence}?st=YYYYMMDD&et=YYYYMMDD
```

文档章节：[doc_hs — 历史分时交易（日线 d）](https://www.biyingapi.com/doc_hs)

仅在 PMC 不可用或管理页「校验交易日历」时使用，**日常不依赖 API**。

### 8.4 依赖

```text
pandas_market_calendars>=5.4.0
```

---

## 9. 套餐与限制

| 套餐 | ssjy/all 全市场 | ssjy_more 批量 | 备注 |
|------|-----------------|----------------|------|
| 免费版 | ❌ | 200 次/日 | 不够跑全 A，需升级或分批跨日 |
| 包年版 | ✅ | 3000 次/分钟 | 推荐生产使用 |

---

## 10. 相关脚本

| 脚本 | 说明 |
|------|------|
| `scripts/fetch_by_daily.py` | **主入口** |
| `scripts/by_common.py` | 必盈 API 客户端 |
| `scripts/trading_calendar.py` | **A 股交易日历**（PMC SSE + 必盈校验） |

---

## 11. 旧方案归档

| 方案 | 脚本 | 文档 | 状态 |
|------|------|------|------|
| TickFlow 申万池 | `fetch_daily_data.py` | [TickFlow 文档](https://docs.tickflow.org/zh-Hans/api-reference/introduction) | 归档，覆盖 ~85% |
| StockAPI 东财 BK | `fetch_sector_data.py` | https://www.stockapi.com.cn | 归档，非申万 |
| BigQuant DAI | `fetch_bq_daily.py` | https://bigquant.com/data/datasources/ | 备选，需 SDK 权限 |
