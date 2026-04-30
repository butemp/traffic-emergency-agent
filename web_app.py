"""
交通应急Agent - Web界面

基于Chainlit构建的美观AI助手界面。

运行方式:
    chainlit run web_app.py -h 0.0.0.0 -p 8000
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import chainlit as cl
from dotenv import load_dotenv
from chainlit.input_widget import TextInput

# 添加src目录到路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.agent import Agent, Message, TaskPhase
from src.agent.final_plan_reviewer import FinalPlanReviewer
from src.agent.message import MessageRole
from src.providers import OpenAIProvider
from src.providers.defaults import (
    DEFAULT_CAPTION_MODEL,
    DEFAULT_TEXT_API_KEY,
    DEFAULT_TEXT_BASE_URL,
    DEFAULT_TEXT_MAX_TOKENS,
    DEFAULT_TEXT_MODEL,
)
from src.tools import (
    QueryRegulations,
    QueryHistoricalCases,
    GetEmergencyPlan,
    EvaluateIncidentSeverity,
    RiskAssessment,
    MediaCaption,
    SearchEmergencyResources,
    OptimizeDispatchPlan,
    SearchExperts,
    SearchMapResources, # 导入新工具
    CheckTrafficStatus,
    GetWeatherByLocation,
    GeocodeAddress,
    ReverseGeocode,
    SearchNearbyPOIs,
    PlanDispatchRoutes,
    GaodeConfig
)
from src.rag import QueryRAG, RAGConfig, BALANCED_RAG_CONFIG
from src.emergency_plans import EmergencyPlanService
from src.resource_dispatch import ResourceDispatchEngine

# 加载环境变量
load_dotenv()

SESSION_RUNTIME_CONFIG_KEY = "runtime_model_config"
SETTING_OPENAI_API_KEY = "OPENAI_API_KEY"
SETTING_OPENAI_MODEL = "OPENAI_MODEL"
SETTING_OPENAI_BASE_URL = "OPENAI_BASE_URL"
STALL_CONTINUE_REPLY = "请继续行动，直接执行下一步需要的工具；不要停在说明上。"
MAX_FINAL_REVIEW_ROUNDS = 3


def default_runtime_config() -> Dict[str, str]:
    """返回当前会话的默认模型配置。"""
    return {
        # Web 端默认统一走项目内配置，避免服务器残留 OPENAI_API_KEY/DASHSCOPE_API_KEY
        # 把会话默认值悄悄切回其他模型。用户仍可在前端设置面板里手动覆盖。
        SETTING_OPENAI_API_KEY: DEFAULT_TEXT_API_KEY or "",
        SETTING_OPENAI_MODEL: DEFAULT_TEXT_MODEL,
        SETTING_OPENAI_BASE_URL: DEFAULT_TEXT_BASE_URL,
    }


def normalize_runtime_config(raw_config: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """对前端提交的模型配置做归一化处理。"""
    defaults = default_runtime_config()
    raw_config = raw_config or {}

    api_key = str(raw_config.get(SETTING_OPENAI_API_KEY, defaults[SETTING_OPENAI_API_KEY]) or "").strip()
    model = str(raw_config.get(SETTING_OPENAI_MODEL, defaults[SETTING_OPENAI_MODEL]) or "").strip()
    base_url = str(raw_config.get(SETTING_OPENAI_BASE_URL, defaults[SETTING_OPENAI_BASE_URL]) or "").strip()

    return {
        SETTING_OPENAI_API_KEY: api_key,
        SETTING_OPENAI_MODEL: model or defaults[SETTING_OPENAI_MODEL],
        SETTING_OPENAI_BASE_URL: base_url,
    }


def get_runtime_config() -> Dict[str, str]:
    """获取当前会话生效的模型配置。"""
    stored_config = cl.user_session.get(SESSION_RUNTIME_CONFIG_KEY)
    config = normalize_runtime_config(stored_config)
    cl.user_session.set(SESSION_RUNTIME_CONFIG_KEY, config)
    return config


def build_provider_bundle(runtime_config: Dict[str, str]) -> Dict[str, OpenAIProvider]:
    """根据当前会话配置构建聊天、评估和多模态 provider。"""
    api_key = runtime_config.get(SETTING_OPENAI_API_KEY, "")
    base_url = runtime_config.get(SETTING_OPENAI_BASE_URL, "") or os.getenv("OPENAI_BASE_URL") or DEFAULT_TEXT_BASE_URL
    chat_model = runtime_config.get(SETTING_OPENAI_MODEL, "") or os.getenv("OPENAI_MODEL") or DEFAULT_TEXT_MODEL
    caption_model = os.getenv("CAPTION_MODEL") or DEFAULT_CAPTION_MODEL
    caption_api_key = os.getenv("CAPTION_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or api_key
    caption_base_url = os.getenv("CAPTION_BASE_URL") or None
    evaluation_model = os.getenv("EVAL_MODEL") or chat_model
    evaluation_base_url = os.getenv("EVAL_BASE_URL") or base_url

    return {
        "chat": OpenAIProvider(
            api_key=api_key,
            base_url=base_url,
            model=chat_model,
            max_tokens=DEFAULT_TEXT_MAX_TOKENS,
            provider="auto",
        ),
        "caption": OpenAIProvider(
            api_key=caption_api_key,
            base_url=caption_base_url,
            model=caption_model,
            provider="auto",
        ),
        "evaluation": OpenAIProvider(
            api_key=api_key,
            base_url=evaluation_base_url,
            model=evaluation_model,
            max_tokens=DEFAULT_TEXT_MAX_TOKENS,
            provider="auto",
        ),
    }


def apply_runtime_config_to_agent(agent: Agent, runtime_config: Dict[str, str]) -> None:
    """将前端配置应用到当前会话中的 Agent 和相关工具。"""
    providers = build_provider_bundle(runtime_config)
    agent.provider = providers["chat"]

    for tool in agent.tools.values():
        if isinstance(tool, MediaCaption):
            tool.provider = providers["caption"]
            tool.model = providers["caption"].model
        elif isinstance(tool, EvaluateIncidentSeverity):
            tool.provider = providers["evaluation"]
            tool.model = providers["evaluation"].model
            tool.evaluator.provider = providers["evaluation"]
        elif isinstance(tool, RiskAssessment):
            tool.provider = providers["evaluation"]


async def send_runtime_settings_panel() -> Dict[str, str]:
    """发送前端可编辑的模型设置面板。"""
    current = get_runtime_config()

    settings = await cl.ChatSettings(
        [
            TextInput(
                id=SETTING_OPENAI_API_KEY,
                label="OPENAI_API_KEY",
                initial=current[SETTING_OPENAI_API_KEY],
                placeholder="sk-...",
                description="当前会话使用的 API Key。默认已内置项目文本模型 Key；如需切换账号，可在此覆盖。",
            ),
            TextInput(
                id=SETTING_OPENAI_MODEL,
                label="OPENAI_MODEL",
                initial=current[SETTING_OPENAI_MODEL],
                placeholder=DEFAULT_TEXT_MODEL,
                description="主对话模型名称。填写任意支持 OpenAI SDK 风格接口的模型名。",
            ),
            TextInput(
                id=SETTING_OPENAI_BASE_URL,
                label="OPENAI_BASE_URL",
                initial=current[SETTING_OPENAI_BASE_URL],
                placeholder=DEFAULT_TEXT_BASE_URL,
                description="可选。接 OpenAI 官方时可留空；接第三方 OpenAI-compatible 服务时填写其 Base URL。",
            ),
        ]
    ).send()

    normalized = normalize_runtime_config(settings)
    cl.user_session.set(SESSION_RUNTIME_CONFIG_KEY, normalized)
    return normalized

# ===== 配置 =====
# 设置页面信息
@cl.on_chat_start
async def on_chat_start():
    """会话开始时的初始化"""
    # 检查是否已经初始化过
    if cl.user_session.get("welcome_shown"):
        return

    runtime_config = await send_runtime_settings_panel()

    # 设置页面标题和描述
    base_url_text = runtime_config[SETTING_OPENAI_BASE_URL] or "OpenAI 默认地址"
    await cl.Message(
        content="🚗 **欢迎使用交通应急指挥助手**\n\n"
        "我可以帮助你：\n"
        "- 📋 查询法规、规则和应急预案\n"
        "- 📚 参考历史处置案例\n"
        "- 🔍 检索应急相关文档资料\n"
        "- ⚠️ 对应急方案进行风险评估\n"
        "- 🗺️ **地理信息查询**（地址转坐标、周边设施）\n"
        "- 🚦 **实时交通状况**（拥堵情况查询）\n"
        "- 🌤️ **天气查询**（实时天气和预报）\n\n"
        "当前会话模型配置：\n"
        f"- `OPENAI_MODEL`: `{runtime_config[SETTING_OPENAI_MODEL]}`\n"
        f"- `OPENAI_BASE_URL`: `{base_url_text}`\n\n"
        "如需切换模型或接入其他 OpenAI-compatible 服务，请点击输入框旁的设置按钮修改以上三项。",
        author="系统"
    ).send()

    # 标记欢迎消息已显示
    cl.user_session.set("welcome_shown", True)

    # 初始化Agent（每个会话创建一个）
    cl.user_session.set("agent_initialized", False)


def create_agent(runtime_config: Optional[Dict[str, str]] = None):
    """创建Agent实例"""
    import logging
    logger = logging.getLogger(__name__)

    runtime_config = normalize_runtime_config(runtime_config or get_runtime_config())
    providers = build_provider_bundle(runtime_config)
    # 设置高德API Key（如果环境变量中有配置）
    gaode_key = os.getenv("GAODE_API_KEY")
    if gaode_key:
        GaodeConfig.set_api_key(gaode_key)
        logger.info(f"高德API Key已配置: {gaode_key[:10]}...")

    provider = providers["chat"]
    caption_provider = providers["caption"]
    evaluation_provider = providers["evaluation"]
    base_url = runtime_config[SETTING_OPENAI_BASE_URL] or "default"

    logger.info(
        "当前会话模型配置: model=%s, base_url=%s",
        runtime_config[SETTING_OPENAI_MODEL],
        base_url,
    )

    # 创建工具列表
    tools = []
    dispatch_engine = None
    plan_service = None
    try:
        dispatch_engine = ResourceDispatchEngine()
        logger.info("ResourceDispatchEngine 初始化成功")
    except Exception as e:
        logger.warning(f"ResourceDispatchEngine 初始化失败: {e}")

    try:
        plan_service = EmergencyPlanService(data_dir="data/regulations/data")
        logger.info("EmergencyPlanService 初始化成功")
    except Exception as e:
        logger.warning(f"EmergencyPlanService 初始化失败: {e}")

    # 添加基础工具
    try:
        tools.append(QueryRegulations(data_path="data/regulations"))
        logger.info("QueryRegulations 工具加载成功")
    except Exception as e:
        logger.warning(f"QueryRegulations 工具加载失败: {e}")

    try:
        tools.append(QueryHistoricalCases(data_path="data/historical_cases"))
        logger.info("QueryHistoricalCases 工具加载成功")
    except Exception as e:
        logger.warning(f"QueryHistoricalCases 工具加载失败: {e}")

    try:
        tools.append(QueryRAG(data_dir="data/regulations/chunked_json", config=BALANCED_RAG_CONFIG))
        logger.info("QueryRAG 工具加载成功")
    except Exception as e:
        logger.warning(f"QueryRAG 工具加载失败: {e}")

    if plan_service is not None:
        try:
            tools.append(GetEmergencyPlan(plan_service=plan_service))
            logger.info("GetEmergencyPlan 工具加载成功")
        except Exception as e:
            logger.warning(f"GetEmergencyPlan 工具加载失败: {e}")

        try:
            tools.append(
                EvaluateIncidentSeverity(
                    provider=evaluation_provider,
                    plan_service=plan_service,
                )
            )
            logger.info("EvaluateIncidentSeverity 工具加载成功")
        except Exception as e:
            logger.warning(f"EvaluateIncidentSeverity 工具加载失败: {e}")

    # RiskAssessment 工具
    try:
        tools.append(RiskAssessment(provider=evaluation_provider, timeout=30))
        logger.info("RiskAssessment 工具加载成功")
    except Exception as e:
        logger.warning(f"RiskAssessment 工具加载失败: {e}")

    try:
        tools.append(
            MediaCaption(
                provider=caption_provider,
                timeout=60,
                model=caption_provider.model,
            )
        )
        logger.info("MediaCaption 工具加载成功")
    except Exception as e:
        logger.warning(f"MediaCaption 工具加载失败: {e}")

    # ===== 添加高德API工具 =====
    try:
        tools.append(CheckTrafficStatus())
        logger.info("CheckTrafficStatus 工具加载成功")
    except Exception as e:
        logger.warning(f"CheckTrafficStatus 工具加载失败: {e}")

    try:
        tools.append(GetWeatherByLocation())
        logger.info("GetWeatherByLocation 工具加载成功")
    except Exception as e:
        logger.warning(f"GetWeatherByLocation 工具加载失败: {e}")

    try:
        tools.append(GeocodeAddress())
        logger.info("GeocodeAddress 工具加载成功")
    except Exception as e:
        logger.warning(f"GeocodeAddress 工具加载失败: {e}")

    try:
        tools.append(ReverseGeocode())
        logger.info("ReverseGeocode 工具加载成功")
    except Exception as e:
        logger.warning(f"ReverseGeocode 工具加载失败: {e}")

    try:
        tools.append(SearchNearbyPOIs())
        logger.info("SearchNearbyPOIs 工具加载成功")
    except Exception as e:
        logger.warning(f"SearchNearbyPOIs 工具加载失败: {e}")

    try:
        tools.append(PlanDispatchRoutes())
        logger.info("PlanDispatchRoutes 工具加载成功")
    except Exception as e:
        logger.warning(f"PlanDispatchRoutes 工具加载失败: {e}")

    if dispatch_engine is not None:
        try:
            tools.append(SearchEmergencyResources(engine=dispatch_engine))
            logger.info("SearchEmergencyResources 工具加载成功")
        except Exception as e:
            logger.warning(f"SearchEmergencyResources 工具加载失败: {e}")

        try:
            tools.append(OptimizeDispatchPlan(engine=dispatch_engine))
            logger.info("OptimizeDispatchPlan 工具加载成功")
        except Exception as e:
            logger.warning(f"OptimizeDispatchPlan 工具加载失败: {e}")

    try:
        tools.append(SearchExperts(data_path="data/专家数据/expert_info.xls"))
        logger.info("SearchExperts 工具加载成功")
    except Exception as e:
        logger.warning(f"SearchExperts 工具加载失败: {e}")

    try:
        tools.append(SearchMapResources(data_dir="data/graph")) # 注册新工具
        logger.info("SearchMapResources 工具加载成功")
    except Exception as e:
        logger.warning(f"SearchMapResources 工具加载失败: {e}")

    # 创建Agent
    agent = Agent(
        provider=provider,
        tools=tools,
        max_iterations=10,  # 增加迭代次数，支持更复杂的工具调用链
        save_conversations=True,
        conversation_path="data/conversations"
    )

    return agent


def get_agent():
    """获取当前会话的Agent"""
    if not cl.user_session.get("agent_initialized"):
        agent = create_agent(get_runtime_config())
        cl.user_session.set("agent", agent)
        cl.user_session.set("agent_initialized", True)
        return agent
    return cl.user_session.get("agent")


@cl.on_settings_update
async def on_settings_update(settings: Dict[str, Any]):
    """处理前端模型设置更新，并立即作用到当前会话。"""
    runtime_config = normalize_runtime_config(settings)
    cl.user_session.set(SESSION_RUNTIME_CONFIG_KEY, runtime_config)

    existing_agent = cl.user_session.get("agent")
    try:
        if existing_agent is not None:
            apply_runtime_config_to_agent(existing_agent, runtime_config)
            cl.user_session.set("agent", existing_agent)
            cl.user_session.set("agent_initialized", True)
        else:
            cl.user_session.set("agent_initialized", False)
    except Exception as exc:
        cl.user_session.set("agent_initialized", False)
        await cl.Message(
            content=f"模型配置更新失败：{exc}",
            author="系统",
        ).send()
        return

    base_url_text = runtime_config[SETTING_OPENAI_BASE_URL] or "OpenAI 默认地址"
    await cl.Message(
        content=(
            "已更新当前会话模型配置：\n"
            f"- `OPENAI_MODEL`: `{runtime_config[SETTING_OPENAI_MODEL]}`\n"
            f"- `OPENAI_BASE_URL`: `{base_url_text}`\n"
            "下一条消息将按新配置执行。"
        ),
        author="系统",
    ).send()


def get_active_tool_definitions(agent: Agent):
    """根据当前阶段获取本轮应暴露给模型的工具定义。"""
    return [tool.to_openai_format() for tool in agent.get_active_tools()]


def get_user_visible_reply(agent: Agent, raw_content: str) -> str:
    """提取用户可见文本，去掉内部控制块。"""
    visible = agent.strip_control_block(raw_content)
    return visible.strip()


STANDARD_PLAN_SECTIONS = [
    "一、事件概述",
    "二、响应定级",
    "三、指挥架构",
    "四、预警发布",
    "五、处置行动方案",
    "六、资源调度方案",
    "七、信息报送与新闻发布",
    "八、风险提示与注意事项",
    "九、依据引用",
]


def agent_has_tool(agent: Agent, tool_name: str) -> bool:
    """判断当前 Agent 是否注册了指定工具。"""
    return tool_name in agent.tools


def has_standard_plan_structure(text: str) -> bool:
    """检查最终方案是否满足固定 9 章节结构。"""
    if not text:
        return False

    positions = []
    for heading in STANDARD_PLAN_SECTIONS:
        position = text.find(heading)
        if position < 0:
            return False
        positions.append(position)

    return positions == sorted(positions)


def contains_nonexistent_execution_claim(text: str) -> bool:
    """识别模型把建议动作说成已执行现实动作的情况。"""
    if not text:
        return False

    direct_markers = (
        "已执行的行动",
        "已通知",
        "已下达指令",
        "已启动应急响应",
        "已派遣",
        "已调派",
        "已联系",
        "已协调",
        "已通过系统向联系人",
    )
    if any(marker in text for marker in direct_markers):
        return True

    risky_patterns = (
        r"通知.{0,20}出发",
        r"要求.{0,20}立即前往",
        r"我将立即启动应急响应",
        r"我将优先派遣",
        r"我将立即在更小范围内重新搜索",
        r"我将立即启动资源优化",
    )
    return any(re.search(pattern, text) for pattern in risky_patterns)


def looks_like_progress_only_response(text: str) -> bool:
    """识别没有真正完成任务、只是在占位或虚构执行的回复。"""
    if not text:
        return False

    waiting_markers = (
        "请稍候",
        "请稍等",
        "稍后给出",
        "正在生成",
        "正在处理",
        "正在重新搜索",
        "系统正在生成",
    )
    execution_claim_markers = (
        "已执行的行动",
        "已通知",
        "已下达指令",
        "已启动应急响应",
    )

    if any(marker in text for marker in waiting_markers):
        return True

    if any(marker in text for marker in execution_claim_markers):
        return True

    return False


def detect_stalled_response(text: str) -> str:
    """识别“说明了下一步，但没有真正行动”的停住态回复。"""
    if not text:
        return ""

    normalized = text.strip()
    if not normalized or has_standard_plan_structure(normalized):
        return ""

    user_input_markers = ("请提供", "请补充", "请确认", "请选择", "是否确认")
    if any(marker in normalized for marker in user_input_markers):
        return ""

    if looks_like_progress_only_response(normalized):
        return "模型输出了进度说明或占位语，但没有真正调用工具，也没有给出最终方案。"

    planning_patterns = (
        r"下一步.{0,24}(调用|查询|搜索|评估|检索|生成|获取|推进|执行)",
        r"接下来.{0,24}(调用|查询|搜索|评估|检索|生成|获取|推进|执行)",
        r"随后.{0,24}(调用|查询|搜索|评估|检索|生成|获取|推进|执行)",
        r"然后.{0,24}(调用|查询|搜索|评估|检索|生成|获取|推进|执行)",
        r"我将.{0,28}(调用|查询|搜索|评估|检索|生成|获取|推进|优化|分析)",
        r"我会.{0,28}(调用|查询|搜索|评估|检索|生成|获取|推进|优化|分析)",
        r"将立即.{0,24}(调用|查询|搜索|评估|检索|生成|获取|推进|优化)",
    )
    if any(re.search(pattern, normalized) for pattern in planning_patterns):
        return "模型描述了下一步计划，但没有真正调用对应工具，也没有完成当前轮输出。"

    return ""


def build_stall_resume_question() -> str:
    """构造停住态下给用户的交互提示。"""
    return "检测到模型刚刚停在说明态。你可以选择让它继续行动，或补充新的 refine 信息后再继续推进。"


def build_stall_resume_reason(stalled_response: str, detected_reason: str) -> str:
    """格式化停住态原因说明。"""
    excerpt = " ".join((stalled_response or "").split())
    if len(excerpt) > 140:
        excerpt = excerpt[:137] + "..."

    base_reason = detected_reason or "模型刚刚没有真正执行下一步动作。"
    if excerpt:
        return f"{base_reason}\n停住回复摘录：{excerpt}"
    return base_reason


def build_intake_retry_prompt(agent: Agent) -> str:
    """当 INTAKE 未完成时，强制模型回到补问或更新逻辑。"""
    missing = agent.task_state.incident_info.missing_required_fields()
    missing_text = "、".join(missing) if missing else "无"
    return (
        "【系统纠正】当前仍处于 INTAKE 阶段，关键信息尚未完整。"
        f"缺失字段：{missing_text}。\n"
        "不要编造已经执行的现实动作，也不要用“请稍候/正在生成”结束本轮。\n"
        "请执行以下二选一：\n"
        "1. 如果信息仍不足，请直接向用户补问，最多 2 个问题，说明原因和期望格式，并在末尾附上 agent_control；\n"
        "2. 如果你能从上下文可靠补全缺失信息，请在 agent_control 的 incident_updates 中补全后继续推进。"
    )


def build_severity_retry_prompt(agent: Agent) -> str:
    """当 INTAKE 信息齐全但尚未完成预案定级时，强制模型先定级。"""
    incident = agent.task_state.incident_info
    summary = (
        f"事故类型={incident.incident_type or '未知'}；"
        f"位置={incident.location_text or agent.task_state.environment_info.formatted_address or '未知'}；"
        f"伤亡={incident.casualty_status or incident.casualties or '未知'}；"
        f"现场状态={incident.scene_status or '未知'}"
    )
    return (
        "【系统纠正】当前 4 项关键信息已经齐全，但 response_level 仍未判定。\n"
        f"当前摘要：{summary}\n"
        "请优先调用 evaluate_incident_severity 完成预案定级，不要直接跳到方案生成，也不要用普通说明语带过。\n"
        "定级完成后，再根据结果决定是继续补问还是进入 SITUATIONAL_AWARENESS。"
    )


def build_phase_transition_retry_prompt(agent: Agent) -> str:
    """当 INTAKE 已完成定级但模型未继续推进时，提醒其明确切换阶段。"""
    incident = agent.task_state.incident_info
    return (
        "【系统纠正】当前 INTAKE 已完成必要信息收集和预案定级，"
        f"response_level={incident.response_level or '待确认'}。\n"
        "请不要停留在概述性说明上。请执行以下二选一：\n"
        "1. 如果仍有真正影响后续处置的缺口信息，请补问，并附上 agent_control；\n"
        "2. 如果信息已足够，请明确切换到 SITUATIONAL_AWARENESS，并继续调用环境补全工具。"
    )


def build_no_placeholder_prompt() -> str:
    """提醒模型不要用占位语或虚构执行动作结束。"""
    return (
        "【系统纠正】不要输出“请稍候/正在生成/已通知出发/已下达指令”之类的占位语或执行口吻。\n"
        "你不能宣称已经通知队伍、启动真实行动或下达现实指令。\n"
        "请立即继续完成真正的下一步：\n"
        "- 需要信息就补问，并附上 agent_control；\n"
        "- 信息足够就调用工具；\n"
        "- 已完成就给出明确方案和 agent_control。"
    )


def build_no_execution_claim_prompt() -> str:
    """提醒模型不要把建议动作写成已执行现实动作。"""
    return (
        "【系统纠正】你刚才把建议动作写成了系统已经执行的现实动作，这是不允许的。\n"
        "当前系统只能做分析、检索、方案编排和建议，不会真实通知队伍、不会下达现实指令、不会自动派遣资源。\n"
        "请立即重写当前回复，遵守以下要求：\n"
        "1. 把“已通知/已下达/已派遣/已启动”改成“建议通知/拟派/建议启动/待人工联系”；\n"
        "2. 如果用户已经确认方案，可写“建议按以下清单执行，由人工值班人员联系相关资源”；\n"
        "3. 不要出现第一人称执行口吻，如“我将立即启动应急响应”“我将派遣某队伍”；\n"
        "4. 如果需要继续搜索或优化，请直接调用工具，而不是口头宣称系统已经在执行。\n"
        "请重写完整回复，并附上 agent_control。"
    )


def build_output_format_retry_prompt() -> str:
    """当最终方案未满足标准模板时，强制模型按模板重排。"""
    section_text = "\n".join(f"- {heading}" for heading in STANDARD_PLAN_SECTIONS)
    return (
        "【系统纠正】当前最终输出不符合应急指挥方案标准模板，不能直接结束。\n"
        "请重新输出一份标准化应急指挥方案，严格满足以下要求：\n"
        "1. 必须按以下 9 个固定章节、固定顺序输出：\n"
        f"{section_text}\n"
        "2. 一、事件概述 和 二、响应定级 必须用表格；\n"
        "3. 三、指挥架构 必须列出总指挥/副总指挥，并用表格展示工作组；\n"
        "4. 五、处置行动方案 必须拆成三个阶段，并在每个阶段用表格列出行动内容、责任单位、时间要求、预案依据；\n"
        "5. 三、指挥架构 必须覆盖应急管理、消防救援、公安交管、医疗救援、专家技术支持等关键角色；\n"
        "6. 五、处置行动方案 必须包含涉险人员二次排查、其他伤员排查、家属联络安抚和二次事故防范；\n"
        "7. 六、资源调度方案 必须按梯队展示，并补充资源来源单位/出发地、调度路径、预计到达、联系人电话和资源覆盖情况；\n"
        "8. 九、依据引用 必须汇总预案名称、引用章节、引用内容摘要；\n"
        "9. 全文只能写建议性表述，不能写成“已通知/已派遣/已下达指令/已启动应急响应”；\n"
        "10. 资源类别只能用中文名称，不能直接输出 WARNING、PPE、SIGN、VEHICLE 等内部编码；\n"
        "11. 如已有专家检索结果，必须在指挥架构或专家技术支持中写出专家姓名、单位、专业方向和建议支持方式；\n"
        "12. 缺失信息请明确写“暂未获取”或“待现场确认”，不要省略章节。\n"
        "请直接输出重排后的最终方案，并附上 agent_control，final_output=true。"
    )


def collect_final_plan_guardrail_issues(text: str, agent: Optional[Agent] = None) -> list[str]:
    """收集最终方案的硬性校验问题。"""
    issues: list[str] = []

    if not text.strip():
        issues.append("最终方案内容为空。")
        return issues

    if contains_nonexistent_execution_claim(text):
        issues.append("方案中出现了把建议动作写成已执行现实动作的表述。")

    if not has_standard_plan_structure(text):
        issues.append("方案未满足固定 9 章节结构或章节顺序不正确。")

    internal_category_codes = (
        "WARNING",
        "PPE",
        "SIGN",
        "VEHICLE",
        "RESCUE",
        "COMMS",
        "DEICE",
        "MATERIAL",
    )
    leaked_codes = [
        code for code in internal_category_codes
        if re.search(rf"(?<![A-Za-z]){code}(?![A-Za-z])", text)
    ]
    if leaked_codes:
        issues.append(
            "资源类别仍包含内部英文编码，应改为中文名称："
            + "、".join(leaked_codes)
        )

    if agent is not None:
        issues.extend(collect_pre_output_tool_issues(agent))

        expert_names = [
            str(resource.get("name") or "")
            for resource in agent.task_state.available_resources
            if resource.get("type") == "expert" and resource.get("name")
        ]
        if expert_names and not any(name in text for name in expert_names[:5]):
            issues.append("已检索到专家，但最终方案没有写出专家姓名、单位、专业方向和建议支持方式。")

        route_notes = agent.task_state.environment_info.additional_notes
        if route_notes and "调度路径" not in text and "高德" not in text:
            issues.append("已完成调度路线规划，但最终方案没有展示高德路线、预计到达或调度路径。")

    return issues


def _tool_called_successfully(agent: Agent, tool_name: str) -> bool:
    """判断指定工具是否至少成功执行过一次。"""
    return any(
        record.tool_name == tool_name and record.success
        for record in agent.task_state.tool_call_log
    )


def _clean_float(value: Any) -> Optional[float]:
    """把工具结果里的坐标字段安全转成 float。"""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _incident_coordinates(agent: Agent) -> Optional[Dict[str, float]]:
    """获取事故点坐标。"""
    coords = agent.task_state.incident_info.location_coords or {}
    longitude = _clean_float(coords.get("longitude"))
    latitude = _clean_float(coords.get("latitude"))
    if longitude is None or latitude is None:
        return None
    return {"longitude": longitude, "latitude": latitude}


def _route_origin_candidates(agent: Agent, limit: int = 8) -> list[Dict[str, Any]]:
    """从内部资源和外部 POI 中整理可用于高德路径规划的出发点。"""
    origins: list[Dict[str, Any]] = []
    seen: set[tuple[str, float, float]] = set()

    def append_origin(item: Dict[str, Any]) -> None:
        longitude = _clean_float(item.get("longitude"))
        latitude = _clean_float(item.get("latitude"))
        name = str(item.get("name") or item.get("resource_name") or "").strip()
        if not name or longitude is None or latitude is None:
            return

        key = (name, round(longitude, 6), round(latitude, 6))
        if key in seen:
            return
        seen.add(key)
        origins.append(
            {
                "name": name,
                "resource_type": item.get("resource_type") or item.get("type") or "应急资源",
                "address": item.get("address") or item.get("origin_address") or item.get("source_org") or "",
                "longitude": longitude,
                "latitude": latitude,
            }
        )

    for resource in agent.task_state.available_resources:
        if resource.get("type") == "expert":
            continue
        append_origin(resource)
        if len(origins) >= limit:
            return origins[:limit]

    for poi in agent.task_state.environment_info.nearby_pois:
        location = str(poi.get("location") or "")
        if "," not in location:
            continue
        longitude_text, latitude_text = location.split(",", 1)
        append_origin(
            {
                "name": poi.get("name", ""),
                "resource_type": poi.get("type") or "外部公共资源",
                "address": poi.get("address", ""),
                "longitude": longitude_text,
                "latitude": latitude_text,
            }
        )
        if len(origins) >= limit:
            break

    return origins[:limit]


def collect_pre_output_tool_issues(agent: Agent) -> list[str]:
    """最终输出前必须补齐的工具链缺口。"""
    issues: list[str] = []

    if agent_has_tool(agent, "search_experts") and not _tool_called_successfully(agent, "search_experts"):
        issues.append("尚未调用 search_experts 检索专家库，最终方案不能直接缺少专家技术支持。")

    has_route_inputs = bool(_incident_coordinates(agent) and _route_origin_candidates(agent))
    if (
        agent_has_tool(agent, "plan_dispatch_routes")
        and has_route_inputs
        and not _tool_called_successfully(agent, "plan_dispatch_routes")
    ):
        issues.append("已有事故点坐标和可调度资源坐标，但尚未调用 plan_dispatch_routes 做高德路径规划。")

    return issues


def build_pre_output_tool_prompt(agent: Agent, issues: list[str]) -> str:
    """构造最终输出前的强制补工具提示。"""
    incident = agent.task_state.incident_info
    coords = _incident_coordinates(agent)
    origins = _route_origin_candidates(agent)
    keywords = [
        item
        for item in [
            incident.incident_type,
            incident.scene_type,
            incident.disaster_type,
            "交通安全",
            "应急管理",
        ]
        if item
    ]

    lines = [
        "【系统纠正】当前不能直接输出最终方案，因为最终方案缺少必要的专家或路径依据。",
        "请不要重写方案，也不要用文字解释带过；请先调用缺失工具补齐数据，再进入最终输出。",
        "",
        "缺口：",
        *[f"- {issue}" for issue in issues],
        "",
        "请按需要调用：",
        f"- search_experts：keywords={json.dumps(keywords or ['交通安全', '应急管理'], ensure_ascii=False)}, incident_type={incident.incident_type or '交通突发事件'}",
    ]

    if coords and origins:
        lines.extend(
            [
                "- plan_dispatch_routes：使用下面的 destination 和 origins，不要自行编造路线。",
                f"destination_longitude={coords['longitude']}",
                f"destination_latitude={coords['latitude']}",
                f"destination_name={json.dumps(incident.location_text or '事故现场', ensure_ascii=False)}",
                "origins=" + json.dumps(origins, ensure_ascii=False, indent=2),
            ]
        )
    else:
        lines.append("- 如果事故点还没有坐标，请先调用 geocode_address；如资源缺少坐标，最终方案中必须写“路线暂未规划，需由人工调度平台确认”。")

    return "\n".join(lines)


def build_final_review_retry_prompt(
    candidate_text: str,
    review_result: Any,
    guardrail_issues: list[str],
    attempt: int,
) -> str:
    """构造最终方案审核未通过时给主模型的重写提示。"""
    issue_lines = [f"- {item}" for item in guardrail_issues]
    issue_lines.extend(f"- {item}" for item in (review_result.issues or []))
    advice_lines = [f"- {item}" for item in (review_result.revision_advice or [])]

    issue_block = "\n".join(issue_lines) if issue_lines else "- 审核器未给出明确问题，但当前版本仍未通过审核。"
    advice_block = "\n".join(advice_lines) if advice_lines else "- 请严格按标准模板重写，并补齐缺失内容。"

    return (
        f"【最终方案审核未通过，第 {attempt} 轮重写】\n"
        "你刚才输出了一版候选最终方案，但独立审核器认为它还不能直接展示给用户。\n"
        "请基于下面的问题和建议，重新生成一版完整、可直接交付的最终方案。\n\n"
        "硬性要求：\n"
        "1. 必须输出完整最终方案，而不是说明你接下来要做什么；\n"
        "2. 必须保持 9 个固定章节和顺序；\n"
        "3. 只能使用建议性表述，不能写成已经通知、已经下达、已经派遣；\n"
        "4. 指挥架构必须覆盖应急管理、消防救援、公安交管、医疗救援和专家技术支持；\n"
        "5. 资源调度必须说明来源单位/出发地、调度路径、预计到达和联系人电话；\n"
        "6. 处置行动必须包含涉险人员二次排查、现场其他伤员排查、家属联络安抚；\n"
        "7. 资源类别必须用中文名称，不能直接输出 WARNING、PPE、SIGN、VEHICLE 等内部编码；\n"
        "8. 如已有专家检索结果，必须写出专家姓名、单位、专业方向和建议支持方式；\n"
        "9. 对暂时缺失的信息要明确写“暂未获取”或“待现场确认”；\n"
        "10. 回复末尾必须附上 agent_control，并设置 final_output=true；\n"
        "11. 这次是最终方案重写，不要再补问用户，也不要输出占位语。\n\n"
        f"【审核发现的问题】\n{issue_block}\n\n"
        f"【审核建议】\n{advice_block}\n\n"
        f"【上一版候选最终方案】\n{candidate_text}"
    )


async def review_final_response_before_display(
    agent: Agent,
    candidate_text: str,
    review_provider: OpenAIProvider,
) -> tuple[str, Any, bool, int]:
    """
    在最终方案展示前做独立审核，必要时最多回退主模型 3 轮。

    返回：
    - 最终文本
    - 审核结果
    - 是否达到最大轮次后仍未通过
    - 实际审核轮次
    """
    reviewer = FinalPlanReviewer(review_provider)
    current_text = candidate_text.strip()
    last_review_result = None

    for attempt in range(1, MAX_FINAL_REVIEW_ROUNDS + 1):
        guardrail_issues = collect_final_plan_guardrail_issues(current_text)
        review_result = await cl.make_async(reviewer.review)(agent.task_state, current_text)
        last_review_result = review_result

        if not guardrail_issues and review_result.passed:
            return current_text, review_result, False, attempt

        if attempt == MAX_FINAL_REVIEW_ROUNDS:
            return current_text, review_result, True, attempt

        retry_prompt = build_final_review_retry_prompt(
            candidate_text=current_text,
            review_result=review_result,
            guardrail_issues=guardrail_issues,
            attempt=attempt,
        )
        reminder = Message(role=MessageRole.SYSTEM, content=retry_prompt)
        agent.state.add_message(reminder)
        agent.task_state.append_message(reminder)

        regenerated = await cl.make_async(agent.provider.chat)(
            agent.get_runtime_messages(),
            tools=None,
        )
        regenerated_raw = regenerated.content or ""
        regenerated_visible = get_user_visible_reply(agent, regenerated_raw).strip()
        regenerated_control = agent.parse_assistant_control(regenerated_raw)
        agent.apply_assistant_control(regenerated_control)
        current_text = regenerated_visible or current_text

    return current_text, last_review_result, True, MAX_FINAL_REVIEW_ROUNDS


def format_candidate_plans(agent: Agent) -> str:
    """将候选方案格式化为便于用户选择的文本。"""
    if not agent.task_state.candidate_plans:
        return ""

    lines = ["### 可选方案\n"]
    for index, plan in enumerate(agent.task_state.candidate_plans, start=1):
        lines.append(f"**方案 {index}: {plan.title}**")
        if plan.summary:
            lines.append(f"- 核心思路: {plan.summary}")
        if plan.advantages:
            lines.append(f"- 优势: {'；'.join(plan.advantages)}")
        if plan.disadvantages:
            lines.append(f"- 劣势: {'；'.join(plan.disadvantages)}")
        lines.append("")

    return "\n".join(lines).strip()


def format_pending_options(agent: Agent) -> str:
    """格式化等待用户阶段的推荐回复选项。"""
    pending = agent.task_state.pending_question
    if not pending or not pending.suggested_options:
        return ""

    lines = ["### 建议回复选项\n"]
    for option in pending.suggested_options:
        if option:
            lines.append(f"- {option}")
    return "\n".join(lines).strip()


def build_pending_interaction_props(agent: Agent) -> Optional[Dict[str, Any]]:
    """根据当前 pending_question 构建卡片组件 props。"""
    pending = agent.task_state.pending_question
    if pending is None:
        return None

    phase = agent.task_state.current_phase.value
    severity = agent.task_state.incident_info.severity or "unknown"
    location_text = (
        agent.task_state.environment_info.formatted_address
        or agent.task_state.incident_info.location_text
        or "位置待补充"
    )

    base_props: Dict[str, Any] = {
        "phase": phase,
        "severity": severity,
        "locationText": location_text,
        "title": "指挥交互面板",
        "prompt": pending.question,
        "reason": pending.reason,
        "suggestedOptions": pending.suggested_options,
        "submitted": False,
    }

    if pending.question_type == "plan_selection":
        latest_eval = agent.task_state.evaluation_results[-1] if agent.task_state.evaluation_results else None
        plan_cards = []
        for index, plan in enumerate(agent.task_state.candidate_plans, start=1):
            plan_cards.append(
                {
                    "planId": plan.plan_id,
                    "label": f"方案 {index}",
                    "title": plan.title,
                    "summary": plan.summary,
                    "advantages": plan.advantages,
                    "disadvantages": plan.disadvantages,
                    "selected": plan.selected,
                    "userReply": f"方案{index}",
                }
            )

        base_props.update(
            {
                "variant": "plan_selection",
                "title": "请选择处置方案",
                "subtitle": "每张卡片对应一套可执行方案，点击即可继续推进评估。",
                "plans": plan_cards,
                "evaluationSummary": {
                    "score": latest_eval.overall_score if latest_eval else None,
                    "riskLevel": latest_eval.risk_level if latest_eval else "",
                },
            }
        )
        return base_props

    if pending.question_type == "confirmation":
        selected_plan = next((plan for plan in agent.task_state.candidate_plans if plan.selected), None)
        latest_eval = agent.task_state.evaluation_results[-1] if agent.task_state.evaluation_results else None
        base_props.update(
            {
                "variant": "confirmation",
                "title": "确认执行方案",
                "subtitle": "当前方案已经完成评估，请确认是执行还是返回调整。",
                "selectedPlan": {
                    "title": selected_plan.title if selected_plan else "当前方案",
                    "summary": selected_plan.summary if selected_plan else "",
                },
                "evaluationSummary": {
                    "score": latest_eval.overall_score if latest_eval else None,
                    "riskLevel": latest_eval.risk_level if latest_eval else "",
                    "suggestions": latest_eval.suggestions if latest_eval else [],
                },
                "confirmReply": "确认执行",
                "reviseReply": "返回调整",
            }
        )
        return base_props

    if pending.question_type == "stall_resume":
        base_props.update(
            {
                "variant": "stall_resume",
                "title": "检测到流程停住",
                "subtitle": "模型刚刚停在说明态，没有真正调用下一步工具。你可以直接要求它继续行动，或补充新的 refine 信息。",
                "continueReply": pending.metadata.get("continue_reply", STALL_CONTINUE_REPLY),
                "stalledResponse": pending.metadata.get("stalled_response", ""),
                "placeholder": "例如：补充事故信息、强调响应偏好、排除某个资源、要求更快到场等",
            }
        )
        return base_props

    base_props.update(
        {
            "variant": "info_request",
            "title": "请补充关键信息",
            "subtitle": "系统需要更多现场信息，才能继续推进资源调度和方案生成。",
            "expectedFields": pending.expected_fields,
            "placeholder": "例如：伤员人数、具体路段、涉事车辆数量、是否有危化品等",
        }
    )
    return base_props


async def send_pending_interaction_card(agent: Agent) -> bool:
    """
    发送等待用户阶段的卡片交互。

    返回：
    - True: 卡片已发送
    - False: 回退到纯文本交互
    """
    props = build_pending_interaction_props(agent)
    pending = agent.task_state.pending_question

    if props is None or pending is None:
        return False


async def send_pending_interaction_fallback(agent: Agent) -> None:
    """当自定义卡片不可用时，回退到纯文本交互。"""
    pending = agent.task_state.pending_question
    if pending is None:
        return

    if pending.question_type == "stall_resume":
        stalled_response = pending.metadata.get("stalled_response", "")
        if stalled_response:
            await cl.Message(
                content=f"### 模型刚才的停住回复\n\n{stalled_response}",
                author="系统",
            ).send()

    plan_text = format_candidate_plans(agent)
    options_text = format_pending_options(agent)
    if plan_text:
        await cl.Message(content=plan_text).send()
    if options_text:
        await cl.Message(content=options_text).send()
    await cl.Message(content=pending.question).send()

    try:
        element = cl.CustomElement(name="DecisionCards", props=props, display="inline")
        await cl.Message(
            content="",
            author="系统",
            elements=[element],
        ).send()
        return True
    except Exception:
        return False


@cl.on_message
async def on_message(message: cl.Message):
    """处理用户消息"""
    import logging
    logger = logging.getLogger(__name__)

    thinking_msg = None
    try:
        logger.info("=== on_message 开始 ===")

        # 获取Agent
        agent = get_agent()
        review_provider = build_provider_bundle(get_runtime_config())["evaluation"]
        logger.info("=== Agent获取成功 ===")

        # =========================
        # ✅ 仅当上传的是图片/视频时才走 media_caption
        # =========================
        import mimetypes
        import shutil

        def is_media_file(el) -> bool:
            # 1) mime 优先（Chainlit 常见字段：mime / content_type）
            mime = (getattr(el, "mime", None) or getattr(el, "content_type", None) or "").lower()
            if mime.startswith("image/") or mime.startswith("video/"):
                return True

            # 2) 用文件名/路径推断 mime（兜底）
            name = getattr(el, "name", None) or getattr(el, "filename", None) or ""
            path = getattr(el, "path", None) or ""
            guess_target = name or path
            if guess_target:
                g, _ = mimetypes.guess_type(guess_target)
                if (g or "").startswith(("image/", "video/")):
                    return True

            # 3) 扩展名兜底（最后兜底）
            ext = os.path.splitext(name or path)[1].lower()
            return ext in {
                ".jpg", ".jpeg", ".png", ".webp", ".bmp",
                ".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"
            }

        uploaded_media_paths = []
        uploaded_other_files = []

        elems = (
            getattr(message, "elements", None)
            or getattr(message, "attachments", None)
            or []
        )

        for el in elems:
            el_path = (
                getattr(el, "path", None)
                or getattr(el, "local_path", None)
                or getattr(el, "file_path", None)
            )
            if not el_path or not os.path.exists(el_path):
                continue

            if is_media_file(el):
                # 保存到固定目录
                os.makedirs("data/uploads", exist_ok=True)
                el_name = getattr(el, "name", None) or getattr(el, "filename", None) or os.path.basename(el_path)
                safe_name = os.path.basename(el_name)
                import uuid
                dst_path = os.path.join("data/uploads", f"{uuid.uuid4().hex}_{safe_name}")

                shutil.copy(el_path, dst_path)
                uploaded_media_paths.append(dst_path)
            else:
                # 非媒体文件：记录一下（可选）
                el_name = getattr(el, "name", None) or getattr(el, "filename", None) or os.path.basename(el_path)
                uploaded_other_files.append(el_name)

        # 只有在确实上传了图片/视频时，才重写 message.content 触发工具
        if uploaded_media_paths:
            media_path = uploaded_media_paths[0]  # 只取第一个媒体
            user_text = (message.content or "").strip()

            message.content = (
                "请先调用 media_caption 工具对该媒体生成 structured 风格 caption，并列出 key_points 和 risks。\n"
                f"media_path={media_path}\n"
                f"hint=用户补充说明：{user_text}\n"
                "生成caption后，再结合caption回答用户问题。"
            )

            await cl.Message(content=f"📎 已收到媒体文件：`{os.path.basename(media_path)}`，开始分析...").send()

        elif uploaded_other_files:
            # 上传了文件但都不是媒体：提示一下，但继续走纯文本流程
            await cl.Message(
                content=f"📎 已收到文件：{', '.join(uploaded_other_files)}\n"
                        f"目前仅支持图片/视频生成caption；如果你要做法规/RAG/风险评估，请直接提问文本问题。",
                author="系统"
            ).send()
        # 将用户输入同步到会话状态和任务状态
        agent.start_new_turn(message.content)

        # 迭代处理：使用 Chainlit Step 展示思考过程
        iteration = 0
        final_response = ""
        
        # 1. 创建主思考过程 Step
        async with cl.Step(name="Agent 思考中...", type="run") as run_step:
            run_step.input = message.content
            run_step.output = f"当前阶段: {agent.task_state.current_phase.value}"
            
            # 保存最近一次的响应
            last_response = None

            while iteration < agent.max_iterations:
                iteration += 1
                logger.info(f"--- 迭代 {iteration} ---")

                # 获取对话历史和工具定义
                messages = agent.get_runtime_messages()
                tool_definitions = get_active_tool_definitions(agent)
                active_tool_names = [tool["function"]["name"] for tool in tool_definitions]

                # 2. LLM 决策过程 Step
                async with cl.Step(name=f"决策 (轮次 {iteration})", type="llm") as decision_step:
                    decision_step.input = {
                        "phase": agent.task_state.current_phase.value,
                        "active_tools": active_tool_names,
                    }
                    try:
                        import time
                        start_time = time.time()
                        
                        # 异步调用 LLM
                        response = await cl.make_async(agent.provider.chat)(
                            messages,
                            tools=tool_definitions or None,
                        )
                        elapsed = time.time() - start_time
                        logger.info(f"LLM响应耗时: {elapsed:.2f}秒")
                        
                        last_response = response

                        # 更新 Step 输出
                        if response.content:
                            decision_step.output = response.content
                        else:
                            tool_names = [tc.name for tc in (response.tool_calls or [])]
                            decision_step.output = f"🤔 决定调用工具: {', '.join(tool_names)}"

                    except Exception as e:
                        logger.error(f"LLM调用失败: {e}")
                        decision_step.output = f"❌ 错误: {str(e)}"
                        decision_step.is_error = True
                        await cl.Message(content=f"❌ 系统出现错误：{str(e)}").send()
                        return

                # 检查是否有工具调用
                if response.tool_calls:
                    # 添加助手消息（包含工具调用）
                    assistant_msg = Message(
                        role=MessageRole.ASSISTANT,
                        content=response.content or "",
                        tool_calls=response.tool_calls
                    )
                    agent.state.add_message(assistant_msg)
                    agent.task_state.append_message(assistant_msg)
                    called_tool_names = []

                    # 3. 工具执行过程 Step
                    for tool_call in response.tool_calls:
                        called_tool_names.append(tool_call.name)
                        async with cl.Step(name=f"执行工具: {tool_call.name}", type="tool") as tool_step:
                            # 展示工具参数
                            tool_step.input = tool_call.arguments
                            tool_args = {}
                            
                            try:
                                # 执行工具
                                logger.info(f"执行工具: {tool_call.name}")
                                import json
                                
                                # 兼容处理：有些SDK返回的是dict，有些是str
                                if isinstance(tool_call.arguments, dict):
                                    tool_args = tool_call.arguments
                                else:
                                    tool_args = json.loads(tool_call.arguments)
                                    
                                tool_result = await cl.make_async(agent.tools[tool_call.name].run)(**tool_args)

                                # 添加工具结果到历史
                                tool_msg = Message(
                                    role=MessageRole.TOOL,
                                    content=tool_result,
                                    tool_call_id=tool_call.id
                                )
                                agent.state.add_message(tool_msg)
                                agent.task_state.append_message(tool_msg)
                                agent.after_tool_execution(tool_call.name, tool_args, tool_result)

                                # 优化显示逻辑：针对不同工具做特殊处理
                                if tool_call.name == "query_rag":
                                    tool_step.output = f"✅ 已检索到相关文档（长度: {len(tool_result)} 字符）\n由于内容较长，请查看详情。"
                                    tool_step.elements = [
                                        cl.Text(name="RAG 检索结果", content=tool_result, language="markdown")
                                    ]
                                elif tool_call.name == "evaluate_incident_severity":
                                    try:
                                        res_json = json.loads(tool_result)
                                        tool_step.output = (
                                            "📏 已完成预案定级："
                                            f"{res_json.get('response_level', '待确认')} | "
                                            f"场景={res_json.get('incident_category', '未知')} | "
                                            f"灾害={res_json.get('disaster_type', '无') or '无'}"
                                        )
                                        tool_step.elements = [
                                            cl.Text(name="定级结果", content=tool_result, language="json")
                                        ]
                                    except Exception:
                                        tool_step.output = tool_result
                                elif tool_call.name == "get_emergency_plan":
                                    try:
                                        res_json = json.loads(tool_result)
                                        supplementary = res_json.get("supplementary_plan")
                                        extra_note = " + 补充预案" if supplementary else ""
                                        tool_step.output = (
                                            f"📘 已获取预案模块：{res_json.get('plan_name', '未知预案')}{extra_note}\n"
                                            f"模块：{res_json.get('module', '未知')} | "
                                            f"级别：{res_json.get('level', '未指定') or '未指定'}"
                                        )
                                        tool_step.elements = [
                                            cl.Text(name="预案内容", content=tool_result, language="json")
                                        ]
                                    except Exception:
                                        tool_step.output = tool_result
                                elif tool_call.name == "search_emergency_resources":
                                    try:
                                        res_json = json.loads(tool_result)
                                        candidates = res_json.get("candidates", {})
                                        warehouses = candidates.get("warehouses", [])
                                        teams = candidates.get("teams", [])
                                        coverage = res_json.get("coverage", {})
                                        covered = "、".join(
                                            coverage.get("covered_categories_zh")
                                            or coverage.get("covered_categories", [])
                                        ) or "无"
                                        missing = "、".join(
                                            coverage.get("missing_categories_zh")
                                            or coverage.get("missing_categories", [])
                                        ) or "无"
                                        tool_step.output = (
                                            f"📦 已完成内部资源搜索：仓库 {len(warehouses)} 个，队伍 {len(teams)} 支\n"
                                            f"覆盖率：{coverage.get('coverage_ratio', 0)}\n"
                                            f"已覆盖类别：{covered}\n"
                                            f"仍缺类别：{missing}"
                                        )
                                        tool_step.elements = [
                                            cl.Text(name="资源搜索结果", content=tool_result, language="json")
                                        ]
                                    except Exception:
                                        tool_step.output = tool_result
                                elif tool_call.name == "optimize_dispatch_plan":
                                    try:
                                        res_json = json.loads(tool_result)
                                        dispatch_plan = res_json.get("dispatch_plan", {})
                                        coverage_summary = res_json.get("coverage_summary", {})
                                        tier1 = dispatch_plan.get("tier1", {}).get("resources", [])
                                        tier2 = dispatch_plan.get("tier2", {}).get("resources", [])
                                        tier3 = dispatch_plan.get("tier3", {}).get("resources", [])
                                        missing = "、".join(
                                            coverage_summary.get("still_missing_zh")
                                            or coverage_summary.get("still_missing", [])
                                        ) or "无"
                                        tool_step.output = (
                                            f"🚚 已生成调度方案：第一梯队 {len(tier1)} 个，第二梯队 {len(tier2)} 个，第三梯队 {len(tier3)} 个\n"
                                            f"覆盖率：{coverage_summary.get('coverage_ratio', 0)}\n"
                                            f"仍缺类别：{missing}"
                                        )
                                        tool_step.elements = [
                                            cl.Text(name="调度方案详情", content=tool_result, language="json")
                                        ]
                                    except Exception:
                                        tool_step.output = tool_result
                                elif tool_call.name == "search_experts":
                                    try:
                                        res_json = json.loads(tool_result)
                                        experts = res_json.get("experts", [])
                                        names = "、".join(item.get("name", "") for item in experts[:5]) or "无"
                                        tool_step.output = f"🧑‍💼 已检索专家 {len(experts)} 名：{names}"
                                        tool_step.elements = [
                                            cl.Text(name="专家检索结果", content=tool_result, language="json")
                                        ]
                                    except Exception:
                                        tool_step.output = tool_result
                                elif tool_call.name == "plan_dispatch_routes":
                                    try:
                                        res_json = json.loads(tool_result)
                                        routes = res_json.get("routes", [])
                                        ok_routes = [item for item in routes if item.get("status") == "success"]
                                        route_lines = [
                                            f"{item.get('origin_name', '未知')}：{item.get('distance_km', '未知')}km，约{item.get('duration_min', '未知')}分钟"
                                            for item in ok_routes[:5]
                                        ]
                                        summary = "\n".join(route_lines) or "未获取到可用路线"
                                        tool_step.output = f"🧭 已规划调度路线 {len(ok_routes)}/{len(routes)} 条\n{summary}"
                                        tool_step.elements = [
                                            cl.Text(name="路线规划结果", content=tool_result, language="json")
                                        ]
                                    except Exception:
                                        tool_step.output = tool_result
                                elif tool_call.name == "check_traffic_status":
                                    from src.tools.gaode_tools import CheckTrafficStatus # 假设可以这样引用，或者直接解析
                                    try:
                                        res_json = json.loads(tool_result)
                                        desc = res_json.get("description", "无详细描述")
                                        eval_res = res_json.get("evaluation", {}).get("status_desc", "未知")
                                        tool_step.output = f"🚦 交通状况: **{eval_res}**\n{desc}"
                                    except:
                                        tool_step.output = tool_result
                                elif tool_call.name == "search_map_resources":
                                    # 尝试解析 JSON 以判断是否为地图结果
                                    try:
                                        map_data = json.loads(tool_result)
                                        if isinstance(map_data, dict) and map_data.get("_is_map_result"):
                                            from src.utils.map_visualizer import generate_rescue_map_html
                                            
                                            center = map_data.get("center", {})
                                            resources = map_data.get("resources", [])
                                            display_text = map_data.get("display_text", "已检索到周边资源。")
                                            
                                            tool_elements = []
                                            
                                            # 如果有资源，生成路线图（取最近的一个）
                                            if resources and center:
                                                nearest_res = resources[0]
                                                map_id = f"map_{tool_call.id}"
                                                
                                                map_html = generate_rescue_map_html(
                                                    start_lat=nearest_res['latitude'],
                                                    start_lon=nearest_res['longitude'],
                                                    end_lat=center['lat'],
                                                    end_lon=center['lon'],
                                                    start_name=f"{nearest_res['name']} ({nearest_res['type']})",
                                                    end_name="事故地点",
                                                    map_container_id=map_id
                                                )
                                                
                                                tool_elements.append(
                                                    cl.Text(name="地图代码", content=map_html, language="html", display="inline")
                                                )
                                                # 注意: Chainlit 的 cl.Html 组件目前可能需要在 Message 中发送，
                                                # 或者作为 element 附加。但在 Step 中通常附加 Text 或 Image。
                                                # 这里我们将 HTML 作为 Text element 附加，让用户可以查看或者如果 Chainlit 支持渲染 HTML string better.
                                                # 更佳实践：如果 Chainlit 版本支持，直接显示 render 后的 HTML。
                                                # 暂时用 cl.Text 存放详情，并在 output 中提示。
                                                
                                                # 修正：Chainlit 确实没有直接的 "Map Element"，通常是用 iframe 或 html 内容。
                                                # 我们可以尝试直接构造一个 cl.Message 发送地图，但这会打断 Step流。
                                                # 这里我们把 HTML 放在 Elements 里，让用户点开看，或者依赖前端渲染。
                                                
                                                # 实际效果最好的方式可能是不仅 update step，还发送一个独立的 Message 用来展示 Map
                                                # 但为了保持流式一致性，我们先作为 Element 附加。
                                                
                                                # Wait, Chainlit actually renders cl.Html elements inline if display='inline'!
                                                # let's try pushing it as cl.Html if supported, or verify imports.
                                                # Based on docs, cl.Html exists.
                                            
                                            tool_step.output = f"🗺️ {display_text}\n\n(可视化地图已生成，请查看详情面板)"
                                            
                                            # 展示详细资源列表
                                            details = json.dumps(resources, indent=2, ensure_ascii=False)
                                            tool_elements.append(cl.Text(name="资源详情", content=details, language="json"))
                                            
                                            # 如果支持 HTML 渲染
                                            # tool_elements.append(cl.Element(name="RescueMap", display="inline", content=map_html)) 
                                            # Chainlit simple usage:
                                            # We will stick to Text for details since custom HTML embedding might require specific setup.
                                            # better: Just output the text summary.
                                            
                                            tool_step.elements = tool_elements

                                        else:
                                            # 不是地图格式的 JSON，或者解析成功但没有标志位
                                            tool_step.output = tool_result
                                    
                                    except json.JSONDecodeError:
                                        # 如果是纯文本结果（旧逻辑）
                                        lines = tool_result.splitlines()
                                        if len(lines) > 5:
                                            tool_step.output = f"🗺️ {lines[0]}\n\n(点击下方详情查看完整资源列表)"
                                            tool_step.elements = [cl.Text(name="资源检索详情", content=tool_result, language="markdown")]
                                        else:
                                            tool_step.output = tool_result
                                else:
                                    # 默认截断显示过长的结果
                                    if len(tool_result) > 500:
                                        tool_step.output = tool_result[:500] + "..."
                                        tool_step.elements = [cl.Text(name="完整输出", content=tool_result)]
                                    else:
                                        tool_step.output = tool_result

                            except Exception as e:
                                logger.error(f"工具执行失败: {e}")
                                tool_step.output = f"❌ 执行失败: {str(e)}"
                                tool_step.is_error = True
                                
                                error_msg = Message(
                                    role=MessageRole.TOOL,
                                    content=f"工具执行失败: {str(e)}",
                                    tool_call_id=tool_call.id
                                )
                                agent.state.add_message(error_msg)
                                agent.task_state.append_message(error_msg)
                                agent.after_tool_execution(
                                    tool_call.name,
                                    tool_args,
                                    result="",
                                    success=False,
                                    error_message=str(e),
                                )

                    analysis_msg = agent.build_post_tool_analysis_message(", ".join(called_tool_names))
                    agent.state.add_message(analysis_msg)
                    agent.task_state.append_message(analysis_msg)
                    run_step.output = f"当前阶段: {agent.task_state.current_phase.value}"

                    # 继续下一轮迭代
                    continue

                else:
                    raw_response = response.content or ""
                    visible_response = get_user_visible_reply(agent, raw_response)
                    control = agent.parse_assistant_control(raw_response)
                    agent.apply_assistant_control(control)

                    if (
                        agent.task_state.current_phase == TaskPhase.INTAKE
                        and not agent.task_state.intake_is_complete()
                        and not control.needs_user_input
                        and not control.final_output
                    ):
                        reminder = Message(
                            role=MessageRole.SYSTEM,
                            content=build_intake_retry_prompt(agent),
                        )
                        agent.state.add_message(reminder)
                        agent.task_state.append_message(reminder)
                        run_step.output = "🔁 Intake 信息未完整，要求模型继续补问或补全结构化字段。"
                        continue

                    if (
                        agent.task_state.current_phase == TaskPhase.INTAKE
                        and agent.task_state.intake_is_complete()
                        and not agent.task_state.incident_info.response_level
                        and agent_has_tool(agent, "evaluate_incident_severity")
                        and not control.needs_user_input
                        and not control.final_output
                    ):
                        reminder = Message(
                            role=MessageRole.SYSTEM,
                            content=build_severity_retry_prompt(agent),
                        )
                        agent.state.add_message(reminder)
                        agent.task_state.append_message(reminder)
                        run_step.output = "🔁 Intake 信息已齐全，要求模型先完成预案定级。"
                        continue

                    if (
                        agent.task_state.current_phase == TaskPhase.INTAKE
                        and agent.task_state.intake_ready_to_advance()
                        and not control.needs_user_input
                        and not control.final_output
                        and control.next_phase is None
                    ):
                        reminder = Message(
                            role=MessageRole.SYSTEM,
                            content=build_phase_transition_retry_prompt(agent),
                        )
                        agent.state.add_message(reminder)
                        agent.task_state.append_message(reminder)
                        run_step.output = "🔁 Intake 已完成，要求模型明确进入下一阶段。"
                        continue

                    if contains_nonexistent_execution_claim(visible_response):
                        reminder = Message(
                            role=MessageRole.SYSTEM,
                            content=build_no_execution_claim_prompt(),
                        )
                        agent.state.add_message(reminder)
                        agent.task_state.append_message(reminder)
                        run_step.output = "🔁 检测到虚构现实执行动作，要求模型重写为建议性表述。"
                        continue

                    if (
                        looks_like_progress_only_response(visible_response)
                        and not control.needs_user_input
                        and not control.final_output
                    ):
                        assistant_msg = Message(role=MessageRole.ASSISTANT, content=visible_response)
                        agent.state.add_message(assistant_msg)
                        agent.task_state.append_message(assistant_msg)
                        agent.task_state.set_pending_question(
                            question=build_stall_resume_question(),
                            reason=build_stall_resume_reason(
                                visible_response,
                                "模型输出了进度说明或占位语，但没有真正调用工具。",
                            ),
                            suggested_options=["继续行动", "补充 refine 信息"],
                            question_type="stall_resume",
                            metadata={
                                "continue_reply": STALL_CONTINUE_REPLY,
                                "stalled_response": visible_response,
                            },
                            return_phase=agent.task_state.current_phase,
                        )
                        run_step.output = "⏸️ 检测到模型停在说明态，等待用户选择继续行动或补充 refine。"
                        card_sent = await send_pending_interaction_card(agent)
                        if not card_sent:
                            await send_pending_interaction_fallback(agent)
                        agent.state.save()
                        return

                    stalled_reason = ""
                    if (
                        not control.needs_user_input
                        and not control.final_output
                        and control.next_phase is None
                    ):
                        stalled_reason = detect_stalled_response(visible_response)

                    if stalled_reason:
                        assistant_msg = Message(role=MessageRole.ASSISTANT, content=visible_response)
                        agent.state.add_message(assistant_msg)
                        agent.task_state.append_message(assistant_msg)
                        agent.task_state.set_pending_question(
                            question=build_stall_resume_question(),
                            reason=build_stall_resume_reason(visible_response, stalled_reason),
                            suggested_options=["继续行动", "补充 refine 信息"],
                            question_type="stall_resume",
                            metadata={
                                "continue_reply": STALL_CONTINUE_REPLY,
                                "stalled_response": visible_response,
                            },
                            return_phase=agent.task_state.current_phase,
                        )
                        run_step.output = "⏸️ 检测到模型停在说明态，等待用户选择继续行动或补充 refine。"
                        card_sent = await send_pending_interaction_card(agent)
                        if not card_sent:
                            await send_pending_interaction_fallback(agent)
                        agent.state.save()
                        return

                    assistant_msg = Message(role=MessageRole.ASSISTANT, content=visible_response)
                    agent.state.add_message(assistant_msg)
                    agent.task_state.append_message(assistant_msg)

                    if control.needs_user_input:
                        user_prompt = control.user_prompt or visible_response or "请补充必要信息。"
                        run_step.output = f"⏸️ 等待用户输入（阶段: {agent.task_state.current_phase.value}）"
                        card_sent = await send_pending_interaction_card(agent)
                        if not card_sent:
                            await send_pending_interaction_fallback(agent)
                        agent.state.save()
                        return

                    if control.final_output or agent.task_state.current_phase in {TaskPhase.OUTPUT, TaskPhase.OUTPUT_COMPLETE}:
                        reviewed_response, review_result, review_exhausted, review_rounds = await review_final_response_before_display(
                            agent=agent,
                            candidate_text=visible_response,
                            review_provider=review_provider,
                        )
                        final_response = reviewed_response
                        if review_exhausted:
                            run_step.output = (
                                f"⚠️ 最终方案经过 {review_rounds} 轮审核重写后仍未完全通过，"
                                "已按当前版本展示给用户。"
                            )
                        else:
                            review_summary = review_result.summary or "已通过独立审核。"
                            run_step.output = f"✅ 思考完成，最终方案已通过审核。{review_summary}"
                        break

                    if control.next_phase is not None:
                        run_step.output = (
                            f"阶段推进: {control.phase_reason or '根据模型控制信息继续推进'}\n"
                            f"当前阶段: {agent.task_state.current_phase.value}"
                        )
                        continue

                    final_response = visible_response
                    run_step.output = "✅ 思考完成，生成回答。"
                    break

            # 如果达到最大迭代次数但final_response为空，需要再调用一次LLM生成最终回复
            if not final_response:
                logger.info(f"=== 最终回复为空，强制调用LLM生成 ===")
                
                async with cl.Step(name="生成最终回复", type="llm") as final_step:
                     # 调用LLM生成最终回复（不传tools）
                    messages = agent.state.get_history()
                    try:
                        import time
                        start_time = time.time()
                        final_response_message = await cl.make_async(agent.provider.chat)(messages, tools=None)
                        elapsed = time.time() - start_time
                        
                        final_response = final_response_message.content or ""
                        if contains_nonexistent_execution_claim(final_response):
                            reminder_msg = build_no_execution_claim_prompt()
                            agent.state.add_message(Message(role=MessageRole.SYSTEM, content=reminder_msg))
                            retry_response = await cl.make_async(agent.provider.chat)(agent.state.get_history(), tools=None)
                            final_response = retry_response.content or ""
                        if (
                            agent.task_state.current_phase in {TaskPhase.OUTPUT, TaskPhase.OUTPUT_COMPLETE}
                            and not has_standard_plan_structure(final_response)
                        ):
                            reminder_msg = build_output_format_retry_prompt()
                            agent.state.add_message(Message(role=MessageRole.SYSTEM, content=reminder_msg))
                            retry_response = await cl.make_async(agent.provider.chat)(agent.state.get_history(), tools=None)
                            final_response = retry_response.content or ""
                        stalled_reason = ""
                        if agent.task_state.current_phase not in {TaskPhase.OUTPUT, TaskPhase.OUTPUT_COMPLETE}:
                            stalled_reason = detect_stalled_response(final_response)
                        if stalled_reason:
                            assistant_msg = Message(role=MessageRole.ASSISTANT, content=final_response)
                            agent.state.add_message(assistant_msg)
                            agent.task_state.append_message(assistant_msg)
                            agent.task_state.set_pending_question(
                                question=build_stall_resume_question(),
                                reason=build_stall_resume_reason(final_response, stalled_reason),
                                suggested_options=["继续行动", "补充 refine 信息"],
                                question_type="stall_resume",
                                metadata={
                                    "continue_reply": STALL_CONTINUE_REPLY,
                                    "stalled_response": final_response,
                                },
                                return_phase=agent.task_state.current_phase,
                            )
                            final_response = ""
                            final_step.output = "⏸️ 检测到模型停在说明态，已切换到人工选择继续推进。"
                        else:
                            if agent.task_state.current_phase in {TaskPhase.OUTPUT, TaskPhase.OUTPUT_COMPLETE}:
                                reviewed_response, review_result, review_exhausted, review_rounds = await review_final_response_before_display(
                                    agent=agent,
                                    candidate_text=final_response,
                                    review_provider=review_provider,
                                )
                                final_response = reviewed_response
                                if review_exhausted:
                                    final_step.output = (
                                        f"⚠️ 最终方案经过 {review_rounds} 轮审核重写后仍未完全通过，"
                                        "已按当前版本输出。"
                                    )
                                else:
                                    final_step.output = review_result.summary or "最终方案已通过独立审核。"
                            else:
                                final_step.output = final_response

                            # 添加到历史
                            assistant_msg = Message(role=MessageRole.ASSISTANT, content=final_response)
                            agent.state.add_message(assistant_msg)
                            agent.task_state.append_message(assistant_msg)
                        
                    except Exception as e:
                        final_step.output = f"❌ 生成失败: {e}"
                        final_step.is_error = True
            
        if agent.task_state.current_phase == TaskPhase.WAITING_USER and agent.task_state.pending_question:
            card_sent = await send_pending_interaction_card(agent)
            if not card_sent:
                await send_pending_interaction_fallback(agent)
            agent.state.save()
            return

        # 4. 最后发送完整回复
        if final_response:
            # 这里的 final_response 可能包含 markdown
            await cl.Message(content=final_response).send()
        else:
            await cl.Message(content="🤔 似乎没有生成有效回复，请重试。").send()
            
        # 保存对话历史
        agent.state.save()

    except Exception as e:
        import traceback
        logger.error(f"=== on_message 异常: {e} ===")
        logger.error(traceback.format_exc())
        await cl.Message(content=f"❌ 处理请求时发生错误: {str(e)}").send()


async def display_rag_sources(rag_result: str):
    """展示RAG检索到的文档来源"""
    import json
    import logging
    logger = logging.getLogger(__name__)

    try:
        logger.info(f"=== RAG结果（前500字符）: {rag_result[:500]}...")
        data = json.loads(rag_result)
        logger.info(f"=== 解析后的数据: status={data.get('status')}, count={data.get('count')}")

        # 只在成功且有结果时展示
        if data.get("status") != "success" or data.get("count", 0) == 0:
            logger.info("=== RAG结果不是success或count为0，跳过展示")
            return

        results = data.get("results", [])
        logger.info(f"=== 结果数量: {len(results)}")

        # 使用Markdown格式展示，添加边框
        md_lines = []
        md_lines.append("> **📚 工具调用结果：参考文档来源**\n")
        md_lines.append("---\n")
        md_lines.append(f"> *共检索到 **{len(results)}** 条相关文档*\n")

        for r in results:
            rank = r.get("rank", 0)
            score = r.get("score", 0)
            text = r.get("text", "")
            doc_id = r.get("doc_id", "")
            chunk_id = r.get("chunk_id", "")
            source = r.get("source", "")

            # 文档名称
            doc_name = doc_id if doc_id else f"文档_{rank}"

            # 标题行
            md_lines.append(f"#### {rank}. {doc_name}")
            md_lines.append(f"**相似度:** {score:.1%}\n")

            # 元数据
            meta_parts = []
            if source:
                source_short = source.split("/")[-1] if "/" in source else source
                meta_parts.append(f"📄 `{source_short}`")
            if chunk_id:
                meta_parts.append(f"🔖 `{chunk_id}`")

            if meta_parts:
                md_lines.append("**" + " | ".join(meta_parts) + "**\n")

            # 文档内容（使用引用块）
            if text:
                # 截断过长的文本
                display_text = text[:800] + ("..." if len(text) > 800 else "")
                md_lines.append(f"> **内容:**\n> {display_text}\n")

            md_lines.append("\n---\n")

        content = "\n".join(md_lines)
        logger.info(f"=== 准备发送来源信息（前200字符）: {content[:200]}...")

        await cl.Message(content=content).send()
        logger.info("=== 来源信息发送完成")

    except json.JSONDecodeError as e:
        logger.error(f"JSON解析失败: {e}")
    except Exception as e:
        logger.error(f"展示RAG来源失败: {e}")
        import traceback
        traceback.print_exc()


async def display_risk_assessment(risk_result: str):
    """展示风险评估结果"""
    import json
    import logging
    logger = logging.getLogger(__name__)

    try:
        logger.info(f"=== 风险评估结果（前500字符）: {risk_result[:500]}...")
        data = json.loads(risk_result)
        logger.info(f"=== 解析后的数据: status={data.get('status')}, score={data.get('overall_score')}")

        # 获取评分和等级
        overall_score = data.get("overall_score", 0)
        risk_level = data.get("risk_level", "未知")

        # 根据分数选择颜色
        if overall_score >= 90:
            score_color = "🟢"
            score_emoji = "优秀"
        elif overall_score >= 75:
            score_color = "🔵"
            score_emoji = "良好"
        elif overall_score >= 60:
            score_color = "🟡"
            score_emoji = "及格"
        else:
            score_color = "🔴"
            score_emoji = "不及格"

        # 使用Markdown格式展示，添加边框
        md_lines = []
        md_lines.append("> **📊 工具调用结果：风险评估报告**\n")
        md_lines.append("---\n")
        md_lines.append(f"> **综合评分:** {score_color} **{overall_score}** / 100 ({score_emoji})")
        md_lines.append(f"> **风险等级:** {risk_level}\n")

        # 展示各维度评分
        dimensions = data.get("dimensions", [])
        if dimensions:
            md_lines.append("#### 📋 各维度详情\n")
            for dim in dimensions:
                dim_name = dim.get("name", "")
                dim_score = dim.get("score", 0)
                md_lines.append(f"**{dim_name}**: {dim_score}/100")

                # 优点
                strengths = dim.get("strengths", [])
                if strengths:
                    md_lines.append(f"- ✅ 优点: {', '.join(strengths)}")

                # 不足
                weaknesses = dim.get("weaknesses", [])
                if weaknesses:
                    md_lines.append(f"- ⚠️ 不足: {', '.join(weaknesses)}")

                # 缺失信息
                missing = dim.get("missing_info", [])
                if missing:
                    md_lines.append(f"- ❓ 缺失: {', '.join(missing)}")

                md_lines.append("")

        # 整体优点
        excellent_points = data.get("excellent_points", [])
        if excellent_points:
            md_lines.append("#### ✅ 方案亮点\n")
            for point in excellent_points:
                md_lines.append(f"- {point}")
            md_lines.append("")

        # 潜在风险
        potential_risks = data.get("potential_risks", [])
        if potential_risks:
            md_lines.append("#### ⚠️ 潜在风险\n")
            for risk in potential_risks:
                md_lines.append(f"- {risk}")
            md_lines.append("")

        # 改进建议
        suggestions = data.get("suggestions", [])
        if suggestions:
            md_lines.append("#### 💡 改进建议\n")
            for suggestion in suggestions:
                md_lines.append(f"- {suggestion}")
            md_lines.append("")

        md_lines.append("---")

        content = "\n".join(md_lines)
        logger.info(f"=== 准备发送评估报告（前200字符）: {content[:200]}...")

        await cl.Message(content=content).send()
        logger.info("=== 评估报告发送完成")

    except json.JSONDecodeError as e:
        logger.error(f"JSON解析失败: {e}")
    except Exception as e:
        logger.error(f"展示风险评估失败: {e}")
        import traceback
        traceback.print_exc()

async def display_media_caption(caption_result: str):
    import json
    import logging
    logger = logging.getLogger(__name__)

    try:
        data = json.loads(caption_result)
        if data.get("status") == "error":
            await cl.Message(content=f"❌ Caption失败：{data.get('message')}").send()
            return

        caption = data.get("caption", "")
        key_points = data.get("key_points", [])
        risks = data.get("risks", [])
        media_type = data.get("media_type", "")

        md = []
        md.append("---")
        md.append(f"### 🖼️ 媒体理解（{media_type}）")
        if caption:
            md.append(f"**Caption:** {caption}")

        if key_points:
            md.append("\n**要点:**")
            for k in key_points:
                md.append(f"- {k}")

        if risks:
            md.append("\n**潜在风险:**")
            for r in risks:
                md.append(f"- ⚠️ {r}")

        md.append("---")
        await cl.Message(content="\n".join(md)).send()

    except Exception as e:
        logger.error(f"display_media_caption失败: {e}")


async def display_traffic_status(traffic_result: str):
    """展示交通状况查询结果"""
    import json
    import logging
    logger = logging.getLogger(__name__)

    try:
        data = json.loads(traffic_result)

        if data.get("status") == "error":
            await cl.Message(content=f"❌ 交通查询失败：{data.get('message')}").send()
            return

        md_lines = []
        md_lines.append("> **🚦 工具调用结果：实时交通状况**\n")
        md_lines.append("---\n")

        # 整体路况
        traffic_status = data.get("traffic_status", "")
        status_emoji = {
            "畅通": "🟢",
            "缓行": "🟡",
            "拥堵": "🔴",
            "未知": "⚪"
        }.get(traffic_status, "⚪")

        md_lines.append(f"> **整体路况:** {status_emoji} **{traffic_status}**")

        # 详细描述
        description = data.get("description", "")
        if description:
            md_lines.append(f"> **详细描述:** {description}\n")

        # 具体道路信息
        roads = data.get("roads", [])
        if roads:
            md_lines.append("#### 🛣️ 主要道路详情\n")
            for road in roads[:5]:  # 只显示前5条
                name = road.get("name", "")
                status = road.get("status", "")
                speed = road.get("speed", 0)

                # 根据速度选择颜色
                if speed >= 60:
                    speed_emoji = "🟢"
                elif speed >= 30:
                    speed_emoji = "🟡"
                else:
                    speed_emoji = "🔴"

                md_lines.append(f"**{name}**: {status} (平均速度 {speed_emoji} {speed}km/h)")

            if len(roads) > 5:
                md_lines.append(f"\n*还有 {len(roads) - 5} 条道路...*")

        md_lines.append("\n---")
        await cl.Message(content="\n".join(md_lines)).send()
        logger.info("=== 交通状况报告发送完成")

    except json.JSONDecodeError as e:
        logger.error(f"JSON解析失败: {e}")
    except Exception as e:
        logger.error(f"展示交通状况失败: {e}")


async def display_weather_info(weather_result: str):
    """展示天气查询结果"""
    import json
    import logging
    logger = logging.getLogger(__name__)

    try:
        data = json.loads(weather_result)

        if data.get("status") == "error":
            await cl.Message(content=f"❌ 天气查询失败：{data.get('message')}").send()
            return

        md_lines = []
        md_lines.append("> **🌤️ 工具调用结果：实时天气信息**\n")
        md_lines.append("---\n")

        # 位置
        location = data.get("location", "")
        if location:
            md_lines.append(f"> **位置:** {location}")

        # 天气状况
        weather = data.get("weather", "")
        temperature = data.get("temperature", "")
        wind_direction = data.get("wind_direction", "")
        wind_power = data.get("wind_power", "")
        humidity = data.get("humidity", "")

        md_lines.append(f"> **天气:** {weather}")
        md_lines.append(f"> **温度:** {temperature}")
        md_lines.append(f"> **风向:** {wind_direction}风 (风力{wind_power}级)")
        md_lines.append(f"> **湿度:** {humidity}")

        # 发布时间
        report_time = data.get("report_time", "")
        if report_time:
            md_lines.append(f"\n*发布时间: {report_time}*")

        # 预报信息（如果有）
        casts = data.get("casts", [])
        if casts:
            md_lines.append("\n#### 📅 未来预报\n")
            for cast in casts[:3]:  # 只显示前3天
                date = cast.get("date", "")
                week = cast.get("week", "")
                dayweather = cast.get("dayweather", "")
                nightweather = cast.get("nightweather", "")
                daytemp = cast.get("daytemp", "")
                nighttemp = cast.get("nighttemp", "")

                md_lines.append(f"**{date} ({week})**")
                md_lines.append(f"- 白天: {dayweather} {daytemp}°C")
                md_lines.append(f"- 夜间: {nightweather} {nighttemp}°C")
                md_lines.append("")

        md_lines.append("---")
        await cl.Message(content="\n".join(md_lines)).send()
        logger.info("=== 天气信息发送完成")

    except json.JSONDecodeError as e:
        logger.error(f"JSON解析失败: {e}")
    except Exception as e:
        logger.error(f"展示天气信息失败: {e}")


async def display_geocode_result(geo_result: str):
    """展示地址编码结果"""
    import json
    import logging
    logger = logging.getLogger(__name__)

    try:
        data = json.loads(geo_result)

        if data.get("status") == "error" or data.get("status") == "not_found":
            message = data.get("message", "地址编码失败")
            await cl.Message(content=f"❌ {message}").send()
            return

        md_lines = []
        md_lines.append("> **📍 工具调用结果：地理编码**\n")
        md_lines.append("---\n")

        formatted_address = data.get("formatted_address", "")
        longitude = data.get("longitude", 0)
        latitude = data.get("latitude", 0)
        level = data.get("level", "")

        md_lines.append(f"> **地址:** {formatted_address}")
        md_lines.append(f"> **坐标:** ({longitude:.6f}, {latitude:.6f})")
        md_lines.append(f"> **精度:** {level}\n")

        count = data.get("count", 1)
        if count > 1:
            md_lines.append(f"*找到 {count} 个匹配结果，显示最相关的一个*")

        md_lines.append("---")
        await cl.Message(content="\n".join(md_lines)).send()
        logger.info("=== 地址编码结果发送完成")

    except json.JSONDecodeError as e:
        logger.error(f"JSON解析失败: {e}")
    except Exception as e:
        logger.error(f"展示地址编码结果失败: {e}")


async def display_pois_result(pois_result: str):
    """展示周边POI搜索结果"""
    import json
    import logging
    logger = logging.getLogger(__name__)

    try:
        data = json.loads(pois_result)

        if data.get("status") == "error":
            await cl.Message(content=f"❌ POI搜索失败：{data.get('message')}").send()
            return

        pois = data.get("pois", [])
        count = len(pois)

        md_lines = []
        md_lines.append(f"> **🏢 工具调用结果：周边设施** (共找到 {count} 个)\n")
        md_lines.append("---\n")

        # 只显示前10个
        for poi in pois[:10]:
            name = poi.get("name", "")
            poi_type = poi.get("type", "")
            distance = poi.get("distance", "")
            address = poi.get("address", "")
            tel = poi.get("tel", "")

            md_lines.append(f"#### {name}")

            # 类型标签
            if poi_type:
                # 简化类型显示
                type_simple = poi_type.split(";")[-1] if ";" in poi_type else poi_type
                md_lines.append(f"**类型:** {type_simple}")

            # 距离
            if distance:
                distance_km = int(distance) / 1000
                md_lines.append(f"**距离:** {distance_km:.1f}km")

            # 地址
            if address:
                md_lines.append(f"**地址:** {address}")

            # 电话
            if tel:
                md_lines.append(f"**电话:** {tel}")

            md_lines.append("")

        if count > 10:
            md_lines.append(f"\n*还有 {count - 10} 个结果未显示...*")

        md_lines.append("---")
        await cl.Message(content="\n".join(md_lines)).send()
        logger.info("=== POI搜索结果发送完成")

    except json.JSONDecodeError as e:
        logger.error(f"JSON解析失败: {e}")
    except Exception as e:
        logger.error(f"展示POI结果失败: {e}")


@cl.set_starters
async def set_starters():
    """设置快捷提问按钮"""
    return [
        cl.Starter(
            label="🚗 高速公路事故处置",
            message="高速公路发生多车追尾事故，应该如何处置？",
            icon="/public/icon-car.png"
        ),
        cl.Starter(
            label="⚠️ 应急响应流程",
            message="请告诉我应急响应的标准流程是什么？",
            icon="/public/icon-warning.png"
        ),
        cl.Starter(
            label="📋 查询相关法规",
            message="查询关于交通事故应急响应的相关法规",
            icon="/public/icon-docs.png"
        ),
        cl.Starter(
            label="🔍 检索应急文档",
            message="搜索关于高速公路封闭管理的文档资料",
            icon="/public/icon-search.png"
        ),
    ]


# ===== 自定义样式 =====
# 在前端head中添加自定义CSS
@cl.set_chat_profiles
async def chat_profile():
    """设置聊天配置文件"""
    return [
        cl.ChatProfile(
        name="交通应急指挥助手",
        # 图标数据（使用emoji）
        icon="🚨",
        # 说明文档
        markdown_description="我是交通应急指挥助手，专门协助处理交通事故应急响应相关的工作。",
        instructions="我是交通应急指挥助手，专门协助处理交通事故应急响应相关的工作。",
        # 自定义CSS
        markdown_text_style="""@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&display=swap');

