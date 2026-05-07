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
from src.agent.final_plan_pipeline import FinalPlanPipeline, FinalPlanPipelineResult, SECTION_SPECS
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
SETTING_OPENAI_MAX_TOKENS = "OPENAI_MAX_TOKENS"
STALL_CONTINUE_REPLY = "请继续行动，直接执行下一步需要的工具；不要停在说明上。"
MAX_AGENT_ITERATIONS = 24
MAX_FINAL_REVIEW_ROUNDS = 5


def parse_positive_int(value: Any, default: int) -> int:
    """解析正整数配置，失败时回退默认值。"""
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def default_runtime_config() -> Dict[str, str]:
    """返回当前会话的默认模型配置。"""
    return {
        # Web 端默认统一走项目内配置，避免服务器残留 OPENAI_API_KEY/DASHSCOPE_API_KEY
        # 把会话默认值悄悄切回其他模型。用户仍可在前端设置面板里手动覆盖。
        SETTING_OPENAI_API_KEY: DEFAULT_TEXT_API_KEY or "",
        SETTING_OPENAI_MODEL: DEFAULT_TEXT_MODEL,
        SETTING_OPENAI_BASE_URL: DEFAULT_TEXT_BASE_URL,
        SETTING_OPENAI_MAX_TOKENS: str(DEFAULT_TEXT_MAX_TOKENS),
    }


