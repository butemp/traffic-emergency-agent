"""HTTP API Pydantic 请求/响应模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── 请求模型 ──────────────────────────────────────────────

class TaskCreateRequest(BaseModel):
    """创建任务的请求体。"""

    incident_description: str = Field(
        ...,
        min_length=1,
        description="事件描述，例如 'G72高速K85处三车追尾，2人受伤'",
    )
    incident_info: Optional[Dict[str, Any]] = Field(
        default=None,
        description="可选的预填充灾情结构化信息（location_text, incident_type 等）",
    )
    media_urls: Optional[List[str]] = Field(
        default=None,
        description="可选的现场图片/视频 URL 列表",
    )
    config: Optional[Dict[str, str]] = Field(
        default=None,
        description="可选的模型配置覆盖（OPENAI_API_KEY, OPENAI_MODEL 等）",
    )


# ── 进度 / 结果 / 错误子模型 ─────────────────────────────

class TaskProgress(BaseModel):
    """任务实时进度。"""

    phase: str = ""
    iteration: int = 0
    tools_called: List[str] = Field(default_factory=list)
    current_action: str = ""
    pipeline_status: str = ""


class TaskResult(BaseModel):
    """任务最终结果。"""

    plan_markdown: str = ""
    sections: Dict[str, str] = Field(default_factory=dict)
    structured_sections: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="按固定字段输出的结构化章节，便于 API 调用方直接读取",
    )
    review: Optional[Dict[str, Any]] = None


class ProcessData(BaseModel):
    """任务过程中收集的中间数据。"""

    incident_info: Optional[Dict[str, Any]] = None
    environment: Optional[Dict[str, Any]] = None
    resources: Optional[List[Dict[str, Any]]] = None
    experts: Optional[List[Dict[str, Any]]] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    risk_assessment: Optional[List[Dict[str, Any]]] = None
    knowledge_refs: Optional[List[Dict[str, Any]]] = None


class TaskError(BaseModel):
    """任务错误信息。"""

    code: str = ""
    message: str = ""
    phase: str = ""
    iteration: int = 0


# ── 响应模型 ──────────────────────────────────────────────

class TaskCreateResponse(BaseModel):
    """创建任务的响应。"""

    task_id: str
    status: str
    created_at: datetime


class TaskStatusResponse(BaseModel):
    """查询任务状态的响应。"""

    task_id: str
    status: str
    progress: TaskProgress = Field(default_factory=TaskProgress)
    result: Optional[TaskResult] = None
    process_data: Optional[ProcessData] = None
    error: Optional[TaskError] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class TaskSummary(BaseModel):
    """任务列表中的摘要项。"""

    task_id: str
    status: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    incident_description: str = ""


class TaskListResponse(BaseModel):
    """任务列表响应。"""

    total: int
    tasks: List[TaskSummary]
