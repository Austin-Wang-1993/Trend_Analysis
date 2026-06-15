# 项目文档索引

A 股申万行业 **成交额 + 买卖** 分析与 Web 看板。

---

## 核心文档

| 文档 | 说明 |
|------|------|
| [**REQUIREMENTS.md**](./REQUIREMENTS.md) | **v3.0** 需求：看板页面 1–4、历史序列、单位规则、验收标准 |
| [**IMPLEMENTATION_PLAN.md**](./IMPLEMENTATION_PLAN.md) | **v3.0** 方案：SQLite、FastAPI、ECharts、目录与实施顺序 |
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
| **v3.0** | 2026-06-15 | **看板需求 + 历史落库 + 四页面前端方案** |
