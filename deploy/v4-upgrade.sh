#!/usr/bin/env bash
# v4.0 Tushare 换源一键部署（在服务器 ~/Trend_Analysis 下执行）
#
# 用法（二选一）：
#   TUSHARE_TOKEN='你的token' bash deploy/v4-upgrade.sh
#   bash deploy/v4-upgrade.sh '你的token'
#
# 可选环境变量：
#   ROOT=/home/ubuntu/Trend_Analysis   项目目录
#   BRANCH=cursor/tushare-v4-implementation-df9e   代码分支（合并 main 后改为 main）
#   BACKFILL_DAYS=400                  补数交易日数量（上限 400）
#   SKIP_GIT=1                         跳过 git 拉代码
#   SKIP_BACKFILL=1                    只刷映射，不补历史
#   NO_SERVICE=1                       不 stop/restart systemd

set -euo pipefail

ROOT="${ROOT:-$HOME/Trend_Analysis}"
BRANCH="${BRANCH:-cursor/tushare-v4-implementation-df9e}"
BACKFILL_DAYS="${BACKFILL_DAYS:-400}"
TOKEN="${TUSHARE_TOKEN:-${1:-}}"

if [[ -z "$TOKEN" ]]; then
  echo "错误: 请设置 TUSHARE_TOKEN 或作为第一个参数传入" >&2
  echo "示例: TUSHARE_TOKEN='xxx' bash deploy/v4-upgrade.sh" >&2
  exit 1
fi

if [[ ! -d "$ROOT" ]]; then
  echo "错误: 项目目录不存在: $ROOT" >&2
  exit 1
fi

cd "$ROOT"
echo "==> 工作目录: $ROOT"

if [[ "${SKIP_GIT:-0}" != "1" ]]; then
  echo "==> 拉取代码分支: $BRANCH"
  git fetch origin "$BRANCH"
  git checkout "$BRANCH"
  git merge --ff-only "origin/$BRANCH" 2>/dev/null || git reset --hard "origin/$BRANCH"
fi

echo "==> 写入 .env（TUSHARE_TOKEN，不提交 Git）"
ENV_FILE="$ROOT/.env"
touch "$ENV_FILE"
if grep -q '^TUSHARE_TOKEN=' "$ENV_FILE" 2>/dev/null; then
  sed -i "s|^TUSHARE_TOKEN=.*|TUSHARE_TOKEN=${TOKEN}|" "$ENV_FILE"
else
  echo "TUSHARE_TOKEN=${TOKEN}" >> "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"

echo "==> Python 虚拟环境与依赖"
python3 -m venv .venv 2>/dev/null || true
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -U pip
pip install -q -r requirements.txt

if [[ "${NO_SERVICE:-0}" != "1" ]] && command -v systemctl >/dev/null 2>&1; then
  echo "==> 停止 trend-analysis 服务"
  sudo systemctl stop trend-analysis 2>/dev/null || true
fi

DB="$ROOT/data/history.db"
if [[ -f "$DB" ]]; then
  BAK="$ROOT/data/history.db.bak.$(date +%Y%m%d_%H%M%S)"
  echo "==> 备份 history.db → $BAK"
  cp -a "$DB" "$BAK"
  rm -f "$DB" "${DB}-wal" "${DB}-shm" 2>/dev/null || true
else
  echo "==> 无现有 history.db，将新建"
fi
mkdir -p "$ROOT/data/cache" "$ROOT/logs/jobs"

YEAR="$(date +%Y)"
echo "==> 同步交易日历 ${YEAR}"
python3 scripts/trading_calendar.py sync-db "$DB" --start "${YEAR}-01-01" --end "${YEAR}-12-31" || true

echo "==> 刷新四套行业映射（东财较慢，请耐心等待）"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
python3 scripts/refresh_sector_mappings.py

if [[ "${SKIP_BACKFILL:-0}" == "1" ]]; then
  echo "==> 跳过历史补数（SKIP_BACKFILL=1）"
else
  echo "==> 计算补数区间（最近 ${BACKFILL_DAYS} 个交易日）"
  read -r START_DATE END_DATE <<< "$(python3 - <<'PY'
import os, sys
sys.path.insert(0, "scripts")
from trading_calendar import get_recent_trading_days, today_cst
n = int(os.environ.get("BACKFILL_DAYS", "400"))
days = get_recent_trading_days(min(n, 400))
print(days[0], days[-1])
PY
)"
  echo "==> 区间补数: ${START_DATE} ~ ${END_DATE}（约 ${BACKFILL_DAYS} 交易日，耗时较长）"
  python3 scripts/fetch_ts_range.py --start "$START_DATE" --end "$END_DATE"
fi

if [[ "${NO_SERVICE:-0}" != "1" ]] && command -v systemctl >/dev/null 2>&1; then
  echo "==> 更新并重启 systemd 服务"
  sudo cp deploy/trend-analysis.service /etc/systemd/system/trend-analysis.service
  sudo sed -i "s|/home/ubuntu/Trend_Analysis|${ROOT}|g" /etc/systemd/system/trend-analysis.service
  sudo systemctl daemon-reload
  sudo systemctl enable trend-analysis
  sudo systemctl restart trend-analysis
  sleep 2
  sudo systemctl status trend-analysis --no-pager || true
fi

echo ""
echo "=========================================="
echo " v4 部署完成"
echo " 看板: http://$(hostname -I 2>/dev/null | awk '{print $1}'):8080"
echo " 分支: $BRANCH"
echo " 补数: ${START_DATE:-跳过} ~ ${END_DATE:-跳过}"
echo "=========================================="
