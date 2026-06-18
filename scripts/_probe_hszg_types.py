#!/usr/bin/env python3
import collections
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from by_common import fetch_sector_tree, filter_sectors, get_licence, TYPE2_SW_L1, TYPE2_SW_L2

TYPE2_NAMES = {
    0: "申万一级",
    1: "申万二级",
    2: "热门概念",
    3: "概念板块",
    4: "地域板块",
    5: "证监会行业",
    7: "指数成分",
    9: "大盘指数",
}

def main():
    lic = get_licence()
    tree = fetch_sector_tree(lic)
    c2 = collections.Counter(int(r.get("type2", -1)) for r in tree.to_dict("records"))
    print("type2 分布:")
    for k, v in sorted(c2.items()):
        print(f"  {k} ({TYPE2_NAMES.get(k, '?')}): {v}")

    for t2, label in [(0, "SW L1"), (1, "SW L2"), (2, "热门概念"), (3, "概念板块")]:
        df = filter_sectors(tree, type2=t2, leaves_only=True)
        print(f"\n{label} (type2={t2}) 叶子数: {len(df)}")

    semi = tree[tree["name"].astype(str).str.contains("半导体", na=False)]
    print("\n名称含「半导体」:")
    for _, r in semi.head(15).iterrows():
        print(f"  type2={r['type2']} level={r['level']} leaf={r['isleaf']} {r['code']} {r['name']}")

    for kw in ["芯片设计", "芯片", "封装", "集成电路", "半导体设备"]:
        sub = tree[tree["name"].astype(str).str.contains(kw, na=False) & (tree["isleaf"] == 1)]
        if len(sub):
            print(f"\n含「{kw}」的叶子 ({len(sub)}):")
            for _, r in sub.head(10).iterrows():
                print(f"  type2={r['type2']} {r['code']} {r['name']}")

    # 兆易创新所属板块
    code = "603986"
    import requests
    rows = requests.get(f"https://api.biyingapi.com/hszg/zg/{code}/{lic}", timeout=30).json()
    if isinstance(rows, list):
        print(f"\n603986 兆易创新 反查板块 (共 {len(rows)} 条, 展示概念/芯片相关):")
        for r in rows:
            name = r.get("name", "")
            if any(k in name for k in ["半导体", "芯片", "概念", "申万", "集成电路", "存储"]):
                print(f"  type2={r.get('type2')} {r.get('code')} {name}")

if __name__ == "__main__":
    main()
