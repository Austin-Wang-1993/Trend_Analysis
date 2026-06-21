# 全股票清单页设计（v4.1）

> 状态：**已确认，开发中** · 确认日期：2026-06-21  
> 前置：[TUSHARE_SECTOR_DESIGN.md](./TUSHARE_SECTOR_DESIGN.md) · [TUSHARE_API.md](./TUSHARE_API.md)

新增「股票清单」页：一行一只 A 股，展示所属（申万三级）行业、估值与股东数等最新指标，支持搜索、板块多选筛选、正逆排序、分页。

---

## 1. 列与字段

| 列 | 来源 | 单位/格式 | 备注 |
|----|------|-----------|------|
| 所属板块 | `sector_stock_map_v4`(kind=`sw_l3`) | `L1 > L2 > L3` 全路径 | 申万三级 |
| 代码 | `stock_code` | 6 位 | |
| 名称 | `stock_name` | | |
| 最新价 | `daily_basic.close` | 元 | **盘后收盘价**（非实时） |
| 最新市值 | `daily_basic.total_mv` | 亿元（源为万元 ÷1e4） | 总市值 |
| 股息率(静态) | `daily_basic.dv_ratio` | % | **上一财年(LFY)** 现金分红 / 当前股价（市值） |
| 股息率(TTM) | `daily_basic.dv_ttm` | % | **滚动近 12 个月** 现金分红 / 当前股价（市值） |
| 市净率 PB | `daily_basic.pb` | 倍 | 总市值 / 净资产 |
| 市盈率 PE(静态) | `daily_basic.pe` | 倍 | 总市值 / 最近年报净利润；亏损为空 |
| 市盈率 PE(TTM) | `daily_basic.pe_ttm` | 倍 | 总市值 / 滚动 12 个月净利润；亏损为空 |
| 股东数 | `stk_holdernumber.holder_num` | 户 | **最近披露**一期 |
| 股东数截止日 | `stk_holdernumber.end_date` | 日期 | 股东数对应的报告期 |
| 近 3 年分红 | `dividend`（`cash_div_tax`, `end_date`, `ex_date`） | 紧凑列举 | 见下 |

**近 3 年分红列**：紧凑列举每次**已实施**的**现金分红**，每条 `所属年度 · 每股税前现金分红元 (除息日)`，按除息日倒序。例：

```
2023年度 · 0.32元 (2024-06-12)
2022年度 · 0.06元 (2023-06-21)
```

- 「近 3 年」按**除权除息日 `ex_date`** 落在最近 3 个自然年内。
- 只现金分红（`cash_div_tax`，税前），不含送股/转股；仅 `div_proc='实施'`；接口重复记录按 `(ts_code, end_date, ex_date)` 去重。
- 无分红显示「—」。

> 页面在表头/页脚标注各指标计算口径（如上表「备注」列）。

---

## 2. 交互

- **分页**：默认每页 100，可选 50/100/200。
- **搜索**：代码 / 名称 / 板块名 模糊匹配。
- **板块多选筛选**：
  - 可搜索的申万三级板块下拉（数据来自 `sector_catalog_v4` kind=`sw_l3`）；
  - 多选；已选板块以 chip 形式展示，可单独移除；
  - 选中后只显示这些板块的成份股。
- **排序**：点列头切换 **升序/降序**；可排序列：最新价、市值、股息率(两种)、PB、PE(两种)、股东数、代码、名称。
- 默认排序：市值 ↓。

---

## 3. 数据来源与更新

| 数据 | 接口 | 积分 | 更新 |
|------|------|------|------|
| 估值/价/市值 | `daily_basic`（按 `trade_date` 全市场） | 2000 | **每日**随 `fetch_ts_daily` 采集 |
| 股东数 | `stk_holdernumber`（按 `ann_date` 段拉最近一期） | 600 | **每周**随映射刷新 |
| 近 3 年分红 | `dividend`（**逐股**拉取，接口不支持空参全市场） | 2000 | **每个交易日凌晨 03:30** 专项任务（约 15–20 分钟） |

- 估值为**最新交易日快照**（覆盖更新，不留历史）。
- 股东数为季度数据，取每只股票**最近一期**（`end_date` 最大）。

---

## 4. 存储

新表 `stock_metrics_v4`（一股一行，最新快照）：

```
stock_code TEXT PRIMARY KEY,
stock_name TEXT,
trade_date TEXT,          -- 估值对应交易日
close REAL,               -- 收盘价（元）
total_mv REAL,            -- 总市值（元，源万元×1e4）
pe REAL, pe_ttm REAL,
pb REAL,
dv_ratio REAL, dv_ttm REAL,   -- %（原值，前端 ×1 显示）
holder_num INTEGER,
holder_end_date TEXT,     -- 股东数报告期
holder_ann_date TEXT,     -- 股东数公告日
updated_at TEXT
```

> 所属板块不冗余存储，读取时按 `sector_stock_map_v4`(kind=`sw_l3`) 关联。

近 3 年分红另存 `stock_dividend_v4`（一股多条）：

```
stock_code TEXT,
end_date   TEXT,   -- 分红所属年度
ex_date    TEXT,   -- 除权除息日
cash_div_tax REAL, -- 每股税前现金分红（元）
PRIMARY KEY (stock_code, end_date, ex_date)
```

---

## 5. API

```
GET /api/stocks/list?page=1&page_size=100&sort=total_mv&order=desc&q=&sectors=850831.SI,851251.SI
  → { total, page, page_size, items: [ {sector_code, sector_path, stock_code, stock_name,
        close, total_mv, pe, pe_ttm, pb, dv_ratio, dv_ttm, holder_num, holder_end_date,
        dividends: [ {end_date, ex_date, cash_div_tax} ]  // 近3年，按 ex_date 倒序
      } ] }

GET /api/sectors/catalog?kind=sw_l3
  → [ {sector_code, sector_name, sector_path} ]   # 供板块多选筛选器
```

- `sort` 允许：`total_mv|close|pe|pe_ttm|pb|dv_ratio|dv_ttm|holder_num|stock_code|stock_name`
- `order`：`asc|desc`
- `sectors`：申万三级 `sector_code` 列表（逗号分隔），多选筛选
- `q`：代码/名称/板块名模糊

---

## 6. 前端

- 新页面 `dashboard/stock-list.html`，加入顶部导航（「股票清单」）。
- 普通分页表格（非卡片列）；表头可点排序、带升降箭头。
- 板块筛选：可搜索多选组件 + 已选 chips（可移除）。
- 市值显示「亿元」；空值显示「—」。

---

## 7. 验收

1. 清单展示全 A，含 11 列指标，板块为申万三级路径。
2. PE/股息率静态与 TTM 均展示，表内标注口径。
3. 搜索、板块多选筛选（可搜可移除）、各列正逆排序、分页均可用。
4. 估值每日自动更新；股东数每周更新，显示报告期。
5. 亏损股 PE 为「—」；缺失值不报错。
