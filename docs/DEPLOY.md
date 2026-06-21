# 自动化部署（GitHub → 腾讯云）

推送到 `main` 后，GitHub Actions 自动通过 SSH 登录腾讯云服务器，拉取最新代码、装依赖并重启服务。

> 流程：`合并 PR 到 main` → `.github/workflows/deploy.yml` 触发 → SSH 到服务器 → `git reset --hard origin/main` → `deploy/remote_deploy.sh`（装依赖 + 同步日历 + 重启 systemd + 健康检查）。

---

## 0. 一次性准备

### 0.1 服务器首次初始化（手动，仅一次）

```bash
# 登录服务器
ssh ubuntu@<服务器IP>

# 克隆仓库到默认路径
cd ~ && git clone https://github.com/Austin-Wang-1993/Trend_Analysis.git
cd ~/Trend_Analysis

# 写入 .env（不入库；至少包含 TUSHARE_TOKEN）
cat > .env <<'EOF'
TUSHARE_TOKEN=你的真实token
EOF

# 首次安装（建 venv、装依赖、装 systemd 服务）
bash deploy/install.sh
```

### 0.2 配置免密重启（sudoers）

CI 通过 SSH 执行 `sudo systemctl restart`，需免密。`sudo visudo -f /etc/sudoers.d/trend-analysis`：

```
ubuntu ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart trend-analysis, /usr/bin/systemctl is-active trend-analysis, /usr/bin/journalctl -u trend-analysis *
```

> 路径以 `which systemctl` / `which journalctl` 为准（Ubuntu 多为 `/usr/bin/`）。

### 0.3 生成部署用 SSH 密钥

在**本地**生成一对专用部署密钥（不要复用个人密钥）：

```bash
ssh-keygen -t ed25519 -f deploy_key -N "" -C "github-actions-deploy"

# 公钥加入服务器
ssh-copy-id -i deploy_key.pub ubuntu@<服务器IP>
# 或手动：把 deploy_key.pub 内容追加到服务器 ~/.ssh/authorized_keys

# 私钥内容（deploy_key）稍后填入 GitHub Secret TENCENT_SSH_KEY
cat deploy_key
```

### 0.4 配置 GitHub Secrets

仓库 → **Settings → Secrets and variables → Actions → New repository secret**：

| Secret | 必填 | 说明 |
|--------|------|------|
| `TENCENT_HOST` | ✅ | 服务器公网 IP 或域名 |
| `TENCENT_USER` | ✅ | 登录用户名（如 `ubuntu`） |
| `TENCENT_SSH_KEY` | ✅ | 部署私钥（`deploy_key` 全文，含首尾 `-----BEGIN/END-----`） |
| `TENCENT_PORT` | ❌ | SSH 端口，默认 `22` |
| `TENCENT_DEPLOY_PATH` | ❌ | 仓库路径，默认 `/home/ubuntu/Trend_Analysis` |

> 腾讯云安全组需放通 SSH 端口（来源可设 GitHub Actions 出口或临时 0.0.0.0/0）。看板端口 `8080` 按需放通。

---

## 1. 日常使用

- 合并任意 PR 到 `main` → 自动部署。
- 也可在 **Actions → Deploy to Tencent Cloud → Run workflow** 手动触发。
- 部署日志在该 workflow run 中查看；服务日志：`sudo journalctl -u trend-analysis -f`。

## 2. 手动部署（不经 CI）

```bash
ssh ubuntu@<服务器IP>
cd ~/Trend_Analysis
git fetch origin main && git reset --hard origin/main
bash deploy/remote_deploy.sh
```

## 3. 注意事项

- `git reset --hard origin/main` 会丢弃服务器上对**已跟踪文件**的本地改动；`.env`、`data/`、`.venv/`、`logs/` 均被 `.gitignore` 忽略，不受影响。
- 服务器只跟随 `main`（见 [BRANCHING.md](./BRANCHING.md)）。
- `TUSHARE_TOKEN` 只存在服务器 `.env`，**绝不进入 CI 或 Git**。
- v4.0 换源后首次建库（方案 A 清空重拉）：
  ```bash
  source .venv/bin/activate && set -a && source .env && set +a
  python3 scripts/fetch_ts_daily.py --mapping-only                    # 四套行业映射（含同花顺，约 8 分钟）
  python3 scripts/fetch_ts_daily.py --start 20250101 --end 20250613   # 区间补数（≤400 交易日）
  ```
  之后每日 21:35 自动采集（缓存映射，约 8 秒）、每周日 02:00 自动刷新映射。

## 4. 排错

| 现象 | 排查 |
|------|------|
| CI 卡在 SSH | 检查 `TENCENT_HOST/PORT`、安全组放通、`TENCENT_SSH_KEY` 是否完整私钥 |
| `sudo: a password is required` | 未配置 0.2 的 sudoers 免密 |
| 服务起不来 | `sudo journalctl -u trend-analysis -n 50`；多为 `.env` 缺失或依赖未装 |
| 看板打不开 | 安全组放通 8080；`curl 127.0.0.1:8080` 自测 |
