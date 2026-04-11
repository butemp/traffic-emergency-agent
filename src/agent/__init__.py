"""
交通应急Agent核心模块

本模块实现Agent的核心逻辑，包括消息处理、工具调用、对话管理等。
"""

from .message import Message, MessageRole, ToolCall
from .skill_router import SkillRouter
from .state import ConversationState
from .task_state import (
    AssistantControl,
    CandidatePlan,
    EnvironmentInfo,
    EvaluationResult,
    IncidentInfo,
    KnowledgeReference,
    PendingQuestion,
    TaskPhase,
    TaskState,
    ToolExecutionRecord,
)

__all__ = [
    "Agent",
    "Message",
    "MessageRole",
    "ToolCall",
    "ConversationState",
    "SkillRouter",
    "TaskPhase",
    "TaskState",
    "AssistantControl",
    "IncidentInfo",
    "EnvironmentInfo",
    "KnowledgeReference",
    "CandidatePlan",
    "EvaluationResult",
    "PendingQuestion",
    "ToolExecutionRecord",
]


def __getattr__(name):
    """延迟导入重依赖模块，避免基础状态模型被无关依赖阻塞。"""
    if name == "Agent":
        from .agent import Agent
        return Agent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
