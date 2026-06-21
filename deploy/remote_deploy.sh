#!/usr/bin/env bash
# 服务器端部署脚本（由 GitHub Actions 通过 SSH 调用，也可手动运行）。
# 约定：代码已由 CI 同步到最新 main（见 .github/workflows/deploy.yml）；
# 本脚本只负责：装依赖 → 同步交易日历 → 重启 systemd 服务 → 健康检查。
#
# 手动全量更新（在服务器上）：
#   cd ~/Trend_Analysis && git fetch origin main && git reset --hard origin/main && bash deploy/remote_deploy.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
echo "==> 部署目录: $ROOT"
echo "==> 当前提交: $(git rev-parse --short HEAD 2>/dev/null || echo unknown)"

# 1) Python 依赖（venv）
if [[ ! -d .venv ]]; then
  echo "==> 创建 venv"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo "==> 安装/更新依赖"
pip install -q --upgrade pip
pip install -q -r requirements.txt

# 2) 校验 .env（TUSHARE_TOKEN 必须由运维写入服务器本地 .env，不入库）
if [[ ! -f .env ]]; then
  echo "!! 警告：未找到 .env（应包含 TUSHARE_TOKEN）。采集任务会失败。"
fi

# 3) 同步交易日历（非致命）
echo "==> 同步交易日历"
python3 scripts/trading_calendar.py sync-db data/history.db \
  --start "$(date +%Y)-01-01" --end "$(date +%Y)-12-31" || echo "  (交易日历同步失败，已跳过)"

# 4) 重启服务
if command -v systemctl >/dev/null 2>&1; then
  echo "==> 重启 trend-analysis 服务"
  sudo -n systemctl restart trend-analysis
  sleep 3
  if sudo -n systemctl is-active --quiet trend-analysis; then
    echo "==> 服务运行中 ✅"
  else
    echo "!! 服务未能启动，最近日志："
    sudo -n journalctl -u trend-analysis -n 40 --no-pager || true
    exit 1
  fi
else
  echo "!! 无 systemctl，请手动：nohup .venv/bin/python scripts/serve_dashboard.py &"
fi

echo "==> 部署完成 $(date '+%Y-%m-%d %H:%M:%S')"
