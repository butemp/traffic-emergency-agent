"""HTTP API 路由定义。"""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel, Field

from .models import (
    TaskCreateRequest,
    TaskCreateResponse,
    TaskError,
    TaskListResponse,
    TaskProgress,
    TaskResult,
    TaskStatusResponse,
    TaskSummary,
    ProcessData,
)
from .task_runner import run_task
from .task_store import TaskStore
from src.utils.structured_sections import normalize_structured_sections
from src.tools.get_emergency_plan import get_shared_plan_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["tasks"])
store = TaskStore(max_tasks=100)


def _build_status_response(record) -> TaskStatusResponse:
    """将 TaskRecord 转换为 API 响应模型。"""
    progress = TaskProgress(**record.progress) if record.progress else TaskProgress()

    result = None
    if record.result:
        result = TaskResult(
            plan_markdown=record.result.get("plan_markdown", ""),
            sections=record.result.get("sections", {}),
            structured_sections=normalize_structured_sections(record.result.get("structured_sections", {})),
            review=record.result.get("review"),
        )

    process_data = None
    if record.process_data:
        process_data = ProcessData(**record.process_data)

    error = None
    if record.error:
        error = TaskError(**record.error)

    return TaskStatusResponse(
        task_id=record.task_id,
        status=record.status,
        progress=progress,
        result=result,
        process_data=process_data,
        error=error,
        created_at=record.created_at,
        completed_at=record.completed_at,
    )


# ─── 任务路由 ─────────────────────────────────────────────

