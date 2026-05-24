"""无 Chainlit 依赖的 Agent 端到端执行逻辑。

API 模式下采用「一键处置」策略：
- 默认用户已输入全部详情信息，不向用户补问
- 缺失信息在方案中考虑多种情况，而非阻塞等待
- 自动跳过所有用户交互点（方案选择、确认、补问）
- 连续停住超过阈值时强制进入最终输出
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from .task_store import TaskRecord, TaskStore

logger = logging.getLogger(__name__)

MAX_AGENT_ITERATIONS = 24
MAX_FINAL_REVIEW_ROUNDS = 2
# 连续无工具调用且非最终输出的轮次上限，超过后强制进入 Pipeline
MAX_CONSECUTIVE_STALLS = 3

# ── API 端到端模式系统指令 ────────────────────────────────
# 注入到 Agent 消息历史中，覆盖交互式行为

API_MODE_SYSTEM_PROMPT = """【API 端到端模式——重要】
你当前运行在 HTTP API 无人值守模式下，没有人类用户在线等待回复。
你必须严格遵守以下规则：

1. **绝对不要向用户提问、补问或等待确认。** 不要输出"请提供""请确认""请选择"等交互语句。
   - needs_user_input 必须始终为 false。
2. **信息缺失时的处理方式：** 如果关键信息缺失（如伤亡不明、位置模糊），你必须：
   - 基于已有信息做合理推断，并在方案中标注'待现场确认'；
   - 对不确定的关键决策点，列出多种情景及对应处置建议；
   - 不要因为信息不完整就停止推进。
