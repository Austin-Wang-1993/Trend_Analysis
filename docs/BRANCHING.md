# 分支与发布说明

> 更新：2026-06-18  
> **唯一发布分支：`main`**

---

## 1. 当前状态（整理后）

| 分支 | 状态 | 说明 |
|------|------|------|
| **`main`** | ✅ 唯一活跃分支 | 包含全部已交付功能（v3.6 概念 Tab + 后续修复） |
| `cursor/*-df9e` | 🗑️ 已删除 | Cloud Agent 临时分支，内容均已 fast-forward 进 `main` |

**服务器 / 生产环境只跟踪 `main`：**

```bash
cd ~/Trend_Analysis
git fetch origin main
git merge FETCH_HEAD          # 或：git pull origin main
```

不要用 `git merge FETCH_HEAD` 却不指定 fetch 哪个分支——容易合错分支。

---

## 2. 分支策略（今后）

```
main          ← 稳定可部署，所有功能合并到这里
cursor/xxx-df9e   ← Cloud Agent 临时开发，合并后立即删除
```

| 规则 | 说明 |
|------|------|
| 默认基线 | 从 `main` 拉新分支 |
| 命名 | Cloud Agent：`cursor/<简述>-df9e` |
| 合并方式 | 功能完成 → fast-forward / squash 进 `main` → **删远程临时分支** |
| 部署 | 只部署 `main`，不在服务器长期停留 feature 分支 |
| PR | 合并后关闭；不必保留 head 分支 |

---

## 3. 已合并 PR 与 commit 线（归档）

### PR #1 — 看板卡片列 MVP

- 分支：`cursor/sector-fund-flow-mvp-df9e`（已删）
- 合并：`132fdd6` 及之前
- 内容：板块/成份股/ETF 卡片列、搜索、详情图

### PR #2 — 概念 Tab + 原子资金流

- 分支：`cursor/concept-sectors-tabs-df9e`（已删）
- 合并：`da694d8` → `main`
- 内容：页面 2 三 Tab、概念表、8 档原子字段、400 日补数

### 后续 hotfix（直接进 main，无独立 PR）

| Commit | 说明 |
|--------|------|
| `2bb76ee` | 修复板块 API 500（`_normalize_sector_table_sort`） |
| `9b9fe73` | `hszg/gg` 404 跳过；`refresh --board-only` |
| `18af3f0` | 概念聚合 merge 列冲突（`sector_code` KeyError） |
| `24cf82c` | SQLite WAL + busy_timeout |
| `3b7cf37` | rebuild 先 commit sector 再写 concept（自锁） |
| `114bd2f` | rebuild 打印映射条数、board 为空提示 |

**当前 `main` 顶端：`114bd2f`**

---

## 4. `main` 功能一览（v3.6）

| 模块 | 状态 |
|------|------|
| 申万二级 Tab | ✅ |
| 热门概念 Tab | ✅（需 `concept_stock_map` type=2 + rebuild） |
| 概念板块 Tab | ⚠️ 需 `--board-only` 刷新映射后再 rebuild |
| ETF 表格/详情 | ✅ |
| 管理页 / 定时 / 补数 | ✅ |

---

## 5. 服务器推荐工作流

```bash
# 日常更新代码
cd ~/Trend_Analysis
git fetch origin main
git merge FETCH_HEAD

# 概念板块首次补数（若 board 为空）
set -a && source .env && set +a
python scripts/refresh_sector_mappings.py --board-only
sudo systemctl stop trend-analysis
python scripts/rebuild_sector_aggregates.py
sudo systemctl start trend-analysis
```

---

## 6. 本地清理（可选）

若 clone 里还留着旧 `cursor/*` 分支：

```bash
git checkout main
git pull origin main
git branch | grep '^  cursor/' | xargs -r git branch -D
git fetch origin --prune
```