@router.post("/tasks", response_model=TaskCreateResponse, status_code=201)
async def create_task(request: TaskCreateRequest):
    """创建一个异步方案生成任务。"""
    record = store.create(request.model_dump())
    asyncio.create_task(run_task(record.task_id, store))
    logger.info("API 任务已创建并启动: task_id=%s", record.task_id)
    return TaskCreateResponse(
        task_id=record.task_id,
        status=record.status,
        created_at=record.created_at,
    )


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task(task_id: str):
    """查询任务状态。"""
    record = store.get(task_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    return _build_status_response(record)


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(
    status: Optional[str] = Query(default=None, description="按状态过滤: pending/running/completed/failed/cancelled"),
    limit: int = Query(default=20, ge=1, le=100, description="每页数量"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
):
    """列出任务。"""
    total, records = store.list(status=status, limit=limit, offset=offset)
    tasks = [
        TaskSummary(
            task_id=r.task_id,
            status=r.status,
            created_at=r.created_at,
            completed_at=r.completed_at,
            incident_description=r.request.get("incident_description", ""),
        )
        for r in records
    ]
    return TaskListResponse(total=total, tasks=tasks)


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    """取消/删除任务。"""
    record = store.get(task_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    record.cancel_event.set()
    store.delete(task_id)
    return {"task_id": task_id, "status": "cancelled"}


@router.get("/health")
async def health():
    """健康检查。"""
    total, _ = store.list()
    _, running = store.list(status="running")
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "python_version": platform.python_version(),
        "tasks_total": total,
        "tasks_running": len(running),
    }


# ─────────────────────────────────────────────────────────
# 应急预案管理接口
# ─────────────────────────────────────────────────────────

class PlanInfo(BaseModel):
    """单份预案的元信息。"""
    title: str = Field(..., description="预案标题（取自 封面.标题）")
    file: str = Field(..., description="文件名")
    publisher: str = Field("", description="发布单位")
    publish_time: str = Field("", description="发布时间")
    top_level_keys: list[str] = Field(default_factory=list, description="顶层章节 keys")
    routed_scenes: list[str] = Field(default_factory=list, description="该预案被哪些 scene 路由到")


class PlanListResponse(BaseModel):
    """预案列表响应。"""
    total: int
    plans: list[PlanInfo]
    fallback_plan_name: str = ""
    plans_dir: str = ""


class PlanUploadResponse(BaseModel):
    """预案上传响应。"""
    status: str
    message: str
    saved_file: str = ""
    plan_title: str = ""
    routed_to_scene: str = ""
    reload_summary: Dict[str, Any] = Field(default_factory=dict)


def _safe_filename(name: str) -> str:
    """清理文件名防路径穿越，保留中文。"""
    cleaned = re.sub(r"[\\/\x00]", "_", name).strip()
    cleaned = cleaned.lstrip(".")
    return cleaned or "unnamed.json"


def _scene_routing_for_plan(plan_title: str, index: Dict[str, Any]) -> list[str]:
    """找出哪些 scene 把这份预案当 preferred。"""
    scene_plans = index.get("scene_plans", {}) or {}
    return [
        scene for scene, entry in scene_plans.items()
        if entry.get("preferred_plan_name") == plan_title
    ]


@router.get("/plans", response_model=PlanListResponse, tags=["plans"])
async def list_plans():
    """列出当前服务已加载的所有应急预案。"""
    svc = get_shared_plan_service()
    plans_meta = svc.list_plans()
    index = svc.index or {}

    plans = [
        PlanInfo(
            title=p["title"],
            file=p["file"],
            publisher=p.get("publisher", ""),
            publish_time=p.get("publish_time", ""),
            top_level_keys=p.get("top_level_keys", []),
            routed_scenes=_scene_routing_for_plan(p["title"], index),
        )
        for p in plans_meta
    ]

    return PlanListResponse(
        total=len(plans),
        plans=plans,
        fallback_plan_name=index.get("fallback_plan_name", ""),
        plans_dir=str(svc.plans_dir),
    )


@router.post("/plans", response_model=PlanUploadResponse, status_code=201, tags=["plans"])
async def upload_plan(
    file: UploadFile = File(..., description="预案 JSON 文件，必须含 封面.标题 字段"),
    scene: Optional[str] = Form(default=None, description="（可选）把该预案路由到指定 scene，如 EXPRESSWAY/HIGHWAY/CONSTRUCTION 等；不填只保存不路由"),
    fallback_to: Optional[str] = Form(default="GENERAL", description="（可选）当 scene 找不到时的回退 scene，默认 GENERAL"),
    overwrite: bool = Form(default=False, description="目录中同名文件是否覆盖"),
):
    """上传一份新预案 JSON 并热加载。

    流程：
    1. 校验上传内容是合法 JSON 且含 封面.标题
    2. 保存到 data/预案/parsered_data/<filename>
    3. （可选）在 plan_index.json 的 scene_plans 加一条路由
    4. 调用 service.reload() 让运行中的服务立即看到新预案
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="未提供文件名")

    # 1. 读取 + 解析 JSON
    raw = await file.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="文件不是有效的 UTF-8 编码")
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"文件不是合法 JSON: {e.msg} (line {e.lineno})")

    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="JSON 根节点必须是对象（dict），不能是数组或基础类型")

    cover = data.get("封面")
    if not isinstance(cover, dict) or not cover.get("标题"):
        raise HTTPException(
            status_code=400,
            detail="JSON 必须含 封面.标题 字段（service 按此字段做路由）",
        )

    plan_title = str(cover.get("标题")).strip()
    if not plan_title:
        raise HTTPException(status_code=400, detail="封面.标题 不能为空")

    # 2. 写入文件
    svc = get_shared_plan_service()
    target_dir: Path = svc.plans_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    safe_name = _safe_filename(file.filename)
    if not safe_name.endswith(".json"):
        safe_name = f"{safe_name}.json"
    target_path = target_dir / safe_name

    if target_path.exists() and not overwrite:
        raise HTTPException(
            status_code=409,
            detail=f"文件已存在: {safe_name}。如需覆盖请传 overwrite=true",
        )

    try:
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("预案 JSON 已保存: %s (title=%s)", target_path, plan_title)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入文件失败: {e}")

    # 3. （可选）在 plan_index.json 加路由
    routed_to = ""
    if scene:
        scene_upper = scene.strip().upper()
        try:
            with open(svc.index_path, "r", encoding="utf-8") as f:
                index_data = json.load(f)

            scene_plans = index_data.setdefault("scene_plans", {})
            scene_plans[scene_upper] = {
                "preferred_plan_name": plan_title,
                "description": f"上传时间 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 自动注册",
                "fallback_to": fallback_to or None,
            }

            with open(svc.index_path, "w", encoding="utf-8") as f:
                json.dump(index_data, f, ensure_ascii=False, indent=2)
            routed_to = scene_upper
            logger.info("plan_index.json 已加路由: %s → %s (fallback_to=%s)", scene_upper, plan_title, fallback_to)
        except Exception as e:
            logger.warning("写 plan_index.json 失败（预案文件已保存，但路由未生效）: %s", e)

    # 4. 热加载服务实例
    try:
        reload_summary = svc.reload()
        logger.info("EmergencyPlanService.reload 完成: %s", reload_summary)
    except Exception as e:
        logger.warning("reload 失败（文件已保存，下次新任务会自动加载）: %s", e)
        reload_summary = {"error": str(e)}

    return PlanUploadResponse(
        status="success",
        message=f"预案 '{plan_title}' 已上传并热加载",
        saved_file=safe_name,
        plan_title=plan_title,
        routed_to_scene=routed_to,
        reload_summary=reload_summary,
    )


@router.post("/plans/reload", tags=["plans"])
async def reload_plans():
    """手动触发预案热重载（不上传新文件，只重新扫盘）。"""
    svc = get_shared_plan_service()
    try:
        summary = svc.reload()
        return {"status": "success", "summary": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"reload 失败: {e}")