3. **自动推进阶段：** 完成当前阶段可用工具调用后，立即切换到下一阶段，不要等待指令。
4. **候选方案自动选择：** 如果你生成了多个候选方案，自动选择最稳妥（覆盖最全面、风险最低）的方案继续推进，不要等用户选择。
5. **目标：** 尽快走完 INTAKE → SITUATIONAL_AWARENESS → PLAN_GENERATION → PLAN_EVALUATION → OUTPUT 全流程，输出完整 7 章节标准化应急指挥方案。
6. **效率：** 一轮能调用工具就调用，不要花一轮来"说明你接下来打算做什么"。
"""


def _parse_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


# ── Agent / Provider 构建（不依赖 Chainlit） ─────────────

def _build_provider_bundle(config: Optional[Dict[str, str]] = None):
    """根据可选配置构建 chat / caption / evaluation provider。

    优先级：请求 config > defaults.py 硬编码 > 环境变量。
    这样不传 config 时始终走项目内置的 deepseek 配置，
    不会被部署环境中残留的 OPENAI_* 环境变量覆盖。
    """
    from src.providers import OpenAIProvider
    from src.providers.defaults import (
        DEFAULT_CAPTION_MODEL,
        DEFAULT_TEXT_API_KEY,
        DEFAULT_TEXT_BASE_URL,
        DEFAULT_TEXT_MAX_TOKENS,
        DEFAULT_TEXT_MODEL,
    )

    config = config or {}
    api_key = config.get("OPENAI_API_KEY") or DEFAULT_TEXT_API_KEY or os.getenv("OPENAI_API_KEY") or ""
    base_url = config.get("OPENAI_BASE_URL") or DEFAULT_TEXT_BASE_URL or os.getenv("OPENAI_BASE_URL") or ""
    chat_model = config.get("OPENAI_MODEL") or DEFAULT_TEXT_MODEL or os.getenv("OPENAI_MODEL") or ""
    max_tokens = _parse_positive_int(config.get("OPENAI_MAX_TOKENS"), DEFAULT_TEXT_MAX_TOKENS)

    caption_model = os.getenv("CAPTION_MODEL") or DEFAULT_CAPTION_MODEL
    caption_api_key = os.getenv("CAPTION_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or api_key
    caption_base_url = os.getenv("CAPTION_BASE_URL") or None

    evaluation_model = os.getenv("EVAL_MODEL") or chat_model
    evaluation_base_url = os.getenv("EVAL_BASE_URL") or base_url

    return {
        "chat": OpenAIProvider(
            api_key=api_key, base_url=base_url, model=chat_model,
            max_tokens=max_tokens, provider="auto",
        ),
        "caption": OpenAIProvider(
            api_key=caption_api_key, base_url=caption_base_url, model=caption_model,
            provider="auto",
        ),
        "evaluation": OpenAIProvider(
            api_key=api_key, base_url=evaluation_base_url, model=evaluation_model,
            max_tokens=max_tokens, provider="auto",
        ),
    }


def create_agent_for_api(config: Optional[Dict[str, str]] = None):
    """创建独立的 Agent 实例（不依赖 Chainlit session）。"""
    from src.agent import Agent
    from src.tools import (
        QueryRegulations, QueryHistoricalCases, GetEmergencyPlan,
        EvaluateIncidentSeverity, RiskAssessment, MediaCaption,
        SearchEmergencyResources, OptimizeDispatchPlan, SearchExperts,
        SearchMapResources, CheckTrafficStatus, GetWeatherByLocation,
        GeocodeAddress, ReverseGeocode, SearchNearbyPOIs, PlanDispatchRoutes,
        GaodeConfig,
    )
    from src.rag import QueryRAG, BALANCED_RAG_CONFIG
    from src.emergency_plans import EmergencyPlanService
    from src.resource_dispatch import ResourceDispatchEngine

    providers = _build_provider_bundle(config)

    gaode_key = os.getenv("GAODE_API_KEY")
    if gaode_key:
        GaodeConfig.set_api_key(gaode_key)

    tools = []
    dispatch_engine = None
    plan_service = None

    try:
        dispatch_engine = ResourceDispatchEngine()
    except Exception as e:
        logger.warning("ResourceDispatchEngine 初始化失败: %s", e)

    try:
        plan_service = EmergencyPlanService()
    except Exception as e:
        logger.warning("EmergencyPlanService 初始化失败: %s", e)

    # 基础工具
    _try_add(tools, lambda: QueryRegulations(data_path="data/regulations"))
    _try_add(tools, lambda: QueryHistoricalCases(data_path="data/historical_cases"))
    _try_add(tools, lambda: QueryRAG(data_dir="data/regulations/chunked_json", config=BALANCED_RAG_CONFIG))

    if plan_service is not None:
        _try_add(tools, lambda: GetEmergencyPlan(plan_service=plan_service))
        _try_add(tools, lambda: EvaluateIncidentSeverity(
            provider=providers["evaluation"], plan_service=plan_service,
        ))

    _try_add(tools, lambda: RiskAssessment(provider=providers["evaluation"], timeout=30))
    _try_add(tools, lambda: MediaCaption(
        provider=providers["caption"], timeout=60, model=providers["caption"].model,
    ))

    # 高德工具
    _try_add(tools, CheckTrafficStatus)
    _try_add(tools, GetWeatherByLocation)
    _try_add(tools, GeocodeAddress)
    _try_add(tools, ReverseGeocode)
    _try_add(tools, SearchNearbyPOIs)
    _try_add(tools, PlanDispatchRoutes)

    if dispatch_engine is not None:
        _try_add(tools, lambda: SearchEmergencyResources(engine=dispatch_engine))
        _try_add(tools, lambda: OptimizeDispatchPlan(engine=dispatch_engine))

    expert_data_path = Path(__file__).resolve().parent.parent.parent / "data" / "专家数据" / "expert_info.xls"
    _try_add(tools, lambda: SearchExperts(data_path=str(expert_data_path)))
    _try_add(tools, lambda: SearchMapResources(data_dir="data/graph"))

    agent = Agent(
        provider=providers["chat"],
        tools=tools,
        max_iterations=MAX_AGENT_ITERATIONS,
        save_conversations=True,
        conversation_path="data/conversations",
    )
    return agent


def _try_add(tools: list, factory) -> None:
    """安全地尝试创建并添加工具。"""
    try:
        tool = factory() if callable(factory) else factory
        tools.append(tool)
    except Exception as e:
        logger.warning("工具加载失败: %s", e)


def _build_review_provider(config: Optional[Dict[str, str]] = None):
    """构建用于 Pipeline 和 Reviewer 的 provider。"""
    providers = _build_provider_bundle(config)
    return providers["evaluation"]


# ── 预填充灾情信息 ────────────────────────────────────────

def _prefill_incident_info(agent, incident_info: Dict[str, Any]) -> None:
    """将请求中提供的 incident_info 直接写入 Agent 的 TaskState。"""
    agent.task_state.apply_incident_updates(incident_info)


# ── 从 TaskState 收集中间数据 ─────────────────────────────

def _collect_process_data(agent) -> Dict[str, Any]:
    """从 Agent 的 TaskState 中提取中间过程数据。"""
    ts = agent.task_state
    incident = ts.incident_info

    incident_dict = {
        "incident_type": incident.incident_type,
        "severity": incident.severity,
        "incident_category": incident.incident_category,
        "disaster_type": incident.disaster_type,
        "scene_type": incident.scene_type,
        "response_level": incident.response_level,
        "response_level_reason": incident.response_level_reason,
        "location_text": incident.location_text,
        "location_coords": incident.location_coords,
        "casualty_status": incident.casualty_status,
        "casualties": incident.casualties,
        "scene_status": incident.scene_status,
    }

    env = ts.environment_info
    environment_dict = {
        "formatted_address": env.formatted_address,
        "weather": env.weather,
        "traffic": env.traffic,
        "nearby_pois": env.nearby_pois[:10],
        "route_notes": env.additional_notes[:10],
    }

    tool_calls = [
        {
            "tool_name": r.tool_name,
            "arguments": r.arguments,
            "success": r.success,
            "result_preview": r.result_preview[:200],
            "error_message": r.error_message,
        }
        for r in ts.tool_call_log
    ]

    knowledge_refs = [
        {
            "source_type": ref.source_type,
            "title": ref.title,
            "source_path": ref.source_path,
            "score": ref.score,
        }
        for ref in ts.knowledge_refs
    ]

    experts = [
        r for r in ts.available_resources if r.get("type") == "expert"
    ]

    risk_assessment = [
        {
            "overall_score": er.overall_score,
            "risk_level": er.risk_level,
            "summary": er.summary,
            "suggestions": er.suggestions,
        }
        for er in ts.evaluation_results
    ]

    return {
        "incident_info": incident_dict,
        "environment": environment_dict,
        "resources": ts.available_resources[:30],
        "experts": experts,
        "tool_calls": tool_calls,
        "risk_assessment": risk_assessment,
        "knowledge_refs": knowledge_refs,
    }


# ── 核心：异步执行任务 ───────────────────────────────────

async def run_task(task_id: str, store: TaskStore) -> None:
    """后台执行一个完整的方案生成任务（无 Chainlit 依赖，端到端无交互）。"""
    record = store.get(task_id)
    if not record:
        logger.error("任务不存在: task_id=%s", task_id)
        return

    try:
        store.update_progress(task_id, status="running", current_action="正在初始化 Agent")

        # 1. 创建 Agent
        agent = create_agent_for_api(record.request.get("config"))
        record.agent = agent

        # 2. 预填充 incident_info
        if record.request.get("incident_info"):
            _prefill_incident_info(agent, record.request["incident_info"])

        # 3. 注入 API 端到端模式指令
        _inject_api_mode_prompt(agent)

        # 4. Agent 主循环
        await _run_agent_loop(task_id, store, agent, record)

    except asyncio.CancelledError:
        store.fail(task_id, {
            "code": "CANCELLED",
            "message": "任务已取消",
            "phase": "",
            "iteration": 0,
        })
    except Exception as exc:
        logger.exception("任务执行异常: task_id=%s", task_id)
        phase = ""
        if record.agent:
            phase = record.agent.task_state.current_phase.value
        store.fail(task_id, {
            "code": "INTERNAL_ERROR",
            "message": str(exc),
            "phase": phase,
            "iteration": record.progress.get("iteration", 0),
        })


def _inject_api_mode_prompt(agent) -> None:
    """在 Agent 消息历史中注入 API 端到端模式系统指令。"""
    from src.agent.message import Message, MessageRole
    api_mode_msg = Message(role=MessageRole.SYSTEM, content=API_MODE_SYSTEM_PROMPT)
    agent.state.add_message(api_mode_msg)
    agent.task_state.append_message(api_mode_msg)


def _force_output_prompt() -> str:
    """当连续停住超过阈值时，强制模型直接进入最终输出。"""
    return (
        "【系统强制指令】你已经连续多轮未调用任何工具也未产出最终方案。\n"
        "当前处于 API 无人值守模式，不允许等待用户。\n"
        "请立即基于目前已有的全部信息（即使不完整），直接输出完整的 7 章节标准化应急指挥方案。\n"
        "对于缺失的信息，在对应章节写明'待现场确认'并给出多种情景处置建议。\n"
        "在回答末尾附上 agent_control，设置 final_output=true。"
    )


async def _run_agent_loop(
    task_id: str,
    store: TaskStore,
    agent,
    record: TaskRecord,
) -> None:
    """Agent 端到端主循环：自动调用工具 → 自动推进阶段 → Pipeline 输出。"""
    from src.agent.task_state import TaskPhase
    from src.agent.message import Message, MessageRole

    incident_description = record.request["incident_description"]
    agent.start_new_turn(incident_description)

    iteration = 0
    called_tools_history: List[str] = []
    called_tools_set: set[str] = set()
    consecutive_no_tool_rounds = 0  # 连续无工具调用计数

    while iteration < agent.max_iterations:
        iteration += 1

        # 检查取消
        if record.cancel_event.is_set():
            store.fail(task_id, {
                "code": "CANCELLED",
                "message": "任务已取消",
                "phase": agent.task_state.current_phase.value,
                "iteration": iteration,
            })
            return

        store.update_progress(
            task_id,
            phase=agent.task_state.current_phase.value,
            iteration=iteration,
            current_action=f"第 {iteration} 轮推理中",
        )

        # 获取消息和工具定义
        messages = agent.get_runtime_messages()
        tool_defs = [t.to_openai_format() for t in agent.get_active_tools()]

        # 调用 LLM（同步调用，放到线程池避免阻塞事件循环）
        try:
            response = await asyncio.to_thread(
                agent.provider.chat, messages, tools=tool_defs or None,
            )
        except Exception as exc:
            logger.error("LLM 调用失败: task_id=%s, error=%s", task_id, exc)
            store.fail(task_id, {
                "code": "LLM_ERROR",
                "message": str(exc),
                "phase": agent.task_state.current_phase.value,
                "iteration": iteration,
            })
            return

        # ── 有工具调用 → 重置停住计数 ──
        if response.tool_calls:
            consecutive_no_tool_rounds = 0
            tool_call = response.tool_calls[0]

            # 重复工具调用检测
            if tool_call.name in called_tools_set:
                skip_msg = Message(
                    role=MessageRole.ASSISTANT,
                    content=f"（工具 {tool_call.name} 已经调用过，跳过重复调用）",
                )
                agent.state.add_message(skip_msg)
                continue

            # 记录 assistant message
            assistant_msg = Message(
                role=MessageRole.ASSISTANT,
                content=response.content or "",
                tool_calls=[tool_call],
            )
            agent.state.add_message(assistant_msg)
            called_tools_set.add(tool_call.name)
            called_tools_history.append(tool_call.name)

            store.update_progress(
                task_id,
                current_action=f"正在调用工具: {tool_call.name}",
                tools_called=list(called_tools_history),
            )

            # 执行工具（同步，放线程池）
            try:
                tool_result = await asyncio.to_thread(
                    agent._execute_tool, tool_call,
                )
                tool_msg = Message(
                    role=MessageRole.TOOL,
                    content=tool_result,
                    tool_call_id=tool_call.id,
                )
                agent.state.add_message(tool_msg)
                agent.task_state.append_message(tool_msg)
                agent.after_tool_execution(tool_call.name, tool_call.arguments, tool_result)

            except Exception as exc:
                logger.error("工具执行失败: tool=%s, error=%s", tool_call.name, exc)
                error_msg = Message(
                    role=MessageRole.TOOL,
                    content=f"工具执行失败: {exc}",
                    tool_call_id=tool_call.id,
                )
                agent.state.add_message(error_msg)
                agent.task_state.append_message(error_msg)
                agent.after_tool_execution(
                    tool_call.name, tool_call.arguments,
                    result="", success=False, error_message=str(exc),
                )

            # 插入分析指令
            analysis_msg = agent.build_post_tool_analysis_message(tool_call.name)
            agent.state.add_message(analysis_msg)
            agent.task_state.append_message(analysis_msg)

            store.update_progress(
                task_id,
                current_action=f"已调用 {tool_call.name}，分析结果中",
                tools_called=list(called_tools_history),
            )
            continue

        # ── 无工具调用 → 解析控制块 ──
        consecutive_no_tool_rounds += 1
        control = agent.parse_assistant_control(response.content)

        # API 模式：在 apply 之前强制禁用所有用户交互，
        # 防止 Agent 进入 WAITING_USER 状态浪费迭代
        control.needs_user_input = False
        control.awaiting_confirmation = False

        agent.apply_assistant_control(control)
        visible = agent.strip_control_block(response.content)

        # 记录 assistant message
        assistant_msg = Message(role=MessageRole.ASSISTANT, content=visible)
        agent.state.add_message(assistant_msg)
        agent.task_state.append_message(assistant_msg)

        # ── 判断是否进入最终输出 ──
        # 除了显式 final_output / OUTPUT 阶段，还检测模型是否已经
        # 在文本中直接输出了完整 7 章节方案结构
        from web_app import has_standard_plan_structure
        is_final = (
            control.final_output
            or agent.task_state.current_phase in {TaskPhase.OUTPUT, TaskPhase.OUTPUT_COMPLETE}
            or has_standard_plan_structure(visible)
        )

        if is_final:
            store.update_progress(task_id, current_action="正在生成最终方案（章节化流水线）")
            await _run_final_pipeline(task_id, store, agent, record, visible)
            return

        # ── 连续停住超过阈值 → 强制进入 Pipeline ──
        if consecutive_no_tool_rounds >= MAX_CONSECUTIVE_STALLS:
            logger.warning(
                "连续 %d 轮无工具调用，强制进入最终输出: task_id=%s",
                consecutive_no_tool_rounds, task_id,
            )
            store.update_progress(task_id, current_action="连续停住，强制生成最终方案")

            # 最后给模型一次机会：注入强制输出指令
            force_msg = Message(role=MessageRole.SYSTEM, content=_force_output_prompt())
            agent.state.add_message(force_msg)
            agent.task_state.append_message(force_msg)

            try:
                force_response = await asyncio.to_thread(
                    agent.provider.chat,
                    agent.get_runtime_messages(),
                    tools=None,  # 不给工具，强制纯文本输出
                )
                seed = agent.strip_control_block(force_response.content or "")
            except Exception:
                seed = ""

            store.update_progress(task_id, current_action="正在生成最终方案（章节化流水线）")
            await _run_final_pipeline(task_id, store, agent, record, seed)
            return

        # ── DeepSeek 原始 tool call token 泄漏检测 ──
        # 模型有时会把内部 special token 当文本输出，不是真正的工具调用
        _LEAKED_TOKENS = ("<｜tool▁calls▁begin｜>", "<｜tool▁call▁begin｜>", "<｜tool▁sep｜>", "<｜tool▁call▁end｜>", "<｜tool▁calls▁end｜>")
        if any(tok in visible for tok in _LEAKED_TOKENS):
            logger.warning("检测到模型泄漏 tool call special token，视为停住态: task_id=%s", task_id)
            # 清理掉泄漏 token 后的文本对模型没有价值，直接注入重试指令
            push_msg = Message(
                role=MessageRole.SYSTEM,
                content=(
                    "【系统纠正】你刚才把内部 tool call 控制符当文本输出了，这不是有效的工具调用。\n"
                    "如果你需要调用工具，请通过正常的 function calling 机制发起，不要在文本中输出 <｜tool▁calls▁begin｜> 等标记。\n"
                    "请立即重新执行：调用对应工具，或直接输出最终方案并设置 final_output=true。"
                ),
            )
            agent.state.add_message(push_msg)
            agent.task_state.append_message(push_msg)
            store.update_progress(task_id, current_action="检测到 token 泄漏，自动重试中")
            continue

        # ── 停住态 / 占位语检测 → 直接注入推进指令 ──
        from web_app import (
            looks_like_progress_only_response,
            detect_stalled_response,
            contains_nonexistent_execution_claim,
            build_no_execution_claim_prompt,
        )

        if contains_nonexistent_execution_claim(visible):
            retry_msg = Message(role=MessageRole.SYSTEM, content=build_no_execution_claim_prompt())
            agent.state.add_message(retry_msg)
            agent.task_state.append_message(retry_msg)
            store.update_progress(task_id, current_action="检测到虚构执行表述，自动重试中")
            continue

        if looks_like_progress_only_response(visible) or detect_stalled_response(visible):
            push_msg = Message(
                role=MessageRole.SYSTEM,
                content=(
                    "【系统纠正】不要停在说明态。当前是 API 无人值守模式。\n"
                    "请立即执行下一步：如果还需要信息就调用对应工具；"
                    "如果信息足够就直接输出完整最终方案并设置 final_output=true。"
                ),
            )
            agent.state.add_message(push_msg)
            agent.task_state.append_message(push_msg)
            store.update_progress(task_id, current_action="检测到停住态，自动推进中")
            continue

        # 普通中间输出，继续下一轮
        continue

    # 超过最大迭代 → 强制进入 Pipeline
    store.update_progress(task_id, current_action="已达最大迭代次数，强制生成最终方案")
    try:
        await _run_final_pipeline(task_id, store, agent, record, "")
    except Exception:
        store.fail(task_id, {
            "code": "MAX_ITERATIONS",
            "message": f"Agent 迭代超过上限 ({agent.max_iterations})，无法完成任务",
            "phase": agent.task_state.current_phase.value,
            "iteration": iteration,
        })


# ── 关键工具自动兜底（API 模式与 web_app._auto_call_missing_critical_tools 等价）

# 事件类型 → 默认所需物资类别
_TYPE_TO_REQUIRED_CATEGORIES = {
    "交通事故": ["WARNING", "RESCUE", "VEHICLE", "PPE", "COMMS"],
    "危化品泄漏": ["WARNING", "PPE", "FIRE", "RESCUE", "COMMS"],
    "火灾": ["FIRE", "WARNING", "PPE", "RESCUE", "COMMS"],
    "地质灾害": ["WARNING", "RESCUE", "TOOL", "VEHICLE", "COMMS"],
    "洪涝": ["WARNING", "RESCUE", "MATERIAL", "VEHICLE", "COMMS"],
}
_DEFAULT_REQUIRED_CATEGORIES = ["WARNING", "RESCUE", "VEHICLE", "PPE", "COMMS"]

# 资源搜索半径自适应：50km 没结果就扩 100、200、500
_RESOURCE_SEARCH_RADII_KM = (50, 100, 200, 500)


def _tool_called_successfully(agent, tool_name: str) -> bool:
    return any(
        record.tool_name == tool_name and record.success
        for record in agent.task_state.tool_call_log
    )


def _count_resources_by_type(agent, resource_type: str = "") -> int:
    """统计 task_state.available_resources 里指定类型的数量。'' 表示总数。"""
    if not resource_type:
        return len(agent.task_state.available_resources)
    return sum(
        1 for r in agent.task_state.available_resources
        if r.get("type") == resource_type
    )


async def _ensure_critical_tools_called(agent) -> None:
    """生成最终方案前，确保关键工具都被调过；模型跳过的由系统自动补上。

    覆盖：
    1. geocode_address: 缺坐标就根据 location_text 自动定位
    2. search_emergency_resources: 缺资源就按事件类型自动搜，半径 50/100/200/500 自适应直到搜出非零
    3. optimize_dispatch_plan: 资源齐了就自动出梯队方案
    4. search_experts: 缺专家就按事件类型搜，命中 0 时 fallback 到通用关键词

    所有自动调用失败都只打 warn 不抛异常，不阻塞主流程。
    """
    from src.agent.message import Message, MessageRole

    incident = agent.task_state.incident_info

    # ─── 1. geocode_address ───
    coords = incident.location_coords or {}
    if not coords.get("longitude") or not coords.get("latitude"):
        if incident.location_text and "geocode_address" in agent.tools:
            try:
                tool = agent.tools["geocode_address"]
                logger.info("[兜底] geocode_address: address=%s", incident.location_text)
                result = await asyncio.to_thread(tool.execute, address=incident.location_text)
                tool_msg = Message(role=MessageRole.TOOL, content=result, tool_call_id="auto_geocode")
                agent.state.add_message(tool_msg)
                agent.task_state.append_message(tool_msg)
                agent.after_tool_execution("geocode_address", {"address": incident.location_text}, result)
                coords = agent.task_state.incident_info.location_coords or {}
                logger.info("[兜底] geocode 完成: coords=%s", coords)
            except Exception as e:
                logger.warning("[兜底] geocode_address 失败: %s", e)

    lon = coords.get("longitude")
    lat = coords.get("latitude")

    # ─── 2. search_emergency_resources（半径自适应，至少凑足 5 条非专家资源）───
    if (
        "search_emergency_resources" in agent.tools
        and not _tool_called_successfully(agent, "search_emergency_resources")
        and lon is not None and lat is not None
    ):
        required_cats = _TYPE_TO_REQUIRED_CATEGORIES.get(
            incident.incident_type or "", _DEFAULT_REQUIRED_CATEGORIES,
        )
        tool = agent.tools["search_emergency_resources"]
        min_resource_count = 5  # 最小资源条数，少于此数继续扩半径直到拉满最大半径
        for radius in _RESOURCE_SEARCH_RADII_KM:
            try:
                logger.info("[兜底] search_emergency_resources: radius=%skm, cats=%s", radius, required_cats)
                result = await asyncio.to_thread(
                    tool.execute,
                    longitude=lon, latitude=lat,
                    required_categories=required_cats,
                    radius_km=radius,
                )
                tool_msg = Message(role=MessageRole.TOOL, content=result, tool_call_id=f"auto_search_resources_r{radius}")
                agent.state.add_message(tool_msg)
                agent.task_state.append_message(tool_msg)
                agent.after_tool_execution(
                    "search_emergency_resources",
                    {"longitude": lon, "latitude": lat, "required_categories": required_cats, "radius_km": radius},
                    result,
                )
                # 凑够 min_resource_count 条才停，否则继续扩
                non_expert_count = sum(
                    1 for r in agent.task_state.available_resources
                    if r.get("type") != "expert"
                )
                if non_expert_count >= min_resource_count:
                    logger.info("[兜底] 资源搜索达标，命中 %d 条（radius=%skm，阈值=%d）",
                                non_expert_count, radius, min_resource_count)
                    break
                else:
                    logger.info("[兜底] radius=%skm 命中 %d 条，未达阈值 %d，继续扩",
                                radius, non_expert_count, min_resource_count)
            except Exception as e:
                logger.warning("[兜底] search_emergency_resources(radius=%s) 失败: %s", radius, e)

    # ─── 3. optimize_dispatch_plan（资源已搜到则补出梯队）───
    if (
        "optimize_dispatch_plan" in agent.tools
        and not _tool_called_successfully(agent, "optimize_dispatch_plan")
        and _tool_called_successfully(agent, "search_emergency_resources")
    ):
        try:
            tool = agent.tools["optimize_dispatch_plan"]
            logger.info("[兜底] optimize_dispatch_plan")
            result = await asyncio.to_thread(tool.execute, required_categories=[])
            tool_msg = Message(role=MessageRole.TOOL, content=result, tool_call_id="auto_optimize_dispatch")
            agent.state.add_message(tool_msg)
            agent.task_state.append_message(tool_msg)
            agent.after_tool_execution("optimize_dispatch_plan", {}, result)
            logger.info("[兜底] optimize_dispatch_plan 成功")
        except Exception as e:
            logger.warning("[兜底] optimize_dispatch_plan 失败: %s", e)

    # ─── 4. search_experts（确保有 3-5 位专家）───
    if (
        "search_experts" in agent.tools
        and not _tool_called_successfully(agent, "search_experts")
    ):
        # 第一轮：用事件类型关键词
        keywords = [
            item for item in [
                incident.incident_type,
                incident.scene_type,
                incident.disaster_type,
                "交通安全",
                "应急管理",
            ] if item
        ] or ["交通安全", "应急管理"]

        tool = agent.tools["search_experts"]
        try:
            logger.info("[兜底] search_experts: keywords=%s", keywords)
            result = await asyncio.to_thread(
                tool.execute,
                keywords=keywords,
                incident_type=incident.incident_type or "交通突发事件",
                longitude=lon, latitude=lat,
                max_results=5,
            )
            tool_msg = Message(role=MessageRole.TOOL, content=result, tool_call_id="auto_search_experts")
            agent.state.add_message(tool_msg)
            agent.task_state.append_message(tool_msg)
            agent.after_tool_execution("search_experts", {"keywords": keywords}, result)

            expert_count = _count_resources_by_type(agent, "expert")
            logger.info("[兜底] 第一轮 search_experts 命中 %d 位", expert_count)

            # 第二轮兜底：命中 0 时用最通用的关键词再搜一次
            if expert_count == 0:
                fallback_keywords = ["交通安全", "应急管理", "安全管理", "公路", "应急"]
                logger.info("[兜底] 第一轮无命中，fallback 关键词: %s", fallback_keywords)
                result = await asyncio.to_thread(
                    tool.execute,
                    keywords=fallback_keywords,
                    max_results=5,
                )
                tool_msg = Message(role=MessageRole.TOOL, content=result, tool_call_id="auto_search_experts_fallback")
                agent.state.add_message(tool_msg)
                agent.task_state.append_message(tool_msg)
                agent.after_tool_execution("search_experts", {"keywords": fallback_keywords}, result)
                expert_count = _count_resources_by_type(agent, "expert")
                logger.info("[兜底] fallback 命中 %d 位", expert_count)
        except Exception as e:
            logger.warning("[兜底] search_experts 失败: %s", e)


async def _run_final_pipeline(
    task_id: str,
    store: TaskStore,
    agent,
    record: TaskRecord,
    seed_plan: str,
) -> None:
    """执行 FinalPlanPipeline + FinalPlanReviewer 生成最终方案。"""
    from src.agent.final_plan_pipeline import FinalPlanPipeline
    from src.agent.final_plan_reviewer import FinalPlanReviewer

    # ★ 关键兜底：确保 search_resources / search_experts / optimize_dispatch_plan 都被调过
    store.update_progress(task_id, current_action="正在补齐关键工具调用（资源/专家）")
    try:
        await _ensure_critical_tools_called(agent)
    except Exception as exc:
        logger.warning("关键工具兜底过程异常（继续生成方案）: %s", exc)

    review_provider = _build_review_provider(record.request.get("config"))
    pipeline = FinalPlanPipeline(review_provider)

    store.update_progress(task_id, pipeline_status="generating_sections")

    # Pipeline 生成（同步，放线程池）
    try:
        pipeline_result = await asyncio.to_thread(
            pipeline.generate,
            agent.task_state,
            seed_plan=seed_plan,
        )
    except Exception as exc:
        logger.exception("Pipeline 生成失败: task_id=%s", task_id)
        store.fail(task_id, {
            "code": "PIPELINE_ERROR",
            "message": str(exc),
            "phase": agent.task_state.current_phase.value,
            "iteration": record.progress.get("iteration", 0),
        })
        return

    final_markdown = pipeline_result.final_markdown
    review_result = None

    # 规范化 Markdown
    from web_app import normalize_final_markdown_for_display
    final_markdown = normalize_final_markdown_for_display(final_markdown)

    # 组装结果
    from src.utils.structured_sections import normalize_structured_sections

    result = {
        "plan_markdown": final_markdown,
        "sections": pipeline_result.section_texts,
        "structured_sections": normalize_structured_sections(pipeline_result.structured_sections),
        "review": review_result.raw_payload if review_result else None,
    }
    process_data = _collect_process_data(agent)

    store.complete(task_id, result=result, process_data=process_data)
