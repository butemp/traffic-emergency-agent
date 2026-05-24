#!/usr/bin/env python3
"""查询本地应急物资仓库（命令行 CLI，输出 UTF-8 JSON 到 stdout）。

数据来源：data/仓库和队伍的物资数据/warehouse_dispatch_resources.jsonl
（按仓库预聚合好的索引，每行一个仓库，含 categories / materials_by_category 等）。

子命令：
  list [--limit N] [--offset M] [--with-coords-only]    分页列出
  get --id <X>                                            按 warehouse_id 取单条
  search --keyword <Y> [--limit N]                       模糊搜（按 name/address/principal/belong_org_name）
  filter [--category <X>] [--org <Y>] [--limit N]        按 categories/所属机构 过滤
  nearby --lng <X> --lat <Y> --radius <K>                按坐标半径查（km）

示例：
  python3 scripts/query_warehouses.py list --limit 5 --with-coords-only
  python3 scripts/query_warehouses.py search --keyword "南宁"
  python3 scripts/query_warehouses.py filter --category WARNING
  python3 scripts/query_warehouses.py nearby --lng 108.32 --lat 22.84 --radius 30
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._schemas import WAREHOUSE_JSONL_PATH


def emit(obj):
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2, default=str)
    sys.stdout.write("\n")


def _load_warehouses() -> list[dict]:
    if not WAREHOUSE_JSONL_PATH.exists():
        print(f"错误：仓库数据文件不存在: {WAREHOUSE_JSONL_PATH}", file=sys.stderr)
        sys.exit(2)
    records = []
    with open(WAREHOUSE_JSONL_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"警告：跳过无法解析行: {e}", file=sys.stderr)
    return records


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlmb/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def _project(rec: dict) -> dict:
    """精简返回字段（剔除 materials_by_category 详细物资清单，list 视图保持精简）。"""
    keep = (
        "warehouse_id", "warehouse_name", "warehouse_type",
        "belong_org_name", "belong_org_code", "address",
        "latitude", "longitude", "road_code", "stake",
        "principal", "contact_phone",
        "verification_state", "last_verified_at", "next_due_at",
        "categories", "material_item_count", "material_kind_count",
    )
    return {k: rec.get(k) for k in keep if rec.get(k) not in (None, "")}


def _full(rec: dict) -> dict:
    """单条 get 返回完整记录（含 materials_by_category）。"""
    return rec


def _contains(haystack, needle: str) -> bool:
    return needle.lower() in str(haystack or "").lower()


def cmd_list(args):
    records = _load_warehouses()
    if args.with_coords_only:
        records = [r for r in records if r.get("latitude") and r.get("longitude")]
    total = len(records)
    offset = max(0, int(args.offset or 0))
    limit = max(1, int(args.limit or 20))
    chunk = records[offset : offset + limit]
    emit({
        "total": total,
        "offset": offset,
        "limit": limit,
        "count": len(chunk),
        "warehouses": [_project(r) for r in chunk],
        "source": str(WAREHOUSE_JSONL_PATH),
        "filter_with_coords_only": bool(args.with_coords_only),
    })


def cmd_get(args):
    records = _load_warehouses()
    target = str(args.id).strip()
    for r in records:
        if str(r.get("warehouse_id") or "").strip() == target:
            emit({"status": "success", "warehouse": _full(r)})
            return
    emit({"status": "not_found", "warehouse_id": target})
    sys.exit(1)


def cmd_search(args):
    records = _load_warehouses()
    kw = str(args.keyword).strip()
    if not kw:
        print("错误：--keyword 不能为空", file=sys.stderr)
        sys.exit(2)
    fields = ("warehouse_name", "address", "principal", "belong_org_name", "road_code")
    hits = [r for r in records if any(_contains(r.get(f), kw) for f in fields)]
    limit = max(1, int(args.limit or 20))
    emit({
        "keyword": kw,
        "total_hits": len(hits),
        "count": min(len(hits), limit),
        "warehouses": [_project(r) for r in hits[:limit]],
    })


def cmd_filter(args):
    records = _load_warehouses()
    hits = []
    for r in records:
        if args.category:
            cats = r.get("categories") or []
            if args.category.upper() not in [str(c).upper() for c in cats]:
                continue
        if args.org and not _contains(r.get("belong_org_name"), args.org):
            continue
        hits.append(r)
    limit = max(1, int(args.limit or 20))
    emit({
        "filter": {
            "category": (args.category or "").upper(),
            "org": args.org or "",
        },
        "total_hits": len(hits),
        "count": min(len(hits), limit),
        "warehouses": [_project(r) for r in hits[:limit]],
    })


def cmd_nearby(args):
    records = _load_warehouses()
    lng = float(args.lng)
    lat = float(args.lat)
    radius = float(args.radius)
    hits = []
    for r in records:
        rlat = r.get("latitude")
        rlng = r.get("longitude")
        if rlat is None or rlng is None:
            continue
        d = _haversine_km(lat, lng, float(rlat), float(rlng))
        if d <= radius:
            entry = _project(r)
            entry["distance_km"] = round(d, 2)
            hits.append(entry)
    hits.sort(key=lambda x: x["distance_km"])
    limit = max(1, int(args.limit or 20))
    emit({
        "query": {"lng": lng, "lat": lat, "radius_km": radius},
        "total_hits": len(hits),
        "count": min(len(hits), limit),
        "warehouses": hits[:limit],
    })


def main():
    parser = argparse.ArgumentParser(description="查询本地应急物资仓库")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="分页列出全部仓库")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.add_argument("--offset", type=int, default=0)
    p_list.add_argument("--with-coords-only", action="store_true", help="仅返回有坐标的仓库")

    p_get = sub.add_parser("get", help="按 warehouse_id 取单条（含完整物资清单）")
    p_get.add_argument("--id", required=True)

    p_search = sub.add_parser("search", help="按关键词模糊搜")
    p_search.add_argument("--keyword", required=True)
    p_search.add_argument("--limit", type=int, default=20)

    p_filter = sub.add_parser("filter", help="按类别/所属机构过滤")
    p_filter.add_argument("--category", help="物资类别（SIGN/WARNING/PPE/FIRE/TOOL/VEHICLE/MATERIAL/RESCUE/COMMS/DEICE/OTHER）")
    p_filter.add_argument("--org", help="所属机构（模糊匹配）")
    p_filter.add_argument("--limit", type=int, default=20)

    p_near = sub.add_parser("nearby", help="按坐标半径查（km）")
    p_near.add_argument("--lng", type=float, required=True)
    p_near.add_argument("--lat", type=float, required=True)
    p_near.add_argument("--radius", type=float, required=True)
    p_near.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()
    {
        "list": cmd_list,
        "get": cmd_get,
        "search": cmd_search,
        "filter": cmd_filter,
        "nearby": cmd_nearby,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
