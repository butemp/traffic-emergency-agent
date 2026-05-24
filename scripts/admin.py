#!/usr/bin/env python3
"""录入新数据到本地知识库（命令行 CLI）。

4 个子命令：
  add-plan       --file <X.json> [--overwrite]
  add-expert     --file <X.json>
  add-warehouse  --file <X.json>
  add-team       --file <X.json>

通用选项：
  --reload    写完成功后调用 http://localhost:8000/api/v1/plans/reload（需要 API 服务在跑；连不上仅警告）

校验失败：stderr 输出错误清单 + 退出码 1。
校验通过：stdout 输出 JSON 状态 + 退出码 0。

录入格式参考：scripts/examples/ 下 4 个样例 JSON。

示例：
  python3 scripts/admin.py add-plan --file my_new_plan.json
  python3 scripts/admin.py add-expert --file my_expert.json --reload
  python3 scripts/admin.py add-warehouse --file my_warehouse.json
  python3 scripts/admin.py add-team --file my_team.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._schemas import (
    PLANS_DIR, PLAN_INDEX_PATH,
    EXPERT_JSON_PATH, EXPERT_XLS_PATH,
    WAREHOUSE_JSONL_PATH, TEAM_JSONL_PATH,
    validate_plan, validate_expert, validate_warehouse, validate_team,
    format_errors,
)


def emit(obj):
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2, default=str)
    sys.stdout.write("\n")


def _load_json_file(path: Path) -> Any:
    if not path.exists():
        print(f"错误：文件不存在: {path}", file=sys.stderr)
        sys.exit(2)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except UnicodeDecodeError:
        print(f"错误：文件不是 UTF-8 编码: {path}", file=sys.stderr)
        sys.exit(2)
    except json.JSONDecodeError as e:
        print(f"错误：文件不是合法 JSON: {path}\n  {e.msg} (line {e.lineno}, column {e.colno})", file=sys.stderr)
        sys.exit(2)


def _try_reload_plans():
    """可选热加载（仅对预案有效；专家/仓库/队伍由 Agent 自己每任务重载，无需服务端 reload）。"""
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://localhost:8000/api/v1/plans/reload",
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return {"reload_status": resp.status, "reload_body": resp.read().decode("utf-8")[:500]}
    except Exception as e:
        return {"reload_status": "skipped", "reload_error": f"{type(e).__name__}: {e}"}


# ─── add-plan ──────────────────────────────────────────

def cmd_add_plan(args):
    payload = _load_json_file(Path(args.file))

    # 收集现有预案标题
    existing_titles = set()
    if PLANS_DIR.exists():
        for p in PLANS_DIR.glob("*.json"):
            try:
                with open(p, encoding="utf-8") as f:
                    d = json.load(f)
                t = (d.get("封面") or {}).get("标题")
                if t:
                    existing_titles.add(t.strip())
            except Exception:
                continue

    ok, errors = validate_plan(payload, existing_titles if not args.overwrite else set())
    if not ok:
        print(format_errors("预案", errors), file=sys.stderr)
        sys.exit(1)

    # 写入：文件名取 封面.标题（清理特殊字符）+ .json
    title = payload["封面"]["标题"].strip()
    safe_name = title.replace("/", "_").replace("\\", "_") + ".json"
    target = PLANS_DIR / safe_name
    PLANS_DIR.mkdir(parents=True, exist_ok=True)

    if target.exists() and not args.overwrite:
        # 防止文件名冲突（标题不同但文件名冲突的罕见场景）
        target = PLANS_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_name}"

    with open(target, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    result = {
        "status": "success",
        "action": "add-plan",
        "saved_file": str(target.relative_to(PLANS_DIR.parent.parent)),
        "plan_title": title,
        "tip": "如该预案要绑定特定 scene，请编辑 data/预案/plan_index.json 的 scene_plans 加一条 preferred_plan_name 路由",
    }
    if args.reload:
        result.update(_try_reload_plans())
    emit(result)


# ─── add-expert ────────────────────────────────────────

def _migrate_xls_to_json_if_needed() -> List[Dict[str, Any]]:
    """首次执行 add-expert 时，自动把 xls 转 expert_info.json。返回当前 records。"""
    if EXPERT_JSON_PATH.exists():
        with open(EXPERT_JSON_PATH, encoding="utf-8") as f:
            return json.load(f)

    if not EXPERT_XLS_PATH.exists():
        return []

    try:
        import xlrd
    except ImportError:
        print("错误：首次需要将 xls 转 json，但缺少 xlrd（pip install xlrd==2.0.2）", file=sys.stderr)
        sys.exit(2)

    print(f"🔄 首次录入：把 {EXPERT_XLS_PATH.name} 迁移到 {EXPERT_JSON_PATH.name}（原 xls 保留为备份）", file=sys.stderr)
    book = xlrd.open_workbook(str(EXPERT_XLS_PATH))
    sheet = book.sheet_by_index(0)
    headers = [str(h).strip() for h in sheet.row_values(0)]
    records = []
    for r in range(1, sheet.nrows):
        row = sheet.row_values(r)
        rec = {}
        for k, v in zip(headers, row):
            # xlrd float 转 str，避免出现 "13800000000.0" 这种
            if isinstance(v, float) and v.is_integer():
                v = int(v)
            rec[k] = v
        records.append(rec)

    EXPERT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(EXPERT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    return records


def cmd_add_expert(args):
    payload = _load_json_file(Path(args.file))
    records = _migrate_xls_to_json_if_needed()

    existing_ids = {str(r.get("id") or "").strip() for r in records if r.get("id")}
    ok, errors = validate_expert(payload, existing_ids)
    if not ok:
        print(format_errors("专家", errors), file=sys.stderr)
        sys.exit(1)

    # 自动生成 id（如未提供）
    if not str(payload.get("id") or "").strip():
        payload["id"] = uuid.uuid4().hex

    # 加默认审计字段
    now_iso = datetime.now().isoformat(timespec="seconds")
    payload.setdefault("create_time", now_iso)
    payload.setdefault("update_time", now_iso)
    payload.setdefault("create_by", "admin_script")
    payload.setdefault("update_by", "admin_script")
    payload.setdefault("del_flag", 0)
    payload.setdefault("verification_state", 1)
    payload.setdefault("on_duty_status", 0)

    records.append(payload)
    with open(EXPERT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    emit({
        "status": "success",
        "action": "add-expert",
        "expert_id": payload["id"],
        "name": payload.get("name"),
        "total_experts_after": len(records),
        "saved_file": str(EXPERT_JSON_PATH),
    })


# ─── add-warehouse ────────────────────────────────────

def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def cmd_add_warehouse(args):
    payload = _load_json_file(Path(args.file))
    records = _load_jsonl(WAREHOUSE_JSONL_PATH)
    existing_ids = {str(r.get("warehouse_id") or "").strip() for r in records if r.get("warehouse_id")}

    ok, errors = validate_warehouse(payload, existing_ids)
    if not ok:
        print(format_errors("仓库", errors), file=sys.stderr)
        sys.exit(1)

    if not str(payload.get("warehouse_id") or "").strip():
        payload["warehouse_id"] = uuid.uuid4().hex

    payload.setdefault("verification_state", 1)
    payload.setdefault("last_verified_at", datetime.now().strftime("%Y-%m-%d"))
    payload.setdefault("material_item_count", sum(
        len(v) for v in (payload.get("materials_by_category") or {}).values()
        if isinstance(v, list)
    ))
    payload.setdefault("material_kind_count", payload["material_item_count"])

    _append_jsonl(WAREHOUSE_JSONL_PATH, payload)

    emit({
        "status": "success",
        "action": "add-warehouse",
        "warehouse_id": payload["warehouse_id"],
        "warehouse_name": payload.get("warehouse_name"),
        "total_warehouses_after": len(records) + 1,
        "saved_file": str(WAREHOUSE_JSONL_PATH),
    })


# ─── add-team ──────────────────────────────────────────

def cmd_add_team(args):
    payload = _load_json_file(Path(args.file))
    records = _load_jsonl(TEAM_JSONL_PATH)
    existing_ids = {str(r.get("team_id") or "").strip() for r in records if r.get("team_id")}

    ok, errors = validate_team(payload, existing_ids)
    if not ok:
        print(format_errors("救援队", errors), file=sys.stderr)
        sys.exit(1)

    if not str(payload.get("team_id") or "").strip():
        payload["team_id"] = uuid.uuid4().hex

    payload.setdefault("verification_state", 1)
    payload.setdefault("last_verified_at", datetime.now().strftime("%Y-%m-%d"))
    payload.setdefault("status", 1)
    payload.setdefault("categories", [])
    payload.setdefault("material_item_count", 0)
    payload.setdefault("material_kind_count", 0)
    payload.setdefault("materials_by_category", {})

    _append_jsonl(TEAM_JSONL_PATH, payload)

    emit({
        "status": "success",
        "action": "add-team",
        "team_id": payload["team_id"],
        "team_name": payload.get("team_name"),
        "total_teams_after": len(records) + 1,
        "saved_file": str(TEAM_JSONL_PATH),
    })


# ─── main ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="录入新预案/专家/仓库/救援队到本地知识库",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="录入格式参考 scripts/examples/ 下的样例 JSON",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("add-plan", help="录入新预案（parsered_data 风格 JSON）")
    p1.add_argument("--file", required=True, help="预案 JSON 文件路径")
    p1.add_argument("--overwrite", action="store_true", help="同标题预案已存在时是否覆盖")
    p1.add_argument("--reload", action="store_true", help="录入后调 /api/v1/plans/reload 热加载")

    p2 = sub.add_parser("add-expert", help="录入新专家（首次执行会把 xls 迁移到 json）")
    p2.add_argument("--file", required=True, help="专家 JSON 文件路径")
    p2.add_argument("--reload", action="store_true", help="录入后调 /api/v1/plans/reload（专家库本身不依赖此接口，仅为统一选项）")

    p3 = sub.add_parser("add-warehouse", help="录入新仓库（预聚合 JSON 格式）")
    p3.add_argument("--file", required=True, help="仓库 JSON 文件路径")
    p3.add_argument("--reload", action="store_true")

    p4 = sub.add_parser("add-team", help="录入新救援队（预聚合 JSON 格式）")
    p4.add_argument("--file", required=True, help="救援队 JSON 文件路径")
    p4.add_argument("--reload", action="store_true")

    args = parser.parse_args()
    {
        "add-plan": cmd_add_plan,
        "add-expert": cmd_add_expert,
        "add-warehouse": cmd_add_warehouse,
        "add-team": cmd_add_team,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
