#!/usr/bin/env python3
"""查询本地预案库（命令行 CLI，输出 UTF-8 JSON 到 stdout）。

复用 src.emergency_plans.EmergencyPlanService，与主项目 API 路由/Agent 工具共享同一份数据视图。

子命令：
  list                              列出全部已加载预案（标题/文件/发布单位/发布时间/被哪些 scene 路由到）
  scenes                            列出全部 scene 路由（含 fallback 链、是否命中专项预案）
  get --title <标题> | --scene <X>   按预案标题或 scene 取一份预案的元信息
  toc --scene <X> [--depth N]        看某 scene 对应预案的章节结构树（默认 depth=3）
  show --scene <X> --module <Y>     按模块别名取预案章节内容（如 grading_criteria/response_measures）
  show --scene <X> --section <Y>    按中文章节路径取（如 '应急响应.处置措施.Ⅱ级应急响应处置措施'，末尾支持 *）
  show --scene <X> --search <Y>     在预案全文搜关键词

示例：
  python3 scripts/query_plans.py list
  python3 scripts/query_plans.py scenes
  python3 scripts/query_plans.py toc --scene EXPRESSWAY --depth 2
  python3 scripts/query_plans.py show --scene EXPRESSWAY --module grading_criteria
  python3 scripts/query_plans.py show --scene CONSTRUCTION --section "组织体系.自治区应急指挥机构.应急工作组"
  python3 scripts/query_plans.py show --scene CONSTRUCTION --search "抚恤"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.emergency_plans import EmergencyPlanService


def emit(obj):
    """统一输出 UTF-8 JSON 到 stdout。"""
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def _scenes_for_plan(svc: EmergencyPlanService, plan_title: str) -> list[str]:
    scene_plans = (svc.index or {}).get("scene_plans", {}) or {}
    return [
        s for s, e in scene_plans.items()
        if e.get("preferred_plan_name") == plan_title
    ]


def cmd_list(svc: EmergencyPlanService, args):
    plans = svc.list_plans()
    out = {
        "total": len(plans),
        "plans": [
            {
                **p,
                "routed_scenes": _scenes_for_plan(svc, p["title"]),
            }
            for p in plans
        ],
        "plans_dir": str(svc.plans_dir),
        "index_path": str(svc.index_path),
    }
    emit(out)


def cmd_scenes(svc: EmergencyPlanService, args):
    emit({
        "scenes": svc.list_scenes(),
        "fallback_plan_name": (svc.index or {}).get("fallback_plan_name", ""),
        "disaster_supplementary_plans": (svc.index or {}).get("disaster_supplementary_plans", {}),
    })


def cmd_get(svc: EmergencyPlanService, args):
    if not args.title and not args.scene:
        print("错误：--title 或 --scene 至少传一个", file=sys.stderr)
        sys.exit(2)

    plan_meta = None
    chain: list[str] = []
    if args.title:
        plan_meta = svc.plans.get(args.title.strip())
    elif args.scene:
        plan_meta, chain, _ = svc.resolve_plan_for_scene(args.scene.strip())

    if not plan_meta:
        emit({
            "status": "not_found",
            "title": args.title,
            "scene": args.scene,
            "fallback_chain": chain,
        })
        sys.exit(1)

    emit({
        "status": "success",
        "title": plan_meta["title"],
        "file": plan_meta["file"],
        "publisher": plan_meta.get("publisher", ""),
        "publish_time": plan_meta.get("publish_time", ""),
        "top_level_keys": [k for k in plan_meta["content"].keys() if k != "目录"],
        "routed_scenes": _scenes_for_plan(svc, plan_meta["title"]),
        "fallback_chain": chain,
    })


def cmd_toc(svc: EmergencyPlanService, args):
    result = svc.get_toc(scene=args.scene or "", plan_name=args.title or "", depth=int(args.depth or 3))
    emit(result)


def cmd_show(svc: EmergencyPlanService, args):
    if not args.module and not args.section and not args.search:
        print("错误：--module / --section / --search 至少传一个", file=sys.stderr)
        sys.exit(2)

    result = svc.get_emergency_plan(
        incident_category=args.scene or "",
        module=args.module or "",
        section_path=args.section or "",
        search_keyword=args.search or "",
        disaster_type=args.disaster or "",
        level=args.level or "",
    )
    emit(result)


def main():
    parser = argparse.ArgumentParser(
        description="查询本地预案库（list / scenes / get / toc / show）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="列出全部已加载预案")
    sub.add_parser("scenes", help="列出全部 scene 路由")

    p_get = sub.add_parser("get", help="按预案标题或 scene 取一份预案元信息")
    p_get.add_argument("--title", help="预案的 封面.标题（与 --scene 二选一）")
    p_get.add_argument("--scene", help="场景类别编码（如 EXPRESSWAY/HIGHWAY/PORT 等）")

    p_toc = sub.add_parser("toc", help="看某预案的章节树")
    p_toc.add_argument("--scene", help="场景类别编码")
    p_toc.add_argument("--title", help="或直接指定预案标题")
    p_toc.add_argument("--depth", type=int, default=3, help="树深度，默认 3")

    p_show = sub.add_parser("show", help="取预案章节内容")
    p_show.add_argument("--scene", required=True, help="场景类别编码")
    p_show.add_argument("--module", help="模块别名（如 grading_criteria/response_measures/command_structure 等）")
    p_show.add_argument("--section", help="中文章节路径，'.' 分隔，末尾支持 *")
    p_show.add_argument("--search", help="在预案全文搜关键词")
    p_show.add_argument("--disaster", help="（可选）灾害类别 FLOOD/ICE_SNOW/EARTHQUAKE/PUBLIC_HEALTH/CYBER")
    p_show.add_argument("--level", help="（可选）响应级别 特别重大级/重大级/较大级/一般级")

    args = parser.parse_args()
    svc = EmergencyPlanService()

    {
        "list": cmd_list,
        "scenes": cmd_scenes,
        "get": cmd_get,
        "toc": cmd_toc,
        "show": cmd_show,
    }[args.cmd](svc, args)


if __name__ == "__main__":
    main()
