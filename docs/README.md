# 项目文档索引

A 股申万行业 **成交额 + 买卖** 分析与 Web 看板。

---

## 核心文档

| 文档 | 说明 |
|------|------|
| [**REQUIREMENTS.md**](./REQUIREMENTS.md) | **v3.3** 需求：默认定时 **21:35**、交易日/自然日、管理页 7 |
| [**IMPLEMENTATION_PLAN.md**](./IMPLEMENTATION_PLAN.md) | **v3.3** 方案：交易日历同步、APScheduler |
| [BIYING_API.md](./BIYING_API.md) | 必盈 API 接入归档 |

---

## 必盈 API 快速链接

| 资源 | 地址 |
|------|------|
| 沪深 A 股文档 | https://www.biyingapi.com/doc_hs |
| 文档中心 | https://www.biyingapi.com/doc-center |
| 官网 / 注册 | https://www.biyingapi.com |

---

## 主入口

```bash
export BIYING_LICENCE=你的licence
python3 scripts/fetch_by_daily.py --no-all-turnover
```

看板（Phase 3 完成后）：

```bash
python3 scripts/serve_dashboard.py
# http://127.0.0.1:8080
```

---

## 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | — | BigQuant 初版 |
| v1.1 | — | TickFlow 申万池 |
| v2.0 | 2026-06-15 | 必盈 hszg + 成交额 Phase 1 |
| v2.1 | 2026-06-15 | 必盈 买卖 + ETF 单日 CSV |
| **v3.0** | 2026-06-15 | 看板四页面 + 30 日买卖（已 supersede） |
| **v3.1** | 2026-06-15 | 六页面看板；统一近 5 日；ETF 表格/图表 |
| **v3.2** | 2026-06-15 | 管理页 7：定时、补数、ZIP 导出、数据日历 |
| **v3.3** | 2026-06-15 | 默认定时 **21:35**；**交易日/自然日**；必盈日 K 同步交易日历 |
