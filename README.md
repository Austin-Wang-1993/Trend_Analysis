# Trend_Analysis

A 股**行业成交额**数据（Phase 1）。

## 文档

- [需求文档](docs/REQUIREMENTS.md) — 已确认 v0.2
- [实现方案](docs/IMPLEMENTATION_PLAN.md)

## 快速开始（腾讯云国内节点，交易日 17:00 后）

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # 仅需 pandas / requests / tenacity，不依赖 akshare
python scripts/fetch_daily_data.py
ls data/
```

输出见 `data/*.csv` 与 `data/README.md`。
