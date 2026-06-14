# 实施计划

## Phase 1 — MVP（当前分支）

1. **字段定义**：`docs/FIELD_DEFINITIONS.md`
2. **接口映射**：`docs/AKSHARE_MAPPING.md`
3. **架构解耦**：`sync/` 采集落库，`analysis/` 读库分析
4. **单日验证**：`scripts/verify_one_day.py`
5. **部署脚本**：`scripts/deploy_tencent_cloud.sh`

### 验证结果（海外 CI 环境）

| 任务 | 东财 | 同花顺降级 | 落库行数 |
|------|------|------------|----------|
| 大盘 | 失败 | 个股汇总 | 1 |
| 板块 | 失败 | 行业+概念 | 584 |
| 个股 | 失败 | 即时全市场 | 5194 |
| ETF | 成功 | - | 1507 |

**结论**：流水线可跑通；建议在 **腾讯云国内节点** 部署，东财接口成功率更高。

### 历史数据

- 无免费「全市场每日截面」历史 API
- 策略：每个交易日 `sync_all` 落库 → 自建 `analysis_snapshot` 时间序列
- Phase 2 在此基础上做趋势看板

## Phase 2 — 趋势看板

- Streamlit / Grafana 读取 `analysis_snapshot`
- 板块/个股历史回补 worker（`stock_sector_fund_flow_hist` 等）
- 付费数据源：实现 `FundFlowSource` 新 adapter

## Phase 3 — 生产加固

- PostgreSQL + 备份
- 监控 sync 失败告警
- 板块内个股明细（`stock_sector_fund_flow_summary`）
