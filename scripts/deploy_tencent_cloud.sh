#!/usr/bin/env bash
# 腾讯云 CVM 首次部署脚本（Ubuntu 22.04+）
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/trend_analysis}"
REPO_URL="${REPO_URL:-https://github.com/Austin-Wang-1993/Trend_Analysis.git}"
BRANCH="${BRANCH:-main}"

echo "==> 安装系统依赖"
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip git

echo "==> 克隆/更新代码"
if [ -d "$APP_DIR/.git" ]; then
  cd "$APP_DIR"
  git fetch origin
  git checkout "$BRANCH"
  git pull origin "$BRANCH"
else
  sudo mkdir -p "$(dirname "$APP_DIR")"
  sudo git clone -b "$BRANCH" "$REPO_URL" "$APP_DIR"
  sudo chown -R "$USER:$USER" "$APP_DIR"
  cd "$APP_DIR"
fi

echo "==> 创建虚拟环境"
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt

echo "==> 配置环境变量"
if [ ! -f .env ]; then
  cp .env.example .env
fi
mkdir -p data logs

echo "==> 初始化数据库并验证单日流水线"
python scripts/verify_one_day.py

echo "==> 安装 systemd 定时任务（可选）"
SERVICE_FILE="/etc/systemd/system/trend-analysis-sync.service"
TIMER_FILE="/etc/systemd/system/trend-analysis-sync.timer"

sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Trend Analysis Fund Flow Sync
After=network.target

[Service]
Type=oneshot
User=$USER
WorkingDirectory=$APP_DIR
Environment=PATH=$APP_DIR/.venv/bin:/usr/bin
ExecStart=$APP_DIR/.venv/bin/python -m sync.cli all --init-db
StandardOutput=append:$APP_DIR/logs/sync.log
StandardError=append:$APP_DIR/logs/sync.log

[Install]
WantedBy=multi-user.target
EOF

sudo tee "$TIMER_FILE" > /dev/null <<EOF
[Unit]
Description=Run fund flow sync on trading days 16:30

[Timer]
OnCalendar=Mon..Fri 16:30
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable trend-analysis-sync.timer
sudo systemctl start trend-analysis-sync.timer

echo "部署完成。手动验证："
echo "  cd $APP_DIR && source .venv/bin/activate"
echo "  python scripts/verify_one_day.py"
echo "  python -m analysis.cli report"
