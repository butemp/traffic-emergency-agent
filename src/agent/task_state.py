"""
任务状态机数据模型。

该模块为新的 Skill-Based Agent 架构提供统一的状态容器。
当前阶段先落基础数据结构和少量辅助方法，方便后续逐步改造
Agent 主循环和前端交互逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from .message import Message


class TaskPhase(str, Enum):
    """任务阶段枚举。"""

    INTAKE = "INTAKE"
    SITUATIONAL_AWARENESS = "SITUATIONAL_AWARENESS"
    PLAN_GENERATION = "PLAN_GENERATION"
    PLAN_EVALUATION = "PLAN_EVALUATION"
    OUTPUT = "OUTPUT"
    WAITING_USER = "WAITING_USER"
    OUTPUT_COMPLETE = "OUTPUT_COMPLETE"


@dataclass
class IncidentInfo:
    """
    结构化灾情信息。

    这是后续主流程 Skill 在 INTAKE 阶段要持续补全的核心对象。
    """

    incident_type: str = ""
    severity: str = ""
    location_text: str = ""
    location_coords: Optional[Dict[str, float]] = None
    time_text: str = ""
    casualty_status: str = ""
    casualties: Dict[str, Any] = field(default_factory=dict)
    scene_status: str = ""
    hazmat_involved: Optional[bool] = None
    hazmat_type: str = ""
    road_info: str = ""
    vehicles_involved: str = ""
    additional_context: str = ""

    def missing_required_fields(self) -> List[str]:
        """返回当前仍缺失的必填字段。"""
        missing: List[str] = []

        if not self.incident_type:
            missing.append("incident_type")
        if not self.location_text and not self.location_coords:
            missing.append("location")
        if not self.casualty_status and not self.casualties:
            missing.append("casualties")
        if not self.scene_status:
            missing.append("scene_status")

        return missing

    def is_complete(self) -> bool:
        """判断 Intake 阶段的最小必要信息是否齐备。"""
        return not self.missing_required_fields()


@dataclass
class EnvironmentInfo:
    """现场环境与上下文信息。"""

    formatted_address: str = ""
    weather: Dict[str, Any] = field(default_factory=dict)
    traffic: Dict[str, Any] = field(default_factory=dict)
    media_summary: Dict[str, Any] = field(default_factory=dict)
    nearby_pois: List[Dict[str, Any]] = field(default_factory=list)
    additional_notes: List[str] = field(default_factory=list)


@dataclass
class KnowledgeReference:
    """法规、预案、案例等知识引用。"""

    source_type: str
    title: str = ""
    excerpt: str = ""
    source_path: str = ""
    score: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CandidatePlan:
    """候选方案。"""

    plan_id: str
    title: str
    summary: str
    content: str
    advantages: List[str] = field(default_factory=list)
    disadvantages: List[str] = field(default_factory=list)
    applicable_scenarios: List[str] = field(default_factory=list)
    selected: bool = False


@dataclass
class EvaluationResult:
    """方案评估结果。"""

    plan_id: str = ""
    overall_score: Optional[float] = None
    risk_level: str = ""
    summary: str = ""
    suggestions: List[str] = field(default_factory=list)
    raw_result: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PendingQuestion:
    """等待用户回复的问题。"""

    question: str
    reason: str = ""
    expected_fields: List[str] = field(default_factory=list)
    suggested_options: List[str] = field(default_factory=list)
    question_type: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    return_phase: Optional[TaskPhase] = None
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class ToolExecutionRecord:
    """工具调用记录。"""

    tool_name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    success: bool = True
    result_preview: str = ""
    error_message: str = ""
    called_at: datetime = field(default_factory=datetime.now)


@dataclass
class AssistantControl:
    """
    模型返回的结构化控制信息。

    该对象用于承接主流程 Skill 的阶段推进指令。
    """

    next_phase: Optional[TaskPhase] = None
    needs_user_input: bool = False
    user_prompt: str = ""
    final_output: bool = False
    phase_reason: str = ""
    incident_updates: Dict[str, Any] = field(default_factory=dict)
    environment_updates: Dict[str, Any] = field(default_factory=dict)
    candidate_plans: List[Dict[str, Any]] = field(default_factory=list)
    selected_plan_id: str = ""
    awaiting_confirmation: bool = False
    raw_payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskState:
    """
    任务状态对象。

    该对象是新架构中的中心状态容器。当前版本先负责：
    1. 记录当前阶段
    2. 保存结构化灾情与环境信息
    3. 保存资源、知识、方案、评估与待确认问题
    4. 保存会话历史和工具调用日志
    """

    current_phase: TaskPhase = TaskPhase.INTAKE
    incident_info: IncidentInfo = field(default_factory=IncidentInfo)
    environment_info: EnvironmentInfo = field(default_factory=EnvironmentInfo)
    available_resources: List[Dict[str, Any]] = field(default_factory=list)
    knowledge_refs: List[KnowledgeReference] = field(default_factory=list)
    candidate_plans: List[CandidatePlan] = field(default_factory=list)
    evaluation_results: List[EvaluationResult] = field(default_factory=list)
    pending_question: Optional[PendingQuestion] = None
    conversation_history: List[Message] = field(default_factory=list)
    tool_call_log: List[ToolExecutionRecord] = field(default_factory=list)
    phase_history: List[TaskPhase] = field(default_factory=lambda: [TaskPhase.INTAKE])

    def transition_to(self, next_phase: TaskPhase) -> None:
        """切换到下一个任务阶段。"""
        if self.current_phase == next_phase:
            return
        self.current_phase = next_phase
        self.phase_history.append(next_phase)

    def append_message(self, message: Message) -> None:
        """记录一条会话消息。"""
        self.conversation_history.append(message)

    def record_tool_call(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        result: str = "",
        success: bool = True,
        error_message: str = "",
    ) -> None:
        """追加工具调用记录。"""
        preview = result[:300]
        self.tool_call_log.append(
            ToolExecutionRecord(
                tool_name=tool_name,
                arguments=arguments or {},
                success=success,
                result_preview=preview,
                error_message=error_message,
            )
        )

    def set_pending_question(
        self,
        question: str,
        reason: str = "",
        expected_fields: Optional[List[str]] = None,
        suggested_options: Optional[List[str]] = None,
        question_type: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        return_phase: Optional[TaskPhase] = None,
    ) -> None:
        """设置当前等待用户回答的问题。"""
        self.pending_question = PendingQuestion(
            question=question,
            reason=reason,
            expected_fields=expected_fields or [],
            suggested_options=suggested_options or [],
            question_type=question_type,
            metadata=metadata or {},
            return_phase=return_phase,
        )
        self.transition_to(TaskPhase.WAITING_USER)

    def clear_pending_question(self) -> None:
        """清空待回答问题。"""
        self.pending_question = None

    def resume_from_waiting(self) -> None:
        """从 WAITING_USER 恢复到原阶段。"""
        if not self.pending_question:
            return

        return_phase = self.pending_question.return_phase or TaskPhase.INTAKE
        self.pending_question = None
        self.transition_to(return_phase)

    def add_knowledge_reference(self, reference: KnowledgeReference) -> None:
        """追加一条知识引用。"""
        self.knowledge_refs.append(reference)

    def add_candidate_plan(self, plan: CandidatePlan) -> None:
        """追加候选方案。"""
        self.candidate_plans.append(plan)

    def add_evaluation_result(self, result: EvaluationResult) -> None:
        """追加方案评估结果。"""
        self.evaluation_results.append(result)

    def apply_incident_updates(self, updates: Dict[str, Any]) -> None:
        """将结构化字段更新到 IncidentInfo。"""
        if not updates:
            return

        direct_fields = {
            "incident_type",
            "severity",
            "location_text",
            "time_text",
            "casualty_status",
            "scene_status",
            "hazmat_involved",
            "hazmat_type",
            "road_info",
            "vehicles_involved",
            "additional_context",
        }

        for key, value in updates.items():
            if value in (None, "", []):
                continue

            if key == "location_coords" and isinstance(value, dict):
                self.incident_info.location_coords = value
            elif key == "casualties" and isinstance(value, dict):
                self.incident_info.casualties.update(value)
            elif key in direct_fields:
                setattr(self.incident_info, key, value)

    def apply_environment_updates(self, updates: Dict[str, Any]) -> None:
        """将环境字段更新到 EnvironmentInfo。"""
        if not updates:
            return

        if "formatted_address" in updates and updates["formatted_address"]:
            self.environment_info.formatted_address = updates["formatted_address"]

        if "weather" in updates and isinstance(updates["weather"], dict):
            self.environment_info.weather.update(updates["weather"])

        if "traffic" in updates and isinstance(updates["traffic"], dict):
            self.environment_info.traffic.update(updates["traffic"])

        if "media_summary" in updates and isinstance(updates["media_summary"], dict):
            self.environment_info.media_summary.update(updates["media_summary"])

        if "nearby_pois" in updates and isinstance(updates["nearby_pois"], list):
            self.environment_info.nearby_pois = updates["nearby_pois"]

        if "additional_notes" in updates and isinstance(updates["additional_notes"], list):
            self.environment_info.additional_notes.extend(updates["additional_notes"])

    def intake_is_complete(self) -> bool:
        """判断灾情接收阶段的最小信息是否已经齐备。"""
        return self.incident_info.is_complete()

    def build_context_summary(self) -> str:
        """
        生成简洁的任务上下文摘要。

        这个摘要后续可以直接注入 system prompt，也方便调试阶段观察状态。
        """
        missing_fields = self.incident_info.missing_required_fields()
        pending_question = self.pending_question.question if self.pending_question else "无"
        candidate_plan_titles = [plan.title for plan in self.candidate_plans[:3]]
        selected_plan = next((plan.title for plan in self.candidate_plans if plan.selected), "无")

        return (
            f"当前阶段: {self.current_phase.value}\n"
            f"事件类型: {self.incident_info.incident_type or '未知'}\n"
            f"严重程度: {self.incident_info.severity or '未知'}\n"
            f"位置描述: {self.incident_info.location_text or '未知'}\n"
            f"坐标: {self.incident_info.location_coords or '未知'}\n"
            f"伤亡情况: {self.incident_info.casualty_status or self.incident_info.casualties or '未知'}\n"
            f"现场状态: {self.incident_info.scene_status or '未知'}\n"
            f"缺失字段: {missing_fields or '无'}\n"
            f"已检索资源数: {len(self.available_resources)}\n"
            f"已记录知识引用数: {len(self.knowledge_refs)}\n"
            f"候选方案数: {len(self.candidate_plans)}\n"
            f"候选方案标题: {candidate_plan_titles or '无'}\n"
            f"当前选中方案: {selected_plan}\n"
            f"评估结果数: {len(self.evaluation_results)}\n"
            f"待用户回复问题: {pending_question}"
        )
