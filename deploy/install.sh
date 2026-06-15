#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> 安装 Python 依赖"
python3 -m venv .venv 2>/dev/null || true
source .venv/bin/activate
pip install -q -r requirements.txt

echo "==> 导入现有 CSV 到 history.db（若有）"
if [[ -f data/stock_turnover_latest.csv ]]; then
  python3 scripts/import_csv_snapshot.py || true
fi

echo "==> 同步交易日历"
python3 scripts/trading_calendar.py sync-db data/history.db --start "$(date +%Y)-01-01" --end "$(date +%Y)-12-31" || true

echo "==> 安装 systemd 服务（需 sudo）"
if command -v systemctl >/dev/null 2>&1; then
  sudo cp deploy/trend-analysis.service /etc/systemd/system/trend-analysis.service
  sudo sed -i "s|/home/ubuntu/Trend_Analysis|${ROOT}|g" /etc/systemd/system/trend-analysis.service
  sudo systemctl daemon-reload
  sudo systemctl enable trend-analysis
  sudo systemctl restart trend-analysis
  sudo systemctl status trend-analysis --no-pager || true
else
  echo "无 systemctl，请手动运行: python3 scripts/serve_dashboard.py"
fi

echo "==> 完成。访问 http://$(hostname -I 2>/dev/null | awk '{print $1}'):8080"