:root {
    --primary-color: #FF6B00;  /* 应急橙 */
    --secondary-color: #1E88E5;  /* 警示蓝 */
    --background-color: #F5F5F5;
    --surface-color: #FFFFFF;
    --text-color: #333333;
    --border-radius: 12px;
}

body {
    font-family: 'Noto Sans SC', sans-serif;
}

/* 消息气泡样式 */
.element {
    border-radius: var(--border-radius);
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}

/* 用户消息 */
.user-message {
    background: linear-gradient(135deg, var(--secondary-color), #1565C0);
    color: white;
}

/* 助手消息 */
.assistant-message {
    background: var(--surface-color);
    border-left: 4px solid var(--primary-color);
}

/* 快捷提问按钮 */
.starter-button {
    background: linear-gradient(135deg, #FFF3E0, #FFE0B2);
    border: 2px solid var(--primary-color);
    border-radius: var(--border-radius);
    transition: all 0.3s ease;
}

.starter-button:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(255, 107, 0, 0.3);
}
"""
        )
    ]


# ===== 侧边栏 =====
@cl.on_chat_resume
async def on_chat_resume(thread_id: str):
    """恢复会话时"""
    await cl.Message(
        content="👋 欢迎回来！我已经准备好继续为你服务。",
        author="系统"
    ).send()


# ===== 错误处理 =====
@cl.on_chat_end
async def on_chat_end():
    """会话结束时"""
    # 这里可以添加会话结束后的处理逻辑
    pass


if __name__ == "__main__":
    # 运行Chainlit应用
    cl.run(
        host="0.0.0.0",
        port=8000
    )
