# 项目文档索引

A 股申万行业成交额分析 — Phase 1 文档归档。

---

## 核心文档

| 文档 | 说明 |
|------|------|
| [REQUIREMENTS.md](./REQUIREMENTS.md) | 需求：目标、数据能力、交付物、阶段规划 |
| [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md) | 实现：架构、采集流程、脚本用法 |
| [BIYING_API.md](./BIYING_API.md) | **必盈 API 接入归档**（接口 URL、字段、命令、实测） |

---

## 必盈 API 快速链接

| 资源 | 地址 |
|------|------|
| 沪深 A 股文档 | https://www.biyingapi.com/doc_hs |
| 文档中心 | https://www.biyingapi.com/doc-center |
| 常见问题 | https://www.biyingapi.com/ask |
| 官网 / 注册 | https://www.biyingapi.com |

---

## 主入口

```bash
export BIYING_LICENCE=你的licence
python3 scripts/fetch_by_daily.py --no-all-turnover
```

详见项目根目录 [README.md](../README.md)。

---

## 版本历史

| 版本 | 日期 | 数据源 | 说明 |
|------|------|--------|------|
| v1.0 | — | BigQuant | 初版方案 |
| v1.1 | — | TickFlow | 申万标的池 |
| **v2.0** | 2026-06-15 | **必盈 API** | hszg 映射 + ssjy_more 成交额，Phase 1 跑通 |
