"""HTTP API 路由定义。"""

from __future__ import annotations

import asyncio
import logging
import platform
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

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


# ── 路由 ──────────────────────────────────────────────────

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
