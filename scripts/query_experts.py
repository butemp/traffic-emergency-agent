#!/usr/bin/env python3
"""查询本地专家库（命令行 CLI，输出 UTF-8 JSON 到 stdout）。

数据来源：优先读 data/专家数据/expert_info.json（若已通过 admin.py 迁移生成），
否则回退读 data/专家数据/expert_info.xls。

子命令：
  list [--limit N] [--offset M] [--include-deleted]   分页列出
  get --id <X>                                         按 id 取单条
  search --keyword <Y> [--limit N]                     模糊搜（按 name/specialty_field/duties/work_unit/major/address）
  filter [--specialty <Y>] [--unit <Y>] [--title <Y>]  字段精确/模糊过滤

示例：
  python3 scripts/query_experts.py list --limit 5
  python3 scripts/query_experts.py search --keyword "高速公路"
  python3 scripts/query_experts.py filter --specialty "应急管理" --title "高级"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._schemas import EXPERT_JSON_PATH, EXPERT_XLS_PATH

# 内部统一字段顺序
FIELD_ORDER = (
    "id", "name", "sex", "specialty_field", "duties", "professional_title",
    "work_unit", "major", "education", "graduation_school",
    "phone", "email", "address", "longitude", "latitude",
    "declaration_type", "remark",
    "verification_state", "on_duty_status",
)


def emit(obj):
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2, default=str)
    sys.stdout.write("\n")


def _load_experts(include_deleted: bool = False):
    """优先 JSON，否则 xls。返回 list[dict]，过滤 del_flag=1（除非显式 include_deleted）。"""
    records: list[dict] = []
    if EXPERT_JSON_PATH.exists():
        with open(EXPERT_JSON_PATH, encoding="utf-8") as f:
            records = json.load(f)
    elif EXPERT_XLS_PATH.exists():
        try:
            import xlrd
        except ImportError:
            print("错误：缺少依赖 xlrd（pip install xlrd==2.0.2）", file=sys.stderr)
            sys.exit(2)
        book = xlrd.open_workbook(str(EXPERT_XLS_PATH))
        sheet = book.sheet_by_index(0)
        headers = [str(h).strip() for h in sheet.row_values(0)]
        for r in range(1, sheet.nrows):
            row = sheet.row_values(r)
            rec = dict(zip(headers, row))
            records.append(rec)
    else:
        print(f"错误：专家数据文件不存在（{EXPERT_JSON_PATH} 和 {EXPERT_XLS_PATH} 都没找到）", file=sys.stderr)
        sys.exit(2)

    if not include_deleted:
        def _is_deleted(r):
            v = r.get("del_flag")
            return str(v).strip() in ("1", "1.0", "True", "true")
        records = [r for r in records if not _is_deleted(r)]

    # 过滤掉 name 为空的脏数据
    records = [r for r in records if str(r.get("name") or "").strip()]
    return records


def _project(rec: dict) -> dict:
    """精简返回字段（去掉 create_*/update_*/del_flag 之类内部审计字段）。"""
    return {k: rec.get(k, "") for k in FIELD_ORDER if rec.get(k) not in (None, "")}


def cmd_list(args):
    records = _load_experts(include_deleted=args.include_deleted)
    total = len(records)
    offset = max(0, int(args.offset or 0))
    limit = max(1, int(args.limit or 20))
    chunk = records[offset : offset + limit]
    emit({
        "total": total,
        "offset": offset,
        "limit": limit,
        "count": len(chunk),
        "experts": [_project(r) for r in chunk],
        "source": str(EXPERT_JSON_PATH if EXPERT_JSON_PATH.exists() else EXPERT_XLS_PATH),
    })


def cmd_get(args):
    records = _load_experts(include_deleted=args.include_deleted)
    target = str(args.id).strip()
    for r in records:
        if str(r.get("id") or "").strip() == target:
            emit({"status": "success", "expert": _project(r)})
            return
    emit({"status": "not_found", "id": target})
    sys.exit(1)


def _contains(haystack: str, needle: str) -> bool:
    return needle.lower() in str(haystack or "").lower()


def cmd_search(args):
    records = _load_experts(include_deleted=args.include_deleted)
    kw = str(args.keyword).strip()
    if not kw:
        print("错误：--keyword 不能为空", file=sys.stderr)
        sys.exit(2)
    fields = ("name", "specialty_field", "duties", "professional_title",
              "work_unit", "major", "address", "declaration_type")
    hits = []
    for r in records:
        if any(_contains(r.get(f), kw) for f in fields):
            hits.append(_project(r))
    limit = max(1, int(args.limit or 20))
    emit({
        "keyword": kw,
        "total_hits": len(hits),
        "count": min(len(hits), limit),
        "experts": hits[:limit],
    })


def cmd_filter(args):
    records = _load_experts(include_deleted=args.include_deleted)
    hits = []
    for r in records:
        if args.specialty and not _contains(r.get("specialty_field"), args.specialty):
            continue
        if args.unit and not _contains(r.get("work_unit"), args.unit):
            continue
        if args.title and not _contains(r.get("professional_title"), args.title):
            continue
        hits.append(_project(r))
    limit = max(1, int(args.limit or 20))
    emit({
        "filter": {
            "specialty": args.specialty or "",
            "unit": args.unit or "",
            "title": args.title or "",
        },
        "total_hits": len(hits),
        "count": min(len(hits), limit),
        "experts": hits[:limit],
    })


def main():
    parser = argparse.ArgumentParser(description="查询本地专家库")
    parser.add_argument("--include-deleted", action="store_true", help="包含 del_flag=1 的记录（默认过滤）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="分页列出全部专家")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.add_argument("--offset", type=int, default=0)

    p_get = sub.add_parser("get", help="按 id 取单条")
    p_get.add_argument("--id", required=True)

    p_search = sub.add_parser("search", help="按关键词模糊搜（name/specialty/duties/unit/major/address）")
    p_search.add_argument("--keyword", required=True)
    p_search.add_argument("--limit", type=int, default=20)

    p_filter = sub.add_parser("filter", help="按字段过滤")
    p_filter.add_argument("--specialty", help="专业方向（模糊匹配）")
    p_filter.add_argument("--unit", help="工作单位（模糊匹配）")
    p_filter.add_argument("--title", help="职称（模糊匹配）")
    p_filter.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()
    {
        "list": cmd_list,
        "get": cmd_get,
        "search": cmd_search,
        "filter": cmd_filter,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
