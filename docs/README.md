# 项目文档索引

A 股**细分行业** **成交额 + 买卖** 分析与 Web 看板。  
（**v4.0 规划**：Tushare 四套行业——申万三级 / 中信三级 / 东财 / 同花顺；**v3.6 线上**：必盈 + 申万二级 / 概念 Tab）

> **Git / 部署强制规则**：只跟 `main`；临时分支 `cursor/<简述>-df9e` 合并后立刻删；服务器见 [BRANCHING.md §0](./BRANCHING.md#0-强制规则长期有效)。

---

## 核心文档

| 文档 | 说明 |
|------|------|
| [**TUSHARE_SECTOR_DESIGN.md**](./TUSHARE_SECTOR_DESIGN.md) | **v4.0** 四套行业 Tab、指标、验收（已确认） |
| [**TUSHARE_API.md**](./TUSHARE_API.md) | Tushare 接口与字段映射 |
| [**REQUIREMENTS.md**](./REQUIREMENTS.md) | **v4.0** 需求摘要 + v3.6 归档 |
| [**IMPLEMENTATION_PLAN.md**](./IMPLEMENTATION_PLAN.md) | **v4.0** 方案 + v3.6 实现 |
| [**BRANCHING.md**](./BRANCHING.md) | 分支策略、部署只跟 main |
| [**DEPLOY.md**](./DEPLOY.md) | **自动化部署：push main → GitHub Actions → 腾讯云** |
| [BIYING_API.md](./BIYING_API.md) | 必盈 API（v3.6 归档） |

---

## 主入口

```bash
export BIYING_LICENCE=你的licence

# 采集（默认 L2）
python3 scripts/fetch_by_daily.py --no-all-turnover

# L1 库 → L2 看板（无需重打 API）
python3 scripts/build_sector_mapping.py --level l2
python3 scripts/migrate_sectors_to_l2.py
# 或仅重算 sector 并清理僵尸行（stock 已是 L2 时）
python3 scripts/rebuild_sector_aggregates.py

# 看板
python3 scripts/serve_dashboard.py
```

---

## 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| v3.3 | 2026-06-15 | 21:35 定时；PMC 交易日历；Web 看板 + 管理页 |
| **v3.4** | 2026-06-15 | **申万 L2 默认**；`migrate_sectors_to_l2`；补数 **交易日校验** + **任务取消** |
| **v3.5** | 2026-06-15 | 管理页 **区间补数**（起止必填、不跳过已有；上限 ≤30 → v3.6 起放宽至 **≤400**）；**移除强制补数** |
| **v3.6** | 2026-06-18 | 必盈概念 Tab；原子资金流；分支收敛 main |
| **v4.0** | 规划中 | **Tushare** 四套细分行业；5/15/30 日；移除概念 Tab |
