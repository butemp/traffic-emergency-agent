"""
Agent核心类

实现Agent的主逻辑，包括消息处理、工具调用、对话管理等。
"""

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from .message import Message, MessageRole, ToolCall
from .skill_router import SkillRouter
from .state import ConversationState
from .task_state import (
    AssistantControl,
    CandidatePlan,
    EvaluationResult,
    KnowledgeReference,
    TaskPhase,
    TaskState,
)
from ..providers import OpenAIProvider
from ..tools import BaseTool

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class Agent:
    """
    交通应急Agent

    核心功能：
    1. 维护对话状态和历史
    2. 调用LLM进行推理
    3. 处理工具调用
    4. 返回最终响应
    """

    # System Prompt：定义Agent的角色和行为
    SYSTEM_PROMPT = """你是一个交通应急指挥智能体，目标不是被动回答问题，而是主动推进一次完整的应急指挥任务。

你的总体职责：
1. 识别灾情并补全关键信息
2. 按当前阶段选择合适的能力和工具
3. 基于法规、案例、环境信息和资源情况生成方案
4. 在关键节点主动向用户补问、给选项或征求确认
5. 在完成评估后输出一份结构化的处置方案

工作原则：
- 你始终处于一个明确的任务阶段，必须围绕当前阶段目标行动
- 你只能使用“当前可用工具”部分列出的工具
- 可以在同一轮中调用多个当前阶段需要的工具，但不要无意义地滥用工具
- 所有事实判断必须优先基于工具结果，不要编造现场信息
- 如关键信息缺失，应主动向用户补问，而不是假设
- 如存在多个明显可行方案，应给用户清晰对比并请求选择
- 对于高风险或 critical 场景，可以先给默认方案，再征求确认

资源与知识规则：
- 法规、预案、技术指南优先使用 query_rag
- 历史经验补充使用 query_historical_cases
 - 内部资源调度优先使用 search_emergency_resources
 - 候选资源齐备后使用 optimize_dispatch_plan 生成分梯队调度方案
 - 公开设施仅在内部资源不足时使用 search_nearby_pois
- 风险评估阶段应调用 risk_assessment

输出要求：
- 调用工具前，说明你为什么需要该工具
- 工具返回后，先分析再决策下一步
- 如果进入最终输出阶段，方案应包含事件概述、处置步骤、资源调度、风险提示和依据引用
- 如果不是最终输出，而是阶段推进、补问或确认，必须简洁明确
"""

    CONTROL_BLOCK_TEMPLATE = """```agent_control
{
  "next_phase": "SITUATIONAL_AWARENESS",
  "needs_user_input": false,
  "user_prompt": "",
  "final_output": false,
  "phase_reason": "说明为何切换阶段",
  "incident_updates": {},
  "environment_updates": {},
  "candidate_plans": [],
  "selected_plan_id": "",
  "awaiting_confirmation": false
}
```"""

    def __init__(
        self,
        provider: OpenAIProvider,
        tools: List[BaseTool],
        max_iterations: int = 5,
        save_conversations: bool = True,
        conversation_path: str = "data/conversations",
        enable_skill_routing: bool = True,
        skill_router: Optional[SkillRouter] = None,
    ):
        """
        初始化Agent

        Args:
            provider: LLM Provider（OpenAI）
            tools: 工具列表
            max_iterations: 最大工具调用迭代次数
            save_conversations: 是否保存对话历史
            conversation_path: 对话历史保存路径
        """
        self.provider = provider
        self.tools = {tool.name: tool for tool in tools}
        self.max_iterations = max_iterations
        self.enable_skill_routing = enable_skill_routing
        self.skill_router = skill_router if skill_router is not None else SkillRouter()
        self.task_state = TaskState()

        # 初始化对话状态
        conv_path = conversation_path if save_conversations else None
        self.state = ConversationState(
            max_history=50,
            save_path=conv_path
        )

        # 添加system消息
        system_msg = Message(role=MessageRole.SYSTEM, content=self.SYSTEM_PROMPT)
        self.state.add_message(system_msg)

        logger.info(f"初始化Agent: 工具数量={len(tools)}, max_iterations={max_iterations}")

    def start_new_turn(self, user_message: str) -> Message:
        """
        开始一个新的用户轮次。

        该方法会同时更新旧的对话历史和新的 TaskState。
        """
        logger.info(f"用户输入: {user_message[:100]}...")

        if self.task_state.current_phase == TaskPhase.WAITING_USER:
            self._apply_waiting_user_reply(user_message)
            if self.task_state.current_phase == TaskPhase.WAITING_USER:
                self.task_state.resume_from_waiting()

        self._update_phase_from_user_message(user_message)

        user_msg = Message(role=MessageRole.USER, content=user_message)
        self.state.add_message(user_msg)
        self.task_state.append_message(user_msg)
        return user_msg

    def _update_phase_from_user_message(self, user_message: str) -> None:
        """基于用户输入做轻量的阶段判断。"""
        evaluation_keywords = ("评估", "风险", "可行性", "打分")

        if any(keyword in user_message for keyword in evaluation_keywords):
            self.task_state.transition_to(TaskPhase.PLAN_EVALUATION)
            return

        self._infer_incident_info_from_text(user_message)

        if self.task_state.current_phase == TaskPhase.INTAKE and self.task_state.intake_is_complete():
            self.task_state.transition_to(TaskPhase.SITUATIONAL_AWARENESS)

    def _infer_incident_info_from_text(self, user_message: str) -> None:
        """
        基于关键词做轻量灾情信息抽取。

        这里不追求完整准确，主要是给 TaskState 一个可用的起点。
        """
        if not self.task_state.incident_info.location_text:
            location_match = re.search(r"([A-Z]\d+\S*高速\S*K?\d+\S*|[\u4e00-\u9fa5A-Za-z0-9\-]+路段|[\u4e00-\u9fa5A-Za-z0-9\-]+出口)", user_message)
            if location_match:
                self.task_state.incident_info.location_text = location_match.group(1)

        incident_type_map = {
            "危化品": "危化品泄漏",
            "泄漏": "危化品泄漏",
            "追尾": "交通事故",
            "相撞": "交通事故",
            "车祸": "交通事故",
            "塌方": "地质灾害",
            "滑坡": "地质灾害",
            "火灾": "火灾",
            "起火": "火灾",
            "积水": "洪涝",
            "洪水": "洪涝",
        }
        if not self.task_state.incident_info.incident_type:
            for keyword, incident_type in incident_type_map.items():
                if keyword in user_message:
                    self.task_state.incident_info.incident_type = incident_type
                    break

        if not self.task_state.incident_info.severity:
            if any(keyword in user_message for keyword in ("危化品", "有毒气体", "爆炸", "多人伤亡", "大量被困")):
                self.task_state.incident_info.severity = "critical"
            elif any(keyword in user_message for keyword in ("严重", "多人受伤", "堆积严重", "道路中断")):
                self.task_state.incident_info.severity = "high"
            elif any(keyword in user_message for keyword in ("轻微", "小事故", "擦碰")):
                self.task_state.incident_info.severity = "low"
            else:
                self.task_state.incident_info.severity = "medium"

        casualty_matches = {
            "injured": re.search(r"(\d+)\s*人受伤", user_message),
            "dead": re.search(r"(\d+)\s*人死亡", user_message),
            "trapped": re.search(r"(\d+)\s*人被困", user_message),
        }
        casualties = {}
        for key, match in casualty_matches.items():
            if match:
                casualties[key] = int(match.group(1))
        if casualties:
            self.task_state.incident_info.casualties.update(casualties)
            summary_parts = []
            if "dead" in casualties:
                summary_parts.append(f"{casualties['dead']}人死亡")
            if "injured" in casualties:
                summary_parts.append(f"{casualties['injured']}人受伤")
            if "trapped" in casualties:
                summary_parts.append(f"{casualties['trapped']}人被困")
            self.task_state.incident_info.casualty_status = "，".join(summary_parts)
        elif not self.task_state.incident_info.casualty_status:
            if any(keyword in user_message for keyword in ("暂无伤亡", "无人员伤亡", "无人伤亡")):
                self.task_state.incident_info.casualty_status = "暂无伤亡"
            elif any(keyword in user_message for keyword in ("被困", "困于车内")):
                self.task_state.incident_info.casualty_status = "有人被困"
            elif any(keyword in user_message for keyword in ("受伤", "伤员")):
                self.task_state.incident_info.casualty_status = "有人员受伤"
            elif "死亡" in user_message:
                self.task_state.incident_info.casualty_status = "有人员死亡"

        if not self.task_state.incident_info.scene_status:
            scene_status_map = {
                "双向阻断": "双向阻断",
                "双向中断": "双向阻断",
                "单向阻断": "单向阻断",
                "道路中断": "道路中断",
                "交通中断": "道路中断",
                "无法通行": "道路无法通行",
                "火势蔓延": "火势仍在蔓延",
                "起火": "现场存在火情",
                "泄漏已控制": "泄漏已得到控制",
                "泄漏": "现场存在泄漏风险",
                "拥堵": "现场交通拥堵",
                "占道": "事故车辆占道",
            }
            for keyword, scene_status in scene_status_map.items():
                if keyword in user_message:
                    self.task_state.incident_info.scene_status = scene_status
                    break

    def _apply_waiting_user_reply(self, user_message: str) -> None:
        """处理用户对 WAITING_USER 阶段的回复。"""
        pending = self.task_state.pending_question
        if pending is None:
            return

        reply = user_message.strip()
        normalized_reply = reply.lower()

        if pending.question_type == "plan_selection" and self.task_state.candidate_plans:
            selected_plan = self._select_candidate_plan(reply)
            if selected_plan is not None:
                for plan in self.task_state.candidate_plans:
                    plan.selected = plan.plan_id == selected_plan.plan_id
                self.task_state.clear_pending_question()
                self.task_state.transition_to(TaskPhase.PLAN_EVALUATION)
                return

        if pending.question_type == "confirmation":
            affirmative = ("确认", "执行", "可以", "同意", "继续", "yes", "y", "ok")
            negative = ("调整", "不要", "取消", "重做", "否", "no", "n")

            if any(token in normalized_reply for token in affirmative):
                self.task_state.clear_pending_question()
                self.task_state.transition_to(TaskPhase.OUTPUT)
                return

            if any(token in normalized_reply for token in negative):
                self.task_state.clear_pending_question()
                self.task_state.transition_to(TaskPhase.PLAN_GENERATION)
                return

        # 默认视为补充信息，更新灾情摘要后回到原阶段
        self._infer_incident_info_from_text(reply)
        if self.task_state.incident_info.additional_context:
            self.task_state.incident_info.additional_context += "\n"
        self.task_state.incident_info.additional_context += reply

    def _select_candidate_plan(self, user_message: str) -> Optional[CandidatePlan]:
        """根据用户回复匹配候选方案。"""
        if not self.task_state.candidate_plans:
            return None

        reply = user_message.strip()
        normalized_reply = reply.lower()

        index_aliases = {
            "1": 0,
            "一": 0,
            "a": 0,
            "方案a": 0,
            "方案1": 0,
            "2": 1,
            "二": 1,
            "b": 1,
            "方案b": 1,
            "方案2": 1,
            "3": 2,
            "三": 2,
            "c": 2,
            "方案c": 2,
            "方案3": 2,
        }
        if normalized_reply in index_aliases:
            index = index_aliases[normalized_reply]
            if 0 <= index < len(self.task_state.candidate_plans):
                return self.task_state.candidate_plans[index]

        for plan in self.task_state.candidate_plans:
            if reply == plan.plan_id or plan.title in reply:
                return plan

        return None

    def get_active_tools(self) -> List[BaseTool]:
        """
        根据当前阶段返回应激活的工具。

        如果 SkillRouter 还未完全覆盖当前阶段，回退到全量工具以保证兼容性。
        """
        if not self.enable_skill_routing:
            return list(self.tools.values())

        resolved_tools = self.skill_router.resolve_tools(
            self.task_state.current_phase,
            self.tools,
        )
        if resolved_tools:
            return resolved_tools

        if self.task_state.current_phase in {
            TaskPhase.OUTPUT,
            TaskPhase.OUTPUT_COMPLETE,
            TaskPhase.WAITING_USER,
        }:
            return []

        logger.warning(
            "当前阶段未解析出有效工具，回退到全量工具: phase=%s",
            self.task_state.current_phase.value,
        )
        return list(self.tools.values())

    def get_runtime_messages(self) -> List[dict]:
        """
        获取本轮发给模型的消息列表。

        这里会在原有 system prompt 基础上，动态拼接：
        - TaskState 摘要
        - 当前阶段的 Skill Prompt
        - 当前可用工具说明
        """
        messages = self.state.get_history()
        runtime_system_prompt = self._build_runtime_system_prompt()

        if messages and messages[0]["role"] == MessageRole.SYSTEM.value:
            runtime_messages = [dict(message) for message in messages]
            runtime_messages[0]["content"] = runtime_system_prompt
            return runtime_messages

        return [{"role": MessageRole.SYSTEM.value, "content": runtime_system_prompt}, *messages]

    def _build_runtime_system_prompt(self) -> str:
        """构建带阶段信息的运行时 system prompt。"""
        active_tools = self.get_active_tools()
        active_tool_names = ", ".join(tool.name for tool in active_tools) if active_tools else "无"
        phase_prompt = self.skill_router.build_phase_prompt(self.task_state.current_phase)

        sections = [
            self.SYSTEM_PROMPT,
            self._build_control_protocol_prompt(),
            "## TaskState 摘要\n" + self.task_state.build_context_summary(),
            "## 当前可用工具\n" + active_tool_names,
        ]

        if phase_prompt:
            sections.append(phase_prompt)

        return "\n\n".join(sections)

    def _build_control_protocol_prompt(self) -> str:
        """构建结构化控制协议说明。"""
        return (
            "## 结构化控制协议\n"
            "当你在本轮不调用工具、而是直接输出分析、向用户提问、切换阶段或给出最终方案时，"
            "你必须在回答末尾追加一个 agent_control 代码块。\n\n"
            "要求：\n"
            "- 用户可见内容写在前面\n"
            "- 代码块必须是合法 JSON\n"
            "- 如果需要用户补充信息，needs_user_input=true，并给出 user_prompt\n"
            "- 如果当前轮次已经是最终输出，final_output=true\n"
            "- next_phase 必须是有效阶段名或空字符串\n"
            "- 可通过 incident_updates / environment_updates 更新结构化状态\n\n"
            "格式如下：\n"
            f"{self.CONTROL_BLOCK_TEMPLATE}"
        )

    def after_tool_execution(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]],
        result: str,
        success: bool = True,
        error_message: str = "",
    ) -> None:
        """
        在工具执行后同步 TaskState。
        """
        self.task_state.record_tool_call(
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            success=success,
            error_message=error_message,
        )

        if not success:
            return

        parsed_result = self._try_parse_json(result)
        self._update_task_state_from_tool_result(tool_name, parsed_result)
        self._advance_phase_after_tool(tool_name)

    def _try_parse_json(self, content: str) -> Any:
        """尽量将工具返回解析为 JSON。解析失败时返回原字符串。"""
        if not isinstance(content, str):
            return content

        try:
            return json.loads(content)
        except Exception:
            return content

    def _update_task_state_from_tool_result(self, tool_name: str, result: Any) -> None:
        """将常见工具结果同步到 TaskState。"""
        if not isinstance(result, dict):
            return

        if tool_name == "geocode_address" and result.get("status") == "success":
            longitude = result.get("longitude")
            latitude = result.get("latitude")
            if longitude is not None and latitude is not None:
                self.task_state.incident_info.location_coords = {
                    "longitude": longitude,
                    "latitude": latitude,
                }
            self.task_state.environment_info.formatted_address = result.get("formatted_address", "")

        elif tool_name == "reverse_geocode" and result.get("status") == "success":
            self.task_state.environment_info.formatted_address = result.get("formatted_address", "")

        elif tool_name == "get_weather_by_location":
            self.task_state.environment_info.weather = result

        elif tool_name == "check_traffic_status":
            self.task_state.environment_info.traffic = result

        elif tool_name == "media_caption":
            self.task_state.environment_info.media_summary = result

        elif tool_name == "search_nearby_pois" and result.get("status") == "success":
            self.task_state.environment_info.nearby_pois = result.get("pois", [])

        elif tool_name == "search_map_resources":
            resources = result.get("resources", [])
            if resources:
                self.task_state.available_resources = resources

        elif tool_name == "search_emergency_resources" and result.get("status") == "success":
            candidates = result.get("candidates", {})
            warehouses = candidates.get("warehouses", [])
            teams = candidates.get("teams", [])
            self.task_state.available_resources = [*warehouses, *teams]

        elif tool_name == "optimize_dispatch_plan" and result.get("status") == "success":
            dispatch_plan = result.get("dispatch_plan", {})
            planned_resources = []
            for tier_name in ("tier1", "tier2", "tier3"):
                planned_resources.extend(dispatch_plan.get(tier_name, {}).get("resources", []))
            if planned_resources:
                self.task_state.available_resources = planned_resources

        elif tool_name == "query_rag" and result.get("status") == "success":
            for item in result.get("results", []):
                self.task_state.add_knowledge_reference(
                    KnowledgeReference(
                        source_type="regulation",
                        title=item.get("doc_id", ""),
                        excerpt=item.get("text", ""),
                        source_path=item.get("source", ""),
                        score=item.get("score"),
                    )
                )

        elif tool_name == "query_historical_cases" and result.get("status") == "success":
            for item in result.get("results", []):
                self.task_state.add_knowledge_reference(
                    KnowledgeReference(
                        source_type="historical_case",
                        title=item.get("title", ""),
                        excerpt=item.get("description", ""),
                        source_path=item.get("location", ""),
                    )
                )

        elif tool_name == "risk_assessment":
            self.task_state.add_evaluation_result(
                EvaluationResult(
                    overall_score=result.get("overall_score"),
                    risk_level=result.get("risk_level", ""),
                    summary=result.get("message", ""),
                    suggestions=result.get("suggestions", []),
                    raw_result=result,
                )
            )

    def _advance_phase_after_tool(self, tool_name: str) -> None:
        """根据已执行的工具做轻量阶段推进。"""
        situational_tools = {
            "geocode_address",
            "reverse_geocode",
            "check_traffic_status",
            "get_weather_by_location",
            "media_caption",
        }
        planning_tools = {
            "query_rag",
            "query_historical_cases",
            "search_emergency_resources",
            "optimize_dispatch_plan",
            "search_map_resources",
            "search_nearby_pois",
        }

        if tool_name in situational_tools and self.task_state.current_phase == TaskPhase.SITUATIONAL_AWARENESS:
            self.task_state.transition_to(TaskPhase.PLAN_GENERATION)
            return

        if tool_name in planning_tools and self.task_state.current_phase == TaskPhase.SITUATIONAL_AWARENESS:
            self.task_state.transition_to(TaskPhase.PLAN_GENERATION)
            return

        if tool_name == "risk_assessment":
            self.task_state.transition_to(TaskPhase.OUTPUT)

    def build_post_tool_analysis_message(self, tool_name: str) -> Message:
        """在工具执行后插入分析指令。"""
        analysis_prompt = f"""【重要】你刚刚调用了以下工具并获得了结果：

{tool_name}

现在请按照以下步骤进行：

**第一步：分析工具结果（必须完成）**
请对刚才的工具调用结果进行简要分析：
- 每个工具返回了什么关键信息？
- 这些信息之间有什么关联？
- 基于这些结果，你发现了什么？

**第二步：决定下一步操作**
根据你的分析，选择以下之一：
- 如果信息已经足够，直接给出处置建议，并附上 agent_control 控制块
- 如果还需要更多信息，说明需要调用什么工具并调用
- 如果需要向用户补问，先向用户说明原因，并附上 agent_control 控制块

注意：请确保你的回答包含第一步的分析内容。"""
        return Message(role=MessageRole.SYSTEM, content=analysis_prompt)

    def parse_assistant_control(self, content: str) -> AssistantControl:
        """
        解析模型输出中的控制块。

        控制块缺失时会使用保守回退逻辑，尽量避免 Web 端流程中断。
        """
        raw_payload = self._extract_control_payload(content)
        if not raw_payload:
            return self._fallback_control(content)

        next_phase = raw_payload.get("next_phase") or ""
        control = AssistantControl(
            next_phase=self._safe_phase(next_phase),
            needs_user_input=bool(raw_payload.get("needs_user_input", False)),
            user_prompt=str(raw_payload.get("user_prompt", "") or ""),
            final_output=bool(raw_payload.get("final_output", False)),
            phase_reason=str(raw_payload.get("phase_reason", "") or ""),
            incident_updates=raw_payload.get("incident_updates", {}) or {},
            environment_updates=raw_payload.get("environment_updates", {}) or {},
            candidate_plans=raw_payload.get("candidate_plans", []) or [],
            selected_plan_id=str(raw_payload.get("selected_plan_id", "") or ""),
            awaiting_confirmation=bool(raw_payload.get("awaiting_confirmation", False)),
            raw_payload=raw_payload,
        )
        return control

    def _extract_control_payload(self, content: str) -> Dict[str, Any]:
        """从文本中提取 agent_control JSON。"""
        if not content:
            return {}

        patterns = [
            r"```agent_control\s*(\{.*?\})\s*```",
            r"```json\s*(\{.*?\})\s*```",
        ]
        for pattern in patterns:
            match = re.search(pattern, content, re.DOTALL)
            if not match:
                continue
            try:
                return json.loads(match.group(1))
            except Exception:
                logger.warning("agent_control 解析失败，原始内容将走回退逻辑")
                return {}
        return {}

    def strip_control_block(self, content: str) -> str:
        """移除用户不可见的控制块。"""
        if not content:
            return ""

        stripped = re.sub(r"```agent_control\s*\{.*?\}\s*```", "", content, flags=re.DOTALL)
        stripped = re.sub(r"```json\s*\{.*?\}\s*```", "", stripped, flags=re.DOTALL)
        return stripped.strip()

    def _fallback_control(self, content: str) -> AssistantControl:
        """当模型未按协议返回控制块时的保守回退。"""
        visible_text = self.strip_control_block(content) or content or ""

        needs_user_input = any(keyword in visible_text for keyword in ("请提供", "请确认", "请选择", "是否确认"))
        final_output = self.task_state.current_phase in {TaskPhase.OUTPUT, TaskPhase.PLAN_EVALUATION}
        next_phase = None

        if self.task_state.current_phase == TaskPhase.PLAN_GENERATION and not needs_user_input:
            next_phase = TaskPhase.PLAN_EVALUATION
        elif self.task_state.current_phase == TaskPhase.PLAN_EVALUATION and not needs_user_input:
            next_phase = TaskPhase.OUTPUT

        return AssistantControl(
            next_phase=next_phase,
            needs_user_input=needs_user_input,
            user_prompt=visible_text if needs_user_input else "",
            final_output=final_output,
        )

    def _safe_phase(self, value: str) -> Optional[TaskPhase]:
        """将字符串安全转换为 TaskPhase。"""
        if not value:
            return None

        try:
            return TaskPhase(value)
        except ValueError:
            logger.warning("收到未知阶段标识: %s", value)
            return None

    def _normalize_candidate_plans(self, raw_plans: Any) -> List[Dict[str, Any]]:
        """将模型返回的候选方案统一整理成字典列表。"""
        if not raw_plans:
            return []

        if isinstance(raw_plans, (str, dict)):
            raw_plans = [raw_plans]
        elif not isinstance(raw_plans, list):
            return []

        normalized_plans: List[Dict[str, Any]] = []
        for index, item in enumerate(raw_plans, start=1):
            if isinstance(item, dict):
                normalized_plans.append(item)
                continue

            if isinstance(item, str):
                text = item.strip()
                if not text:
                    continue
                normalized_plans.append(
                    {
                        "plan_id": f"plan_{index}",
                        "title": f"方案{index}",
                        "summary": text,
                        "content": text,
                        "advantages": [],
                        "disadvantages": [],
                        "applicable_scenarios": [],
                    }
                )
                continue

            logger.warning("忽略无法解析的 candidate_plan: type=%s", type(item).__name__)

        return normalized_plans

    def apply_assistant_control(self, control: AssistantControl) -> None:
        """将模型控制信息应用到 TaskState。"""
        self.task_state.apply_incident_updates(control.incident_updates)
        self.task_state.apply_environment_updates(control.environment_updates)

        normalized_candidate_plans = self._normalize_candidate_plans(control.candidate_plans)

        if normalized_candidate_plans:
            self.task_state.candidate_plans = []
            for index, item in enumerate(normalized_candidate_plans, start=1):
                self.task_state.add_candidate_plan(
                    CandidatePlan(
                        plan_id=str(item.get("plan_id", f"plan_{index}")),
                        title=str(item.get("title", f"方案{index}")),
                        summary=str(item.get("summary", "")),
                        content=str(item.get("content", item.get("summary", ""))),
                        advantages=list(item.get("advantages", []) or []),
                        disadvantages=list(item.get("disadvantages", []) or []),
                        applicable_scenarios=list(item.get("applicable_scenarios", []) or []),
                    )
                )

        if control.selected_plan_id:
            for plan in self.task_state.candidate_plans:
                plan.selected = plan.plan_id == control.selected_plan_id

        if control.needs_user_input:
            question = control.user_prompt or "请补充必要信息。"
            return_phase = control.next_phase or self.task_state.current_phase
            question_type = "info_request"
            suggested_options: List[str] = []

            if control.awaiting_confirmation:
                question_type = "confirmation"
                suggested_options = ["确认执行", "返回调整"]
            elif normalized_candidate_plans:
                question_type = "plan_selection"
                suggested_options = [plan.get("title", "") for plan in normalized_candidate_plans]

            self.task_state.set_pending_question(
                question=question,
                reason=control.phase_reason,
                suggested_options=suggested_options,
                question_type=question_type,
                metadata={"awaiting_confirmation": control.awaiting_confirmation},
                return_phase=return_phase,
            )
            return

        if control.next_phase is not None:
            self.task_state.transition_to(control.next_phase)

        if control.final_output:
            self.task_state.transition_to(TaskPhase.OUTPUT_COMPLETE)

    def chat(self, user_message: str) -> str:
        """
        与Agent对话（主入口）

        Args:
            user_message: 用户消息

        Returns:
            Agent的响应内容
        """
        self.start_new_turn(user_message)

        # 迭代处理：可能需要多次工具调用
        iteration = 0
        final_response = ""

        # 跟踪已调用的工具，防止重复调用
        called_tools = set()

        while iteration < self.max_iterations:
            iteration += 1
            logger.info(f"--- 迭代 {iteration} ---")

            # 获取对话历史
            messages = self.get_runtime_messages()

            # 获取工具定义
            tool_definitions = [tool.to_openai_format() for tool in self.get_active_tools()]

            # 调用LLM
            try:
                start_time = time.time()
                response = self.provider.chat(messages, tools=tool_definitions)
                elapsed = time.time() - start_time
                logger.info(f"LLM响应耗时: {elapsed:.2f}秒")

            except Exception as e:
                logger.error(f"LLM调用失败: {e}")
                return f"抱歉，系统出现错误：{str(e)}"

            # 检查是否有工具调用
            if response.tool_calls:
                # 只执行第一个工具调用，实现逐步调用
                tool_call = response.tool_calls[0]

                # 检测是否是重复工具调用
                if tool_call.name in called_tools:
                    logger.warning(f"检测到重复工具调用: {tool_call.name}，已自动跳过")
                    # 添加跳过消息
                    skip_msg = Message(
                        role=MessageRole.ASSISTANT,
                        content=f"（工具 {tool_call.name} 已经调用过，跳过重复调用）"
                    )
                    self.state.add_message(skip_msg)
                    continue

                # 如果有多个工具调用，记录提示
                if len(response.tool_calls) > 1:
                    other_tools = [tc.name for tc in response.tool_calls[1:]]
                    logger.info(f"检测到多个工具调用，本次只执行第一个: {tool_call.name}，其他工具将在后续轮次中考虑: {other_tools}")

                # 添加助手消息（只包含第一个工具调用）
                assistant_msg = Message(
                    role=MessageRole.ASSISTANT,
                    content=response.content or "",
                    tool_calls=[tool_call]
                )
                self.state.add_message(assistant_msg)

                # 标记工具已调用
                called_tools.add(tool_call.name)
                logger.info(f"执行工具: {tool_call.name}（已调用工具列表: {called_tools}）")

                try:
                    # 执行工具
                    tool_result = self._execute_tool(tool_call)

                    # 添加工具结果到历史
                    tool_msg = Message(
                        role=MessageRole.TOOL,
                        content=tool_result,
                        tool_call_id=tool_call.id
                    )
                    self.state.add_message(tool_msg)
                    self.task_state.append_message(tool_msg)
                    self.after_tool_execution(tool_call.name, tool_call.arguments, tool_result)

                except Exception as e:
                    logger.error(f"工具执行失败: {e}")
                    # 添加错误信息
                    error_msg = Message(
                        role=MessageRole.TOOL,
                        content=f"工具执行失败: {str(e)}",
                        tool_call_id=tool_call.id
                    )
                    self.state.add_message(error_msg)
                    self.task_state.append_message(error_msg)
                    self.after_tool_execution(
                        tool_call.name,
                        tool_call.arguments,
                        result="",
                        success=False,
                        error_message=str(e),
                    )

                # 在工具调用完成后，插入一个系统消息，要求模型先分析工具结果
                logger.info("=== 工具调用完成，插入分析指令 ===")
                analysis_msg = self.build_post_tool_analysis_message(tool_call.name)
                self.state.add_message(analysis_msg)
                self.task_state.append_message(analysis_msg)

                # 继续下一轮迭代，让LLM基于工具结果生成最终回答
                continue

            else:
                # 没有工具调用，这是最终回答
                final_response = response.content
                control = self.parse_assistant_control(final_response)
                self.apply_assistant_control(control)
                final_response = self.strip_control_block(final_response)

                # 添加助手消息到历史
                assistant_msg = Message(
                    role=MessageRole.ASSISTANT,
                    content=final_response
                )
                self.state.add_message(assistant_msg)
                self.task_state.append_message(assistant_msg)

                logger.info(f"最终响应: {final_response[:100]}...")
                break

        # 保存对话历史
        self.state.save()

        return final_response

    def _execute_tool(self, tool_call: ToolCall) -> str:
        """
        执行工具调用

        Args:
            tool_call: 工具调用信息

        Returns:
            工具执行结果

        Raises:
            KeyError: 工具不存在
            Exception: 工具执行失败
        """
        tool_name = tool_call.name
        arguments = tool_call.arguments

        logger.info(f"执行工具: {tool_name}, 参数: {arguments}")

        # 获取工具
        if tool_name not in self.tools:
            raise KeyError(f"工具不存在: {tool_name}")

        tool = self.tools[tool_name]

        # 执行工具
        try:
            result = tool.execute(**arguments)
            logger.info(f"工具执行成功: 结果长度={len(result)}")
            return result

        except Exception as e:
            logger.error(f"工具执行失败: {e}")
            raise

    def reset(self) -> None:
        """
        重置对话状态

        清空对话历史，但保留system message。
        """
        self.state.clear()
        self.task_state = TaskState()
        # 重新添加system message
        system_msg = Message(role=MessageRole.SYSTEM, content=self.SYSTEM_PROMPT)
        self.state.add_message(system_msg)
        logger.info("对话状态已重置")

    def set_system_prompt(self, prompt: str) -> None:
        """
        设置System Prompt

        Args:
            prompt: 新的system prompt
        """
        self.__class__.SYSTEM_PROMPT = prompt
        logger.info("System Prompt已更新")
