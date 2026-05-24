#!/usr/bin/env python3
"""查询本地救援队伍（命令行 CLI，输出 UTF-8 JSON 到 stdout）。

数据来源：data/仓库和队伍的物资数据/rescue_team_dispatch_resources.jsonl
（按队伍预聚合好的索引）。

子命令：
  list [--limit N] [--offset M] [--with-coords-only]    分页列出
  get --id <X>                                            按 team_id 取单条
  search --keyword <Y> [--limit N]                       模糊搜（按 name/specialties/address/leader_name/jurisdiction_unit）
  filter [--specialty <Y>] [--unit <Y>] [--limit N]      过滤
  nearby --lng <X> --lat <Y> --radius <K>                按坐标半径查（km）

示例：
  python3 scripts/query_teams.py list --limit 5 --with-coords-only
  python3 scripts/query_teams.py search --keyword "抢修"
  python3 scripts/query_teams.py nearby --lng 108.32 --lat 22.84 --radius 50
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._schemas import TEAM_JSONL_PATH


def emit(obj):
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2, default=str)
    sys.stdout.write("\n")


def _load_teams() -> list[dict]:
    if not TEAM_JSONL_PATH.exists():
        print(f"错误：救援队数据文件不存在: {TEAM_JSONL_PATH}", file=sys.stderr)
        sys.exit(2)
    records = []
    with open(TEAM_JSONL_PATH, encoding="utf-8") as f:
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
    keep = (
        "team_id", "team_name", "team_code", "team_type", "team_size",
        "leader_name", "leader_phone",
        "jurisdiction_unit", "jurisdiction_leader", "jurisdiction_phone",
        "specialties", "address",
        "latitude", "longitude", "road_code", "stake",
        "verification_state", "last_verified_at", "next_due_at",
        "categories", "material_item_count", "material_kind_count",
    )
    return {k: rec.get(k) for k in keep if rec.get(k) not in (None, "")}


def _contains(haystack, needle: str) -> bool:
    return needle.lower() in str(haystack or "").lower()


def cmd_list(args):
    records = _load_teams()
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
        "teams": [_project(r) for r in chunk],
        "source": str(TEAM_JSONL_PATH),
        "filter_with_coords_only": bool(args.with_coords_only),
    })


def cmd_get(args):
    records = _load_teams()
    target = str(args.id).strip()
    for r in records:
        if str(r.get("team_id") or "").strip() == target:
            emit({"status": "success", "team": r})
            return
    emit({"status": "not_found", "team_id": target})
    sys.exit(1)


def cmd_search(args):
    records = _load_teams()
    kw = str(args.keyword).strip()
    if not kw:
        print("错误：--keyword 不能为空", file=sys.stderr)
        sys.exit(2)
    fields = ("team_name", "specialties", "address", "leader_name", "jurisdiction_unit", "road_code")
    hits = [r for r in records if any(_contains(r.get(f), kw) for f in fields)]
    limit = max(1, int(args.limit or 20))
    emit({
        "keyword": kw,
        "total_hits": len(hits),
        "count": min(len(hits), limit),
        "teams": [_project(r) for r in hits[:limit]],
    })


def cmd_filter(args):
    records = _load_teams()
    hits = []
    for r in records:
        if args.specialty and not _contains(r.get("specialties"), args.specialty):
            continue
        if args.unit and not _contains(r.get("jurisdiction_unit"), args.unit):
            continue
        hits.append(r)
    limit = max(1, int(args.limit or 20))
    emit({
        "filter": {"specialty": args.specialty or "", "unit": args.unit or ""},
        "total_hits": len(hits),
        "count": min(len(hits), limit),
        "teams": [_project(r) for r in hits[:limit]],
    })


def cmd_nearby(args):
    records = _load_teams()
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
        "teams": hits[:limit],
    })


def main():
    parser = argparse.ArgumentParser(description="查询本地救援队伍")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="分页列出全部救援队")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.add_argument("--offset", type=int, default=0)
    p_list.add_argument("--with-coords-only", action="store_true")

    p_get = sub.add_parser("get", help="按 team_id 取单条")
    p_get.add_argument("--id", required=True)

    p_search = sub.add_parser("search", help="按关键词模糊搜")
    p_search.add_argument("--keyword", required=True)
    p_search.add_argument("--limit", type=int, default=20)

    p_filter = sub.add_parser("filter", help="按专长/管辖单位过滤")
    p_filter.add_argument("--specialty", help="专长描述（模糊匹配 specialties）")
    p_filter.add_argument("--unit", help="管辖单位（模糊匹配 jurisdiction_unit）")
    p_filter.add_argument("--limit", type=int, default=20)

    p_near = sub.add_parser("nearby", help="按坐标半径查")
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
