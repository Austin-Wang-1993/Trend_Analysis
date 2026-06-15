# 项目文档索引

A 股申万 **二级** 行业 **成交额 + 买卖** 分析与 Web 看板。

---

## 核心文档

| 文档 | 说明 |
|------|------|
| [**REQUIREMENTS.md**](./REQUIREMENTS.md) | **v3.4** 需求：申万 L2、管理页校验/取消 |
| [**IMPLEMENTATION_PLAN.md**](./IMPLEMENTATION_PLAN.md) | **v3.4** 方案：迁移脚本、API |
| [BIYING_API.md](./BIYING_API.md) | 必盈 API（L2 默认、覆盖率） |

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