def normalize_runtime_config(raw_config: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """对前端提交的模型配置做归一化处理。"""
    defaults = default_runtime_config()
    raw_config = raw_config or {}

    api_key = str(raw_config.get(SETTING_OPENAI_API_KEY, defaults[SETTING_OPENAI_API_KEY]) or "").strip()
    model = str(raw_config.get(SETTING_OPENAI_MODEL, defaults[SETTING_OPENAI_MODEL]) or "").strip()
    base_url = str(raw_config.get(SETTING_OPENAI_BASE_URL, defaults[SETTING_OPENAI_BASE_URL]) or "").strip()
    max_tokens = parse_positive_int(
        raw_config.get(SETTING_OPENAI_MAX_TOKENS, defaults[SETTING_OPENAI_MAX_TOKENS]),
        DEFAULT_TEXT_MAX_TOKENS,
    )

    return {
        SETTING_OPENAI_API_KEY: api_key,
        SETTING_OPENAI_MODEL: model or defaults[SETTING_OPENAI_MODEL],
        SETTING_OPENAI_BASE_URL: base_url,
        SETTING_OPENAI_MAX_TOKENS: str(max_tokens),
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
    max_tokens = parse_positive_int(runtime_config.get(SETTING_OPENAI_MAX_TOKENS), DEFAULT_TEXT_MAX_TOKENS)
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
            max_tokens=max_tokens,
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
            max_tokens=max_tokens,
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
            TextInput(
                id=SETTING_OPENAI_MAX_TOKENS,
                label="OPENAI_MAX_TOKENS",
                initial=current[SETTING_OPENAI_MAX_TOKENS],
                placeholder=str(DEFAULT_TEXT_MAX_TOKENS),
                description="单次最大生成 token 数。真实上下文窗口仍由模型/网关决定；如服务端不支持过大值会报错。",
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
        f"- `OPENAI_BASE_URL`: `{base_url_text}`\n"
        f"- `OPENAI_MAX_TOKENS`: `{runtime_config[SETTING_OPENAI_MAX_TOKENS]}`\n\n"
        "如需切换模型或接入其他 OpenAI-compatible 服务，请点击输入框旁的设置按钮修改以上配置。",
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

    expert_data_path = Path(__file__).parent / "data" / "专家数据" / "expert_info.xls"
    try:
        tools.append(SearchExperts(data_path=str(expert_data_path)))
        logger.info("SearchExperts 工具加载成功")
    except Exception as e:
        logger.warning(
            "SearchExperts 工具加载失败: path=%s, error=%s",
            expert_data_path,
            e,
            exc_info=True,
        )

    try:
        tools.append(SearchMapResources(data_dir="data/graph")) # 注册新工具
        logger.info("SearchMapResources 工具加载成功")
    except Exception as e:
        logger.warning(f"SearchMapResources 工具加载失败: {e}")

    # 创建Agent
    agent = Agent(
        provider=provider,
        tools=tools,
        max_iterations=MAX_AGENT_ITERATIONS,
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
            f"- `OPENAI_MAX_TOKENS`: `{runtime_config[SETTING_OPENAI_MAX_TOKENS]}`\n"
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

DETAIL_CRITICAL_SECTIONS = {
    "三、指挥架构",
    "五、处置行动方案",
    "六、资源调度方案",
    "八、风险提示与注意事项",
}

SECTION_MIN_LENGTHS = {
    "一、事件概述": 240,
    "二、响应定级": 240,
    "三、指挥架构": 520,
    "四、预警发布": 260,
    "五、处置行动方案": 800,
    "六、资源调度方案": 900,
    "七、信息报送与新闻发布": 420,
    "八、风险提示与注意事项": 900,
    "九、依据引用": 260,
}

SECTION_DETAIL_REQUIREMENTS = {
    "一、事件概述": ("事件类型", "事发时间", "事发位置", "经纬度", "事件描述", "伤亡情况", "道路影响", "天气状况", "路况状况"),
    "二、响应定级": ("响应级别", "定级依据", "响应启动主体", "适用预案", "预案依据"),
    "三、指挥架构": ("总指挥", "副总指挥", "应急管理", "公安", "消防", "医疗", "专家", "职责"),
    "四、预警发布": ("预警级别", "发布主体", "发布流程", "发布渠道", "预警内容", "预案依据"),
    "五、处置行动方案": ("先期处置", "全面响应", "持续处置", "现场警戒", "交通", "二次排查", "家属", "舆情"),
    "六、资源调度方案": (
        "第一梯队", "第二梯队", "外部资源", "专家技术支持", "资源覆盖",
        "联系人", "电话", "调度路径", "可调配物资", "用途", "使用位置", "调度理由", "缺口", "补充建议",
    ),
    "七、信息报送与新闻发布": ("初报", "续报", "报送对象", "新闻发布", "舆情", "责任单位"),
    "八、风险提示与注意事项": (
        "安全风险", "处置风险", "衍生风险", "风险描述", "触发条件",
        "影响后果", "应对措施", "责任单位", "监测指标", "升级条件",
    ),
    "九、依据引用": ("预案名称", "引用章节", "引用内容", "支撑"),
}


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
    intent_only_patterns = (
        r"(让我|我来|我现在来).{0,36}(调用|查询|搜索|评估|检索|生成|获取|优化|制定|进行)",
        r"基于.{0,40}(收集到|获取到|掌握).{0,24}信息.{0,32}(现在)?(我)?可以.{0,24}(生成|制定|输出)",
        r"(现在)?(我)?可以.{0,24}(生成|制定|输出).{0,16}(完整|最终).{0,16}(方案|调度方案|处置方案)",
        r"(进行|完成).{0,12}风险评估.{0,24}(生成|制定|输出|优化)",
        r"生成最终的.{0,16}(优化调度方案|调度方案|处置方案|应急处置方案)",
    )
    execution_claim_markers = (
        "已执行的行动",
        "已通知",
        "已下达指令",
        "已启动应急响应",
    )

    if any(marker in text for marker in waiting_markers):
        return True

    if any(re.search(pattern, text) for pattern in intent_only_patterns):
        # 短句只表达“准备做什么”，但没有工具调用也没有完整方案，应视为停住态。
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
        r"让我.{0,32}(调用|查询|搜索|评估|检索|生成|获取|推进|优化|分析|制定|进行)",
        r"我来.{0,32}(调用|查询|搜索|评估|检索|生成|获取|推进|优化|分析|制定|进行)",
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
        "0. 完整性优先，不要担心篇幅长；能写细就不要压缩，尤其是资源调度、风险提示、指挥架构和处置行动；\n"
        "1. 必须按以下 9 个固定章节、固定顺序输出：\n"
        f"{section_text}\n"
        "2. 一、事件概述 和 二、响应定级 必须用表格；\n"
        "3. 三、指挥架构 必须列出总指挥/副总指挥，并用表格展示工作组；\n"
        "4. 五、处置行动方案 必须拆成三个阶段，并在每个阶段用表格列出行动内容、责任单位、时间要求、预案依据；\n"
        "5. 三、指挥架构 必须覆盖应急管理、消防救援、公安交管、医疗救援、专家技术支持等关键角色；\n"
        "6. 五、处置行动方案 必须包含涉险人员二次排查、其他伤员排查、家属联络安抚和二次事故防范；\n"
        "7. 六、资源调度方案 必须按梯队展示，并补充资源来源单位/出发地、调度路径、预计到达、联系人电话、关键物资用途说明和资源覆盖与缺口分析；\n"
        "8. 九、依据引用 必须汇总预案名称、引用章节、引用内容摘要；\n"
        "9. 全文只能写建议性表述，不能写成'已通知/已派遣/已下达指令/已启动应急响应'；\n"
        "10. 资源类别只能用中文名称，不能直接输出 WARNING、PPE、SIGN、VEHICLE 等内部编码；\n"
        "11. 如已有专家检索结果，必须在指挥架构或专家技术支持中写出专家姓名、单位、专业方向和建议支持方式；\n"
        "12. 缺失信息请明确写'暂未获取'或'待现场确认'，不要省略章节。\n"
        "\n"
        "【Markdown 格式硬性要求】\n"
        "- 所有表格必须有表头行和分隔行（即 |---|---|--- 格式），且列数一致；\n"
        "- 表格前后必须留空行；如果表头有 9 列，分隔行也必须有 9 个 --- 单元格；\n"
        "- 章节标题统一使用 ### 级别，子标题用 ####；\n"
        "- 资源调度中的“第一梯队/第二梯队/外部资源补充/专家技术支持/关键物资用途说明/资源覆盖与缺口分析”必须写成 #### 小标题，不能作为普通段落夹在表格之间；\n"
        "- 列表项统一使用 - 开头，不要混用 * 或数字列表与无序列表；\n"
        "- 不要出现未闭合的表格行或格式断裂。\n"
        "\n"
        "【资源调度方案硬性要求】\n"
        "- 六、资源调度方案 必须基于 search_emergency_resources 和 optimize_dispatch_plan 的实际返回数据编写；\n"
        "- 每个仓库/队伍必须详细列出可调配的物资清单（物资名称x数量），不能只写物资类别名；\n"
        "- 表格中'携带物资/可调配物资'列要放在显著位置（前几列）；\n"
        "- 每个梯队的每个资源都要单独成行，完整写明：名称、所属单位、可调配物资、距离、预计到达、调度路径、联系人、电话；\n"
        "- 必须增加'关键物资用途说明'表格，写清物资名称、来源资源、用途、使用位置、调度理由、注意事项；\n"
        "- 必须增加'资源覆盖与缺口分析'表格，逐类说明已覆盖、不足、补充来源、人工协调建议。\n"
        "\n"
        "【风险提示与注意事项硬性要求】\n"
        "- 必须分为安全风险、处置风险、衍生风险三类，每类至少 3 条，能写 10-12 条时不要压缩；\n"
        "- 每条风险必须用表格写清：风险描述、触发条件、影响后果、应对措施、责任单位、监测指标、升级条件；\n"
        "- 风险内容必须结合本次事故的实际情况（天气、路况、事故类型、现场环境、资源缺口、舆情压力），不能写空泛通用的风险。\n"
        "\n"
        "【逐章详细度硬性要求】\n"
        "- 不要输出“第一步：分析工具结果”“第二步：处置方案生成”等过程说明；\n"
        "- 指挥架构至少列出 7 个工作组，并写清牵头单位、参与单位、职责和首要动作；\n"
        "- 处置行动方案三个阶段合计不少于 12 条行动，每条都要有责任单位、协同单位、时间要求和依据；\n"
        "- 信息报送与新闻发布必须覆盖初报、续报、终报、新闻发布、舆情监测和回应口径；\n"
        "- 依据引用必须说明每条依据支撑了哪个关键决策。\n"
        "\n"
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

    process_markers = ("第一步：分析工具结果", "第二步：处置方案生成", "基于以上分析，我现在可以生成")
    if any(marker in text for marker in process_markers):
        issues.append("最终方案中混入了模型推理过程说明，应删除“第一步/第二步”等过程性文字，只保留标准 9 章节方案。")

    if not has_standard_plan_structure(text):
        issues.append("方案未满足固定 9 章节结构或章节顺序不正确。")

    detail_issues = collect_section_detail_issues(text)
    issues.extend(detail_issues)

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

    # Markdown 表格格式检查
    markdown_issues = _check_markdown_table_format(text)
    if markdown_issues:
        issues.append("Markdown 格式存在问题：" + "；".join(markdown_issues))

    # 资源调度内容充实度检查
    dispatch_section = _extract_section(text, "六、资源调度方案")
    if dispatch_section:
        dispatch_issues = _check_resource_dispatch_detail(dispatch_section, agent)
        issues.extend(dispatch_issues)

    # 风险提示与注意事项详细度检查
    risk_section = _extract_section(text, "八、风险提示与注意事项")
    if risk_section:
        risk_issues = _check_risk_section_detail(risk_section)
        issues.extend(risk_issues)

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


def _extract_section(text: str, section_heading: str) -> str:
    """从最终方案中提取指定章节内容。"""
    start = text.find(section_heading)
    if start < 0:
        return ""

    end = len(text)
    for next_heading in STANDARD_PLAN_SECTIONS:
        if next_heading == section_heading:
            continue
        pos = text.find(next_heading, start + len(section_heading))
        if 0 < pos < end:
            end = pos
    return text[start:end]


def collect_section_detail_issues(text: str) -> list[str]:
    """逐章检查最终方案是否足够详细。"""
    issues: list[str] = []

    for heading in STANDARD_PLAN_SECTIONS:
        section = _extract_section(text, heading)
        if not section:
            continue

        content = section.replace(heading, "", 1).strip()
        visible_length = len(re.sub(r"\s+", "", content))
        minimum_length = SECTION_MIN_LENGTHS.get(heading, 160)
        if visible_length < minimum_length:
            issues.append(
                f"{heading} 内容过于简略，当前约 {visible_length} 字，建议至少 {minimum_length} 字并补齐关键字段。"
            )

        requirements = SECTION_DETAIL_REQUIREMENTS.get(heading, ())
        missing_terms = [term for term in requirements if term not in section]
        allowed_missing = 2 if heading in DETAIL_CRITICAL_SECTIONS else 3
        if len(missing_terms) > allowed_missing:
            issues.append(
                f"{heading} 缺少关键内容：{'、'.join(missing_terms[:8])}。"
            )

    issues.extend(_check_command_structure_detail(_extract_section(text, "三、指挥架构")))
    issues.extend(_check_action_plan_detail(_extract_section(text, "五、处置行动方案")))
    issues.extend(_check_reporting_section_detail(_extract_section(text, "七、信息报送与新闻发布")))
    issues.extend(_check_reference_section_detail(_extract_section(text, "九、依据引用")))
    return issues


def _check_markdown_table_format(text: str) -> list[str]:
    """检查 Markdown 表格格式是否规范。"""
    issues: list[str] = []
    lines = text.split("\n")

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if not _looks_like_table_row(line):
            i += 1
            continue

        if i + 1 >= len(lines) or not _looks_like_table_separator(lines[i + 1].strip()):
            issues.append(f"表格缺少分隔行（在 '{line[:40]}...' 之后）")
            if len(issues) >= 3:
                break
            i += 1
            continue

        col_count = _table_col_count(line)
        sep_col_count = _table_col_count(lines[i + 1].strip())
        if sep_col_count != col_count:
            issues.append(f"表格分隔行列数({sep_col_count})与表头列数({col_count})不一致")

        i += 2
        while i < len(lines) and _looks_like_table_row(lines[i].strip()):
            row = lines[i].strip()
            if _table_col_count(row) != col_count:
                issues.append(f"表格数据行列数与表头不一致（在 '{row[:40]}...'）")
                break
            i += 1

        if len(issues) >= 3:
            break

    return issues


def normalize_final_markdown_for_display(text: str) -> str:
    """展示前轻量规范 Markdown，避免表格小错误影响前端渲染。"""
    if not text:
        return ""

    normalized = _normalize_resource_subheadings(text)
    normalized = _normalize_markdown_tables(normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _normalize_resource_subheadings(text: str) -> str:
    """将资源调度中的裸文本梯队标题转成稳定的小标题。"""
    lines: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if _looks_like_resource_subheading(line) and not line.startswith("#"):
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(f"#### {line}")
            lines.append("")
            continue
        lines.append(raw_line)

    return "\n".join(lines)


def _looks_like_resource_subheading(line: str) -> bool:
    if not line or line.startswith("|"):
        return False

    heading_patterns = (
        r"^第[一二三四五六七八九十]+梯队(?:（.*?）|\(.*?\))?[：:]?$",
        r"^外部资源补充(?:（.*?）|\(.*?\))?[：:]?$",
        r"^专家技术支持(?:（.*?）|\(.*?\))?[：:]?$",
        r"^关键物资用途说明(?:（.*?）|\(.*?\))?[：:]?$",
        r"^资源覆盖情况(?:（.*?）|\(.*?\))?[：:]?$",
        r"^资源覆盖与缺口分析(?:（.*?）|\(.*?\))?[：:]?$",
    )
    return any(re.match(pattern, line) for pattern in heading_patterns)


def _normalize_markdown_tables(text: str) -> str:
    """修正常见 Markdown 表格断裂：分隔列数不一致、表格前后缺少空行。"""
    source_lines = text.splitlines()
    output_lines: list[str] = []
    i = 0

    while i < len(source_lines):
        line = source_lines[i]
        stripped = line.strip()

        if not _looks_like_table_row(stripped):
            output_lines.append(line)
            i += 1
            continue

        next_line = source_lines[i + 1].strip() if i + 1 < len(source_lines) else ""
        if not _looks_like_table_separator(next_line):
            output_lines.append(line)
            i += 1
            continue

        table_lines = _collect_normalized_table_lines(source_lines, i)
        if output_lines and output_lines[-1].strip():
            output_lines.append("")
        output_lines.extend(table_lines)

        i += len(table_lines)
        if i < len(source_lines) and source_lines[i].strip():
            output_lines.append("")

    return "\n".join(output_lines)


def _collect_normalized_table_lines(lines: list[str], start: int) -> list[str]:
    header_cells = _split_table_cells(lines[start])
    col_count = len(header_cells)
    table_lines = [_format_table_row(header_cells), _format_table_separator(col_count)]

    i = start + 2
    while i < len(lines) and _looks_like_table_row(lines[i].strip()):
        row_cells = _split_table_cells(lines[i])
        table_lines.append(_format_table_row(_fit_table_cells(row_cells, col_count)))
        i += 1

    return table_lines


def _split_table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _fit_table_cells(cells: list[str], col_count: int) -> list[str]:
    """让数据行列数和表头一致。多出来的内容合并到最后一列，少了则补空。"""
    if len(cells) == col_count:
        return cells
    if len(cells) < col_count:
        return cells + [""] * (col_count - len(cells))
    return cells[: col_count - 1] + ["；".join(cells[col_count - 1 :])]


def _format_table_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _format_table_separator(col_count: int) -> str:
    return "| " + " | ".join(["---"] * col_count) + " |"


def _looks_like_table_row(line: str) -> bool:
    return (
        line.startswith("|")
        and line.endswith("|")
        and line.count("|") >= 3
        and not _looks_like_table_separator(line)
    )


def _looks_like_table_separator(line: str) -> bool:
    return bool(re.match(r"^\|[\s\-:|]+\|$", line)) and "--" in line


def _table_col_count(line: str) -> int:
    return max(0, line.count("|") - 1)


def _count_table_data_rows(section: str) -> int:
    rows = 0
    lines = section.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if _looks_like_table_row(line) and i + 1 < len(lines) and _looks_like_table_separator(lines[i + 1].strip()):
            i += 2
            while i < len(lines) and _looks_like_table_row(lines[i].strip()):
                rows += 1
                i += 1
            continue
        i += 1
    return rows


def _check_command_structure_detail(section: str) -> list[str]:
    """检查指挥架构是否足够完整。"""
    if not section:
        return []

    issues: list[str] = []
    required_roles = {
        "应急管理": "应急管理部门/属地政府",
        "公安": "公安交管部门",
        "消防": "消防救援部门",
        "医疗": "卫生健康或医疗救援部门",
        "专家": "专家技术支持组",
        "综合协调": "综合协调工作组",
        "善后": "善后安抚或家属联络组",
    }
    missing = [label for marker, label in required_roles.items() if marker not in section]
    if missing:
        issues.append("三、指挥架构不够完整，缺少：" + "、".join(missing))

    row_count = _count_table_data_rows(section)
    if row_count < 7:
        issues.append("三、指挥架构工作组数量不足，建议至少列出 7 个工作组并写清牵头单位、参与单位、职责和首要动作。")

    return issues


def _check_action_plan_detail(section: str) -> list[str]:
    """检查处置行动方案是否足够详细。"""
    if not section:
        return []

    issues: list[str] = []
    stage_markers = ("先期处置", "全面响应", "持续处置")
    missing_stages = [stage for stage in stage_markers if stage not in section]
    if missing_stages:
        issues.append("五、处置行动方案缺少阶段：" + "、".join(missing_stages))

    action_rows = _count_table_data_rows(section)
    list_actions = len(re.findall(r"(?m)^\s*(?:-|\d+[\.、])\s+", section))
    action_count = max(action_rows, list_actions)
    if action_count < 12:
        issues.append(f"五、处置行动方案行动项不足，当前约 {action_count} 条，建议至少 12 条并覆盖三个阶段。")

    required_actions = ("现场警戒", "交通管制", "二次排查", "伤员", "家属", "清障", "舆情")
    missing_actions = [item for item in required_actions if item not in section]
    if missing_actions:
        issues.append("五、处置行动方案缺少关键动作：" + "、".join(missing_actions))

    return issues


def _check_resource_dispatch_detail(dispatch_section: str, agent: Optional[Agent] = None) -> list[str]:
    """检查资源调度方案的内容详细度。"""
    issues: list[str] = []

    # 检查是否有实际的仓库/队伍名称（而非泛泛而谈）
    if agent is not None:
        resource_names = [
            str(resource.get("name") or "")
            for resource in agent.task_state.available_resources
            if resource.get("type") != "expert" and resource.get("name")
        ]
        if resource_names:
            found_count = sum(1 for name in resource_names[:10] if name in dispatch_section)
            if found_count == 0:
                issues.append(
                    "资源调度方案未引用任何实际搜索到的仓库或队伍名称，"
                    "必须基于 search_emergency_resources/optimize_dispatch_plan 的实际返回数据来编写。"
                )

    # 检查是否有物资详情（物资名×数量的模式）
    material_patterns = [
        r"[×xX]\s*\d+",  # ×2, x3
        r"\d+\s*[个台套件把条箱桶瓶组块根付顶辆双]",  # 50个, 3台
    ]
    has_material_detail = any(
        re.search(pattern, dispatch_section) for pattern in material_patterns
    )
    if not has_material_detail and len(dispatch_section) > 100:
        issues.append(
            "资源调度方案缺少具体的物资数量信息，"
            "每个仓库/队伍应详细列出可调配的物资名称和数量（如'锥桶x50、爆闪灯x20'）。"
        )

    table_rows = _count_table_data_rows(dispatch_section)
    if table_rows < 8:
        issues.append(
            f"资源调度方案表格内容偏少，当前约 {table_rows} 行。建议至少包含梯队资源、外部补充、专家支持、物资用途说明和资源覆盖与缺口分析等多张表。"
        )

    purpose_markers = ("用途", "用于", "作用", "使用位置", "适用场景", "调度理由", "优先级")
    if not any(marker in dispatch_section for marker in purpose_markers):
        issues.append(
            "资源调度方案缺少物资用途说明。每类关键物资应写清用于什么处置动作、放在现场哪个位置、为什么优先调度。"
        )
    if "关键物资用途说明" not in dispatch_section:
        issues.append("资源调度方案缺少“关键物资用途说明”小节，无法判断物资如何服务现场处置动作。")

    coverage_markers = ("资源覆盖", "覆盖状态", "缺口", "未覆盖", "补充建议")
    missing_coverage = [marker for marker in coverage_markers if marker not in dispatch_section]
    if len(missing_coverage) > 2:
        issues.append(
            "资源调度方案缺少资源覆盖与缺口分析，必须说明已覆盖物资、未覆盖物资、补充来源和人工协调建议。"
        )
    if "资源覆盖与缺口分析" not in dispatch_section and "资源覆盖情况" not in dispatch_section:
        issues.append("资源调度方案缺少“资源覆盖与缺口分析”小节，无法看出哪些资源已覆盖、哪些仍需补充。")

    return issues


def _check_risk_section_detail(risk_section: str) -> list[str]:
    """检查风险提示与注意事项的详细度。"""
    issues: list[str] = []

    # 检查三类风险是否都有
    risk_categories = ["安全风险", "处置风险", "衍生风险"]
    missing_categories = [cat for cat in risk_categories if cat not in risk_section]
    if missing_categories:
        issues.append(
            "风险提示与注意事项缺少以下分类：" + "、".join(missing_categories)
            + "，必须包含安全风险、处置风险、衍生风险三类。"
        )

    # 检查是否有应对措施（而不只是列出风险）
    countermeasure_markers = (
        "应对", "措施", "防范", "防护", "建议", "需", "应",
        "确保", "做好", "加强", "注意", "提前", "安排",
    )
    lines = [line.strip() for line in risk_section.split("\n") if line.strip().startswith("-")]
    table_rows = _count_table_data_rows(risk_section)
    risk_item_count = max(len(lines), table_rows)

    if len(lines) >= 3:
        lines_with_measures = sum(
            1 for line in lines
            if any(marker in line for marker in countermeasure_markers)
        )
        if lines_with_measures < len(lines) * 0.5:
            issues.append(
                "风险提示中多数条目只列出了风险描述，缺少对应的防范或处置措施，"
                "每条风险应配有具体的应对方案。"
            )
    elif table_rows >= 3:
        if not any(marker in risk_section for marker in countermeasure_markers):
            issues.append(
                "风险提示表格缺少防范或处置措施列，每条风险应写清应对措施和责任单位。"
            )

    # 检查风险条目数量是否充足
    if risk_item_count < 9:
        issues.append(
            "风险提示条目过少（当前约 %d 条），安全风险、处置风险、衍生风险每类至少应有 3 条。" % risk_item_count
        )

    detail_markers = ("风险描述", "触发条件", "影响后果", "应对措施", "责任单位", "监测指标", "升级条件")
    missing_detail_markers = [marker for marker in detail_markers if marker not in risk_section]
    if len(missing_detail_markers) > 2:
        issues.append(
            "风险提示与注意事项不够细，缺少字段："
            + "、".join(missing_detail_markers)
            + "。建议用表格列出风险描述、触发条件、影响后果、应对措施、责任单位、监测指标和升级条件。"
        )

    return issues


def _check_reporting_section_detail(section: str) -> list[str]:
    """检查信息报送与新闻发布章节是否完整。"""
    if not section:
        return []

    issues: list[str] = []
    required = ("初报", "续报", "终报", "报送对象", "新闻发布", "舆情", "责任单位", "时限")
    missing = [item for item in required if item not in section]
    if len(missing) > 2:
        issues.append("七、信息报送与新闻发布缺少关键内容：" + "、".join(missing))

    if _count_table_data_rows(section) < 5:
        issues.append("七、信息报送与新闻发布内容偏少，建议分别列出初报、续报、终报、新闻发布、舆情回应等事项。")

    return issues


def _check_reference_section_detail(section: str) -> list[str]:
    """检查依据引用章节是否完整。"""
    if not section:
        return []

    issues: list[str] = []
    if "《" not in section or "》" not in section:
        issues.append("九、依据引用未列出明确的预案或法规名称。")
    if "章节" not in section and "第" not in section:
        issues.append("九、依据引用未写清引用章节或条款位置。")
    if _count_table_data_rows(section) < 2:
        issues.append("九、依据引用条目过少，建议用表格列出预案、工具结果、案例或法规依据及其支撑的决策。")

    return issues


def _tool_called_successfully(agent: Agent, tool_name: str) -> bool:
    """判断指定工具是否至少成功执行过一次。"""
    return any(
        record.tool_name == tool_name and record.success
        for record in agent.task_state.tool_call_log
    )


def _successful_tool_arg_values(agent: Agent, tool_name: str, arg_name: str) -> set[str]:
    """收集指定工具成功调用时某个参数的取值。"""
    values: set[str] = set()
    for record in agent.task_state.tool_call_log:
        if record.tool_name != tool_name or not record.success:
            continue
        value = record.arguments.get(arg_name)
        if value not in (None, ""):
            values.add(str(value))
    return values


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
    has_coords = bool(_incident_coordinates(agent))

    if (
        agent_has_tool(agent, "geocode_address")
        and not has_coords
        and (agent.task_state.incident_info.location_text or agent.task_state.environment_info.formatted_address)
        and not _tool_called_successfully(agent, "geocode_address")
    ):
        issues.append("尚未调用 geocode_address 获取事故点坐标，后续天气、路况、资源搜索和路径规划都需要坐标支撑。")

    if (
        agent_has_tool(agent, "evaluate_incident_severity")
        and not agent.task_state.incident_info.response_level
        and not _tool_called_successfully(agent, "evaluate_incident_severity")
    ):
        issues.append("尚未调用 evaluate_incident_severity 完成预案定级，最终方案不能缺少响应级别和定级依据。")

    if agent_has_tool(agent, "get_emergency_plan"):
        required_plan_modules = {
            "grading_criteria",
            "command_structure",
            "response_measures",
            "scene_disposal",
            "warning_rules",
        }
        called_plan_modules = _successful_tool_arg_values(agent, "get_emergency_plan", "module")
        missing_plan_modules = sorted(required_plan_modules - called_plan_modules)
        if missing_plan_modules:
            issues.append(
                "get_emergency_plan 预案模块未补齐，缺少："
                + "、".join(missing_plan_modules)
                + "。最终方案必须包含定级、指挥架构、响应措施、分场景处置和预警发布依据。"
            )

    if has_coords and agent_has_tool(agent, "get_weather_by_location") and not _tool_called_successfully(agent, "get_weather_by_location"):
        issues.append("已有事故点坐标但尚未调用 get_weather_by_location 查询天气，最终方案需要天气对救援安全和风险的影响分析。")

    if has_coords and agent_has_tool(agent, "check_traffic_status") and not _tool_called_successfully(agent, "check_traffic_status"):
        issues.append("已有事故点坐标但尚未调用 check_traffic_status 查询路况，最终方案需要路况、拥堵和绕行风险依据。")

    if agent_has_tool(agent, "search_emergency_resources") and not _tool_called_successfully(agent, "search_emergency_resources"):
        issues.append("尚未调用 search_emergency_resources 搜索应急仓库和救援队伍，最终方案必须基于实际资源数据进行调度。")

    if agent_has_tool(agent, "optimize_dispatch_plan") and not _tool_called_successfully(agent, "optimize_dispatch_plan"):
        if _tool_called_successfully(agent, "search_emergency_resources"):
            issues.append("已完成资源搜索但尚未调用 optimize_dispatch_plan 生成分梯队调度方案，最终方案的资源调度必须基于优化后的调度结果。")

    if agent_has_tool(agent, "search_experts") and not _tool_called_successfully(agent, "search_experts"):
        issues.append("尚未调用 search_experts 检索专家库，最终方案不能直接缺少专家技术支持。")

    if agent_has_tool(agent, "risk_assessment") and not _tool_called_successfully(agent, "risk_assessment"):
        issues.append("尚未调用 risk_assessment 进行风险评估，最终方案的风险提示与注意事项必须有系统化评估支撑。")

    if agent_has_tool(agent, "query_historical_cases") and not _tool_called_successfully(agent, "query_historical_cases"):
        issues.append("尚未调用 query_historical_cases 查询类似案例，最终方案应尽量吸收历史处置经验。")

    if agent_has_tool(agent, "query_regulations") and not _tool_called_successfully(agent, "query_regulations"):
        issues.append("尚未调用 query_regulations 查询细粒度法规、规则和预案处置要求，最终方案需要更具体的操作依据。")

    if agent_has_tool(agent, "query_rag") and not _tool_called_successfully(agent, "query_rag"):
        issues.append("尚未调用 query_rag 补充技术规范或处置细节，最终方案应尽量有更充分的知识依据。")

    has_route_inputs = bool(has_coords and _route_origin_candidates(agent))
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
        "【系统纠正】当前不能直接输出最终方案，因为最终方案缺少必要的预案、态势、资源、专家、路线、风险或案例依据。",
        "请不要重写方案，也不要用文字解释带过；请先调用缺失工具补齐数据，再进入最终输出。",
        "",
        "缺口：",
        *[f"- {issue}" for issue in issues],
        "",
        "请按需要依次调用：",
    ]

    if agent_has_tool(agent, "geocode_address") and not _tool_called_successfully(agent, "geocode_address"):
        location_for_geocode = incident.location_text or agent.task_state.environment_info.formatted_address
        if location_for_geocode:
            lines.append(
                f"- geocode_address：address={json.dumps(location_for_geocode, ensure_ascii=False)}"
            )

    if (
        agent_has_tool(agent, "evaluate_incident_severity")
        and not incident.response_level
        and not _tool_called_successfully(agent, "evaluate_incident_severity")
    ):
        severity_summary = "；".join(
            item
            for item in [
                incident.incident_type,
                incident.location_text,
                incident.casualty_status,
                incident.scene_status,
                incident.additional_context,
            ]
            if item
        )
        lines.append(
            "- evaluate_incident_severity：先独立完成 incident_category、disaster_type、response_level 和 scene_type 判定。"
        )
        lines.append(
            f"  incident_summary={json.dumps(severity_summary or '交通突发事件，需根据上下文定级', ensure_ascii=False)}"
        )

    if agent_has_tool(agent, "get_emergency_plan"):
        required_plan_modules = {
            "grading_criteria",
            "command_structure",
            "response_measures",
            "scene_disposal",
            "warning_rules",
        }
        missing_plan_modules = sorted(
            required_plan_modules - _successful_tool_arg_values(agent, "get_emergency_plan", "module")
        )
        incident_category = incident.incident_category or "EXPRESSWAY"
        disaster_type = incident.disaster_type or ""
        response_level = incident.response_level or ""
        scene_type = incident.scene_type or ""
        if missing_plan_modules:
            lines.extend(
                [
                    "- get_emergency_plan：按缺失模块逐个调用，补齐 "
                    + "、".join(missing_plan_modules)
                    + "。",
                    f"  incident_category={json.dumps(incident_category, ensure_ascii=False)}, disaster_type={json.dumps(disaster_type, ensure_ascii=False)}, level={json.dumps(response_level, ensure_ascii=False)}, scene_type={json.dumps(scene_type, ensure_ascii=False)}",
                ]
            )

    if coords and agent_has_tool(agent, "get_weather_by_location") and not _tool_called_successfully(agent, "get_weather_by_location"):
        lines.append(
            f"- get_weather_by_location：longitude={coords['longitude']}, latitude={coords['latitude']}, extensions='base'"
        )

    if coords and agent_has_tool(agent, "check_traffic_status") and not _tool_called_successfully(agent, "check_traffic_status"):
        lines.append(
            f"- check_traffic_status：longitude={coords['longitude']}, latitude={coords['latitude']}, radius=5000"
        )

    # 资源搜索指引
    if agent_has_tool(agent, "search_emergency_resources") and not _tool_called_successfully(agent, "search_emergency_resources") and coords:
        required_cats = []
        if incident.incident_type:
            type_cat_map = {
                "交通事故": ["WARNING", "RESCUE", "VEHICLE", "PPE", "COMMS"],
                "危化品泄漏": ["WARNING", "PPE", "FIRE", "RESCUE", "COMMS"],
                "火灾": ["FIRE", "WARNING", "PPE", "RESCUE", "COMMS"],
                "地质灾害": ["WARNING", "RESCUE", "TOOL", "VEHICLE", "COMMS"],
                "洪涝": ["WARNING", "RESCUE", "MATERIAL", "VEHICLE", "COMMS"],
            }
            required_cats = type_cat_map.get(incident.incident_type, ["WARNING", "RESCUE", "VEHICLE", "PPE", "COMMS"])
        else:
            required_cats = ["WARNING", "RESCUE", "VEHICLE", "PPE", "COMMS"]
        lines.append(
            f"- search_emergency_resources：longitude={coords['longitude']}, latitude={coords['latitude']}, "
            f"required_categories={json.dumps(required_cats, ensure_ascii=False)}"
        )

    # 调度优化指引
    if agent_has_tool(agent, "optimize_dispatch_plan") and not _tool_called_successfully(agent, "optimize_dispatch_plan") and _tool_called_successfully(agent, "search_emergency_resources"):
        lines.append(
            "- optimize_dispatch_plan：基于 search_emergency_resources 的搜索结果生成分梯队调度方案"
        )

    # 专家检索指引
    if agent_has_tool(agent, "search_experts") and not _tool_called_successfully(agent, "search_experts"):
        lines.append(
            f"- search_experts：keywords={json.dumps(keywords or ['交通安全', '应急管理'], ensure_ascii=False)}, incident_type={incident.incident_type or '交通突发事件'}"
        )

    if agent_has_tool(agent, "query_historical_cases") and not _tool_called_successfully(agent, "query_historical_cases"):
        historical_type = incident.incident_type if incident.incident_type in {"交通事故", "自然灾害", "危化品泄漏", "设施故障", "其他"} else "交通事故"
        lines.append(
            f"- query_historical_cases：keywords={json.dumps(' '.join(keywords or ['交通事故', '救援', '清障']), ensure_ascii=False)}, accident_type={json.dumps(historical_type, ensure_ascii=False)}, location={json.dumps(incident.location_text or '', ensure_ascii=False)}"
        )

    if agent_has_tool(agent, "query_regulations") and not _tool_called_successfully(agent, "query_regulations"):
        regulation_type = incident.incident_type if incident.incident_type in {"交通事故", "自然灾害", "危化品泄漏", "其他"} else "交通事故"
        severity_text = incident.response_level.replace("级", "") if incident.response_level else ""
        regulation_keywords = " ".join(
            part
            for part in [
                incident.incident_type or "交通事故",
                incident.scene_status,
                "现场处置",
                "交通管制",
                "信息报送",
                "善后",
            ]
            if part
        )
        lines.append(
            f"- query_regulations：keywords={json.dumps(regulation_keywords, ensure_ascii=False)}, accident_type={json.dumps(regulation_type, ensure_ascii=False)}, severity={json.dumps(severity_text, ensure_ascii=False)}"
        )

    if agent_has_tool(agent, "query_rag") and not _tool_called_successfully(agent, "query_rag"):
        rag_query_parts = [
            incident.incident_type or "交通突发事件",
            incident.location_text,
            incident.scene_status,
            "现场处置",
            "交通管制",
            "风险防控",
            "信息报送",
        ]
        rag_query = " ".join(part for part in rag_query_parts if part)
        lines.append(
            f"- query_rag：query={json.dumps(rag_query, ensure_ascii=False)}, top_k=8"
        )

    # 路径规划指引
    if coords and origins and agent_has_tool(agent, "plan_dispatch_routes") and not _tool_called_successfully(agent, "plan_dispatch_routes"):
        lines.extend(
            [
                "- plan_dispatch_routes：使用下面的 destination 和 origins，不要自行编造路线。",
                f"destination_longitude={coords['longitude']}",
                f"destination_latitude={coords['latitude']}",
                f"destination_name={json.dumps(incident.location_text or '事故现场', ensure_ascii=False)}",
                "origins=" + json.dumps(origins, ensure_ascii=False, indent=2),
            ]
        )
    elif not coords:
        lines.append("- 如果事故点还没有坐标，请先调用 geocode_address；如资源缺少坐标，最终方案中必须写'路线暂未规划，需由人工调度平台确认'。")

    if agent_has_tool(agent, "risk_assessment") and not _tool_called_successfully(agent, "risk_assessment"):
        scenario_text = "；".join(
            item
            for item in [
                incident.incident_type,
                incident.location_text or agent.task_state.environment_info.formatted_address,
                incident.casualty_status,
                incident.scene_status,
                incident.response_level,
            ]
            if item
        )
        lines.append(
            "- risk_assessment：先用当前已掌握信息和拟定方案要点进行评估，focus_areas=['信息完整性','响应及时性','措施有效性','资源充足性','风险可控性']。"
        )
        if scenario_text:
            lines.append(f"  scenario={json.dumps(scenario_text, ensure_ascii=False)}")

    lines.extend([
        "",
        "重要提醒：最终方案的'六、资源调度方案'必须基于以上工具的实际返回数据来编写，"
        "包括每个仓库/队伍的名称、可调配物资清单（物资名称x数量）、距离、联系人等，不能凭空编造。",
    ])

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
        "1.1 完整性优先，不要担心篇幅长；资源调度、风险提示、指挥架构和处置行动应尽可能详细；\n"
        "2. 必须保持 9 个固定章节和顺序；\n"
        "3. 只能使用建议性表述，不能写成已经通知、已经下达、已经派遣；\n"
        "4. 指挥架构必须覆盖应急管理、消防救援、公安交管、医疗救援和专家技术支持；\n"
        "5. 资源调度必须说明来源单位/出发地、调度路径、预计到达和联系人电话；\n"
        "6. 处置行动必须包含涉险人员二次排查、现场其他伤员排查、家属联络安抚；\n"
        "7. 资源类别必须用中文名称，不能直接输出 WARNING、PPE、SIGN、VEHICLE 等内部编码；\n"
        "8. 如已有专家检索结果，必须写出专家姓名、单位、专业方向和建议支持方式；\n"
        "9. 对暂时缺失的信息要明确写'暂未获取'或'待现场确认'；\n"
        "10. 回复末尾必须附上 agent_control，并设置 final_output=true；\n"
        "11. 这次是最终方案重写，不要再补问用户，也不要输出占位语；\n"
        "12. 不要输出“第一步：分析工具结果”“第二步：处置方案生成”等过程说明，直接给标准 9 章节方案。\n\n"
        "Markdown 格式要求：\n"
        "- 所有表格必须有表头行和分隔行（|---|---|），且每行列数与表头一致；\n"
        "- 表格前后必须留空行；如果表头有 9 列，分隔行也必须有 9 个 --- 单元格；\n"
        "- 章节标题用 ### 级别，子标题用 ####；\n"
        "- 资源调度中的梯队标题和资源用途/缺口小节必须用 ####，例如 #### 第一梯队（立即出动，预计15分钟内到达）、#### 关键物资用途说明；\n"
        "- 不要出现未闭合的表格行或格式断裂。\n\n"
        "逐章详细度要求：\n"
        "- 一、事件概述：至少覆盖事件类型、时间、位置、坐标、伤亡、道路影响、天气、路况和信息来源；\n"
        "- 二、响应定级：必须写出定级依据、启动主体、适用预案、条款摘要和复核条件；\n"
        "- 三、指挥架构：必须详细列出总指挥、副总指挥和不少于 7 个工作组，写清牵头单位、参与单位、职责和首要动作；\n"
        "- 四、预警发布：必须写清发布主体、流程、渠道、内容要点、更新频率和解除条件；\n"
        "- 五、处置行动方案：三个阶段合计不少于 12 条行动，每条有责任单位、协同单位、时间要求和预案依据；\n"
        "- 七、信息报送与新闻发布：必须包含初报、续报、终报、新闻发布、舆情监测和回应口径；\n"
        "- 九、依据引用：必须列出预案/法规/工具结果/案例依据，并说明支撑哪个决策。\n\n"
        "资源调度方案要求：\n"
        "- 必须基于 search_emergency_resources 和 optimize_dispatch_plan 返回的实际数据编写，不能凭空编造仓库和队伍；\n"
        "- 每个仓库/队伍必须详细列出可调配物资清单（物资名称x数量），不能只写类别名；\n"
        "- 表格中'携带物资/可调配物资'列要放在显著位置（靠前列），这是指挥员最关心的信息；\n"
        "- 每个梯队的每个资源都要单独成行，内容要充实，资源调度部分整体字数应充足；\n"
        "- 必须增加'关键物资用途说明'表格：物资名称、来源资源、用途、使用位置、调度理由、注意事项；\n"
        "- 必须增加'资源覆盖与缺口分析'表格：所需类别、覆盖状态、现有来源、缺口、补充建议、人工确认事项。\n\n"
        "风险提示与注意事项要求：\n"
        "- 必须分为安全风险、处置风险、衍生风险三类，每类至少 3 条，能写 10-12 条时不要压缩；\n"
        "- 每条风险必须用表格写清：风险描述、触发条件、影响后果、应对措施、责任单位、监测指标、升级条件；\n"
        "- 风险内容必须结合本次事故实际情况，不要写空泛通用的风险。\n\n"
        f"【审核发现的问题】\n{issue_block}\n\n"
        f"【审核建议】\n{advice_block}\n\n"
        f"【上一版候选最终方案】\n{candidate_text}"
    )


async def send_final_plan_pipeline_preview(pipeline_result: Any, label: str = "章节化最终方案") -> None:
    """把章节流水线的中间产物展示到前端，方便定位最终方案生成问题。"""
    if pipeline_result is None:
        return

    section_texts = getattr(pipeline_result, "section_texts", {}) or {}
    section_paths = getattr(pipeline_result, "section_paths", {}) or {}
    exhausted_sections = getattr(pipeline_result, "exhausted_sections", []) or []
    run_dir = getattr(pipeline_result, "run_dir", "")
    evidence_path = getattr(pipeline_result, "evidence_path", "")

    summary_lines = [
        f"### {label}",
        "",
        f"- 本地目录：`{run_dir}`",
        f"- 证据包：`{evidence_path}`",
        f"- 已生成章节数：{len(section_texts)}",
    ]
    if exhausted_sections:
        summary_lines.append(f"- 未完全通过章节内审核：{'、'.join(exhausted_sections)}")
    else:
        summary_lines.append("- 章节内审核：未发现耗尽重写轮次的章节")

    summary_lines.append("")
    summary_lines.append("下面的附件展示了每个章节的当前 Markdown 内容。")

    elements = []
    for index, (title, content) in enumerate(section_texts.items(), start=1):
        path = section_paths.get(title)
        element_content = "\n".join(
            [
                f"> 文件路径：`{path}`" if path else "> 文件路径：暂未记录",
                "",
                content or "[空章节]",
            ]
        )
        elements.append(
            cl.Text(
                name=f"{index:02d}_{title}",
                content=element_content,
                language="markdown",
            )
        )

    await cl.Message(
        content="\n".join(summary_lines),
        author="章节生成流水线",
        elements=elements,
    ).send()


async def send_final_plan_section_message(title: str, content: str, path: Any, label: str) -> None:
    """章节生成完成后立即展示该章节内容。"""
    await cl.Message(
        content="\n".join(
            [
                f"### {label}: {title}",
                "",
                f"- 文件路径：`{path}`" if path else "- 文件路径：暂未记录",
                "",
                content or "[空章节]",
            ]
        ),
        author="章节生成流水线",
    ).send()


async def generate_final_plan_pipeline_with_frontend(
    pipeline: FinalPlanPipeline,
    task_state: Any,
    seed_plan: str = "",
    global_feedback: str = "",
) -> FinalPlanPipelineResult:
    """逐章生成最终方案，并在每章完成后立即展示到前端。"""
    run_dir = pipeline._create_run_dir()
    sections_dir = run_dir / "sections"
    reviews_dir = run_dir / "reviews"
    sections_dir.mkdir(parents=True, exist_ok=True)
    reviews_dir.mkdir(parents=True, exist_ok=True)

    evidence = pipeline._build_evidence_bundle(task_state=task_state, seed_plan=seed_plan)
    evidence_path = run_dir / "evidence_bundle.md"
    pipeline._write_text(evidence_path, evidence)

    await cl.Message(
        content="\n".join(
            [
                "### 开始章节化生成最终应急指挥方案",
                "",
                f"- 本地目录：`{run_dir}`",
                f"- 证据包：`{evidence_path}`",
                "- 生成方式：9 个章节逐章生成、逐章审核；每章完成后会立即展示。",
            ]
        ),
        author="章节生成流水线",
    ).send()

    section_texts: Dict[str, str] = {}
    section_paths: Dict[str, Path] = {}
    review_paths: Dict[str, list[Path]] = {}
    exhausted_sections: list[str] = []

    for index, spec in enumerate(SECTION_SPECS, start=1):
        async with cl.Step(name=f"生成章节 {index}/9：{spec.title}", type="llm") as section_step:
            section_step.input = {
                "section": spec.title,
                "min_chars": spec.min_chars,
                "required_terms": list(spec.required_terms),
            }
            try:
                text, paths, exhausted = await cl.make_async(pipeline._generate_section_with_review)(
                    spec=spec,
                    evidence=evidence,
                    seed_plan=seed_plan,
                    global_feedback=global_feedback,
                    sections_dir=sections_dir,
                    reviews_dir=reviews_dir,
                )
            except Exception as error:
                logger.exception("章节生成失败，写入错误占位后继续: section=%s, error=%s", spec.title, error)
                text = pipeline._build_section_error_placeholder(spec, error)
                paths = []
                exhausted = True

            section_path = sections_dir / spec.filename
            pipeline._write_text(section_path, text)
            section_texts[spec.title] = text
            section_paths[spec.title] = section_path
            review_paths[spec.title] = paths
            if exhausted:
                exhausted_sections.append(spec.title)

            section_step.output = (
                f"已生成 {spec.title}，长度 {len(text)} 字，"
                f"{'未完全通过章节内审核' if exhausted else '已通过章节内审核'}。"
            )

        await send_final_plan_section_message(
            title=spec.title,
            content=text,
            path=section_path,
            label=f"章节 {index}/9 已生成",
        )

    final_markdown = pipeline._merge_sections(section_texts)
    pipeline._write_text(run_dir / "final_plan.md", final_markdown)

    return FinalPlanPipelineResult(
        final_markdown=final_markdown,
        run_dir=run_dir,
        evidence_path=evidence_path,
        section_texts=section_texts,
        section_paths=section_paths,
        review_paths=review_paths,
        exhausted_sections=exhausted_sections,
    )


async def repair_final_plan_pipeline_with_frontend(
    pipeline: FinalPlanPipeline,
    task_state: Any,
    pipeline_result: FinalPlanPipelineResult,
    review_result: Any,
    guardrail_issues: list[str],
    attempt: int,
) -> FinalPlanPipelineResult:
    """根据全局审核意见逐章局部重写，并立即展示重写章节。"""
    failed_titles = pipeline._select_failed_sections(review_result, guardrail_issues)
    if not failed_titles:
        failed_titles = {"三、指挥架构", "五、处置行动方案", "六、资源调度方案", "八、风险提示与注意事项"}

    evidence = pipeline._read_text(pipeline_result.evidence_path)
    sections_dir = pipeline_result.run_dir / "sections"
    reviews_dir = pipeline_result.run_dir / "reviews"
    section_texts = dict(pipeline_result.section_texts)
    section_paths = dict(pipeline_result.section_paths)
    review_paths = {title: list(paths) for title, paths in pipeline_result.review_paths.items()}
    exhausted_sections = list(pipeline_result.exhausted_sections)
    global_feedback = pipeline._format_global_feedback(review_result, guardrail_issues)

    await cl.Message(
        content="\n".join(
            [
                f"### 开始局部重写最终方案章节（第 {attempt} 轮）",
                "",
                f"- 本轮重写章节：{'、'.join(sorted(failed_titles))}",
                f"- 本地目录：`{pipeline_result.run_dir}`",
            ]
        ),
        author="章节生成流水线",
    ).send()

    for spec in SECTION_SPECS:
        if spec.title not in failed_titles:
            continue

        section_feedback = pipeline._filter_feedback_for_section(spec.title, global_feedback)
        previous_draft = section_texts.get(spec.title, "")
        async with cl.Step(name=f"局部重写章节：{spec.title}", type="llm") as section_step:
            section_step.input = {
                "section": spec.title,
                "feedback": section_feedback,
            }
            try:
                text, paths, exhausted = await cl.make_async(pipeline._generate_section_with_review)(
                    spec=spec,
                    evidence=evidence,
                    seed_plan=previous_draft,
                    global_feedback=section_feedback,
                    sections_dir=sections_dir,
                    reviews_dir=reviews_dir,
                    tag=f"global_retry_{attempt}",
                )
            except Exception as error:
                logger.exception("章节局部重写失败，保留错误占位: section=%s, error=%s", spec.title, error)
                text = pipeline._build_section_error_placeholder(spec, error, previous_draft=previous_draft)
                paths = []
                exhausted = True

            section_path = sections_dir / spec.filename
            pipeline._write_text(section_path, text)
            section_texts[spec.title] = text
            section_paths[spec.title] = section_path
            review_paths.setdefault(spec.title, []).extend(paths)
            if exhausted and spec.title not in exhausted_sections:
                exhausted_sections.append(spec.title)
            elif not exhausted and spec.title in exhausted_sections:
                exhausted_sections.remove(spec.title)

            section_step.output = (
                f"已重写 {spec.title}，长度 {len(text)} 字，"
                f"{'仍未完全通过章节内审核' if exhausted else '已通过章节内审核'}。"
            )

        await send_final_plan_section_message(
            title=spec.title,
            content=text,
            path=section_path,
            label=f"局部重写第 {attempt} 轮完成",
        )

    final_markdown = pipeline._merge_sections(section_texts)
    pipeline._write_text(pipeline_result.run_dir / f"final_plan_global_retry_{attempt}.md", final_markdown)
    pipeline._write_text(pipeline_result.run_dir / "final_plan.md", final_markdown)

    return FinalPlanPipelineResult(
        final_markdown=final_markdown,
        run_dir=pipeline_result.run_dir,
        evidence_path=pipeline_result.evidence_path,
        section_texts=section_texts,
        section_paths=section_paths,
        review_paths=review_paths,
        exhausted_sections=exhausted_sections,
    )


async def review_final_response_before_display(
    agent: Agent,
    candidate_text: str,
    review_provider: OpenAIProvider,
) -> tuple[str, Any, bool, int]:
    """
    在最终方案展示前走章节化生成流水线，再做独立审核。

    主模型给出的 candidate_text 只作为事实线索和风格参考；
    真正展示给用户的最终方案由 FinalPlanPipeline 按 9 个章节分别生成、
    分别审核，并在全局审核失败时只重写问题章节。

    返回：
    - 最终文本
    - 审核结果
    - 是否达到最大轮次后仍未通过
    - 实际审核轮次
    """
    reviewer = FinalPlanReviewer(review_provider)
    pipeline = FinalPlanPipeline(review_provider)
    current_text = candidate_text.strip()
    last_review_result = None
    pipeline_result = None

    # Pipeline 生成，最多尝试 2 次
    for pipeline_attempt in range(1, 3):
        try:
            pipeline_result = await generate_final_plan_pipeline_with_frontend(
                pipeline=pipeline,
                task_state=agent.task_state,
                seed_plan=current_text,
            )
            current_text = pipeline_result.final_markdown
            logger.info("章节化最终方案已生成: run_dir=%s, attempt=%s", pipeline_result.run_dir, pipeline_attempt)
            break
        except Exception as error:
            logger.exception(
                "章节化最终方案生成失败 (第%s次): %s",
                pipeline_attempt, error,
            )
            if pipeline_attempt < 2:
                logger.info("将在下一次尝试重新生成章节化方案")

    # 如果 Pipeline 两次都失败了，用主模型生成一个符合 9 章节结构的详细方案作为兜底
    if pipeline_result is None:
        logger.warning("Pipeline 生成全部失败，启动主模型兜底重写")
        current_text = await _fallback_full_rewrite(agent, current_text)

    for attempt in range(1, MAX_FINAL_REVIEW_ROUNDS + 1):
        guardrail_issues = collect_final_plan_guardrail_issues(current_text, agent=agent)
        review_result = await cl.make_async(reviewer.review)(agent.task_state, current_text)
        last_review_result = review_result

        if not guardrail_issues and review_result.passed:
            return current_text, review_result, False, attempt

        if attempt == MAX_FINAL_REVIEW_ROUNDS:
            return current_text, review_result, True, attempt

        if pipeline_result is not None:
            try:
                pipeline_result = await repair_final_plan_pipeline_with_frontend(
                    pipeline=pipeline,
                    task_state=agent.task_state,
                    pipeline_result=pipeline_result,
                    review_result=review_result,
                    guardrail_issues=guardrail_issues,
                    attempt=attempt,
                )
                current_text = pipeline_result.final_markdown
                logger.info(
                    "章节化最终方案按审核意见完成局部重写: attempt=%s, run_dir=%s",
                    attempt,
                    pipeline_result.run_dir,
                )
                continue
            except Exception as error:
                logger.exception("章节化局部重写失败，回退到主模型整稿重写: %s", error)

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


async def _fallback_full_rewrite(agent: Agent, candidate_text: str) -> str:
    """Pipeline 完全失败时，用主模型兜底生成一个完整的 9 章节方案。"""
    section_text = "\n".join(f"- {heading}" for heading in STANDARD_PLAN_SECTIONS)
    fallback_prompt = (
        "【系统指令：Pipeline 章节化生成失败，现在需要你直接生成完整的最终方案】\n\n"
        "你之前生成了一版候选方案，但章节化处理流程遇到异常。\n"
        "现在需要你基于已有的工具调用结果和灾情信息，直接生成一份完整、详细的标准化应急指挥方案。\n\n"
        "硬性要求：\n"
        "1. 必须严格按以下 9 个固定章节输出，不能增删、不能换序：\n"
        f"{section_text}\n\n"
        "2. 每个章节都要尽可能详细，不能只写 3-5 行概述：\n"
        "   - 三、指挥架构：必须列出总指挥/副总指挥和至少 7 个工作组（综合协调、公安交管、消防救援、医疗救援、抢险清障、专家技术支持、信息与舆情、善后安抚），每个写牵头单位、参与单位、主要职责\n"
        "   - 五、处置行动方案：必须分三个阶段（先期处置0-30分钟、全面响应30分钟-2小时、持续处置2小时以后），每阶段至少 4 条行动，用表格写\n"
        "   - 六、资源调度方案：必须基于工具返回的实际资源数据，按梯队展示，每个资源单独成行写名称、物资清单（物资名x数量）、距离、路线、联系人\n"
        "   - 八、风险提示与注意事项：必须分安全风险/处置风险/衍生风险三类，至少 9 条，每条写风险描述、应对措施\n\n"
        "3. 所有表格必须有表头行和分隔行（|---|---|），列数一致\n"
        "4. 只能用建议性表述，不能写已通知/已派遣/已下达指令\n"
        "5. 资源类别只能用中文名称\n"
        "6. 不要输出过程说明，直接输出标准化 9 章节方案\n"
        "7. 回复末尾附上 agent_control，final_output=true\n\n"
        "【你之前的候选方案（仅作参考）】\n"
        f"{candidate_text[:8000]}"
    )
    reminder = Message(role=MessageRole.SYSTEM, content=fallback_prompt)
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
    return regenerated_visible or candidate_text


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
        called_tools_history: list[str] = []  # 跟踪所有已调用的工具（有序）
        consecutive_no_progress = 0  # 连续无进展轮次计数

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

                    # 记录已调用工具，检测循环
                    called_tools_history.extend(called_tool_names)

                    # 检测工具调用是否陷入循环（连续 3 轮调用相同工具集合）
                    if len(called_tools_history) >= 6:
                        recent_3 = called_tools_history[-3:]
                        prev_3 = called_tools_history[-6:-3]
                        if set(recent_3) == set(prev_3):
                            logger.warning(
                                "检测到工具调用循环: recent=%s, prev=%s，强制推进到输出阶段",
                                recent_3, prev_3,
                            )
                            agent.task_state.transition_to(TaskPhase.OUTPUT)
                            reminder = Message(
                                role=MessageRole.SYSTEM,
                                content=(
                                    "【系统检测到工具调用循环】你已经重复调用了相同的工具，不要再调用工具了。\n"
                                    "请基于已有的全部工具结果，直接输出完整的标准化 9 章节应急指挥方案，"
                                    "并在末尾附上 agent_control，设置 final_output=true。"
                                ),
                            )
                            agent.state.add_message(reminder)
                            agent.task_state.append_message(reminder)

                    # 检测是否在 PLAN_GENERATION 阶段停留过久（工具调用超过 15 次）
                    if (
                        len(called_tools_history) >= 15
                        and agent.task_state.current_phase == TaskPhase.PLAN_GENERATION
                    ):
                        logger.warning(
                            "PLAN_GENERATION 阶段工具调用已达 %s 次，强制推进到输出阶段",
                            len(called_tools_history),
                        )
                        agent.task_state.transition_to(TaskPhase.OUTPUT)
                        reminder = Message(
                            role=MessageRole.SYSTEM,
                            content=(
                                "【系统提醒】你已经调用了足够多的工具，信息已经充分。\n"
                                "请停止调用工具，直接基于已有的全部工具结果输出完整的标准化 9 章节应急指挥方案，"
                                "并在末尾附上 agent_control，设置 final_output=true。"
                            ),
                        )
                        agent.state.add_message(reminder)
                        agent.task_state.append_message(reminder)

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

                    if control.final_output or agent.task_state.current_phase in {TaskPhase.OUTPUT, TaskPhase.OUTPUT_COMPLETE}:
                        pre_output_issues = collect_pre_output_tool_issues(agent)
                        if pre_output_issues:
                            consecutive_no_progress += 1
                            # 如果反复退回补工具超过 3 次，不再退回，直接进入输出
                            if consecutive_no_progress >= 3:
                                logger.warning(
                                    "已连续 %s 次退回补工具但模型未能补齐，强制进入最终输出",
                                    consecutive_no_progress,
                                )
                            else:
                                agent.task_state.transition_to(TaskPhase.PLAN_GENERATION)
                                reminder = Message(
                                    role=MessageRole.SYSTEM,
                                    content=build_pre_output_tool_prompt(agent, pre_output_issues),
                                )
                                agent.state.add_message(reminder)
                                agent.task_state.append_message(reminder)
                                run_step.output = "🔁 最终方案缺少预案、态势、资源、专家、路线、风险或案例依据，已退回补齐工具结果。"
                                continue

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
                        if final_response.strip() and final_response.strip() != visible_response.strip():
                            final_msg = Message(role=MessageRole.ASSISTANT, content=final_response)
                            agent.state.add_message(final_msg)
                            agent.task_state.append_message(final_msg)
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
            final_response = normalize_final_markdown_for_display(final_response)
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


# --- HTTP API 路由挂载 ---
# Chainlit 会注册 catch-all 静态文件路由来服务前端 SPA，
# 导致后追加的路由永远匹配不到。这里把 API 路由插到路由列表最前面。
from chainlit.server import app as fastapi_app
from src.api.routes import router as api_router

_n_before = len(fastapi_app.routes)
fastapi_app.include_router(api_router)
_n_new = len(fastapi_app.routes) - _n_before
if _n_new > 0:
    fastapi_app.routes[:] = fastapi_app.routes[-_n_new:] + fastapi_app.routes[:-_n_new]


if __name__ == "__main__":
    # 运行Chainlit应用
    cl.run(
        host="0.0.0.0",
        port=8000
    )
