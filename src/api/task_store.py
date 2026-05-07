"""进程内任务存储。"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TaskRecord:
    """单个 API 任务的完整状态记录。"""

    task_id: str
    status: str  # pending / running / completed / failed / cancelled
    created_at: datetime
    completed_at: Optional[datetime] = None
    request: Dict[str, Any] = field(default_factory=dict)
    progress: Dict[str, Any] = field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    process_data: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    agent: Any = None  # Agent 实例引用（不序列化）
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)


class TaskStore:
    """线程安全的进程内任务存储。"""

    def __init__(self, max_tasks: int = 100) -> None:
        self._tasks: Dict[str, TaskRecord] = {}
        self._max_tasks = max_tasks

    def create(self, request: Dict[str, Any]) -> TaskRecord:
        """创建一个新任务，返回 TaskRecord。"""
        if len(self._tasks) >= self._max_tasks:
            self._evict_oldest_completed()

        task_id = uuid.uuid4().hex[:12]
        record = TaskRecord(
            task_id=task_id,
            status="pending",
            created_at=datetime.now(),
            request=request,
            progress={
                "phase": "",
                "iteration": 0,
                "tools_called": [],
                "current_action": "等待启动",
                "pipeline_status": "",
            },
        )
        self._tasks[task_id] = record
        logger.info("任务已创建: task_id=%s", task_id)
        return record

    def get(self, task_id: str) -> Optional[TaskRecord]:
        return self._tasks.get(task_id)

    def list(
        self,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[int, List[TaskRecord]]:
        """列出任务，支持按状态过滤和分页。"""
        records = list(self._tasks.values())
        if status:
            records = [r for r in records if r.status == status]
        total = len(records)
        records.sort(key=lambda r: r.created_at, reverse=True)
        return total, records[offset : offset + limit]

    def update_progress(self, task_id: str, **kwargs: Any) -> None:
        record = self._tasks.get(task_id)
        if not record:
            return
        if "status" in kwargs:
            record.status = kwargs.pop("status")
        record.progress.update(kwargs)

    def complete(
        self,
        task_id: str,
        result: Dict[str, Any],
        process_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        record = self._tasks.get(task_id)
        if not record:
            return
        record.status = "completed"
        record.completed_at = datetime.now()
        record.result = result
        record.process_data = process_data
        record.agent = None  # 释放 Agent 引用
        logger.info("任务已完成: task_id=%s", task_id)

    def fail(self, task_id: str, error: Dict[str, Any]) -> None:
        record = self._tasks.get(task_id)
        if not record:
            return
        record.status = "failed"
        record.completed_at = datetime.now()
        record.error = error
        record.agent = None
        logger.warning("任务失败: task_id=%s, error=%s", task_id, error)

    def delete(self, task_id: str) -> bool:
        record = self._tasks.get(task_id)
        if not record:
            return False
        record.status = "cancelled"
        record.completed_at = datetime.now()
        record.agent = None
        logger.info("任务已取消: task_id=%s", task_id)
        return True

    def _evict_oldest_completed(self) -> None:
        """淘汰最旧的已完成/失败/取消任务以腾出空间。"""
        terminal = [
            r for r in self._tasks.values()
            if r.status in ("completed", "failed", "cancelled")
        ]
        if not terminal:
            return
        terminal.sort(key=lambda r: r.created_at)
        victim = terminal[0]
        del self._tasks[victim.task_id]
        logger.info("淘汰旧任务: task_id=%s", victim.task_id)
