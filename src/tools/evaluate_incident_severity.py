"""事件定级工具。"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, TYPE_CHECKING

from .base import BaseTool
from .get_emergency_plan import get_shared_plan_service
from ..emergency_plans import EmergencyPlanService, SeverityEvaluator
from ..providers.defaults import DEFAULT_TEXT_BASE_URL, DEFAULT_TEXT_MODEL

if TYPE_CHECKING:
    from ..providers import OpenAIProvider


class EvaluateIncidentSeverity(BaseTool):
    """通过独立模型对话完成事件响应级别判定。"""

    def __init__(
        self,
        provider: Optional["OpenAIProvider"] = None,
        plan_service: Optional[EmergencyPlanService] = None,
    ):
        super().__init__(data_path=None)
        if provider is None:
            from ..providers import OpenAIProvider
            provider = OpenAIProvider(
                api_key=os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY"),
                base_url=os.getenv("EVAL_BASE_URL") or os.getenv("OPENAI_BASE_URL") or DEFAULT_TEXT_BASE_URL,
                model=os.getenv("EVAL_MODEL") or os.getenv("OPENAI_MODEL") or DEFAULT_TEXT_MODEL,
                provider="auto",
            )

        self.provider = provider
        self.model = provider.model
        self.plan_service = plan_service or get_shared_plan_service()
        self.evaluator = SeverityEvaluator(provider=self.provider, plan_service=self.plan_service)

    @property
    def name(self) -> str:
        return "evaluate_incident_severity"

    @property
    def description(self) -> str:
        return (
            "基于应急预案分级标准，对当前灾情进行独立定级。"
            "这个工具会使用一个新的模型对话完成 incident_category、disaster_type、response_level 和 scene_type 判定，"
            "以减少主对话上下文压力。"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "incident_summary": {
                    "type": "string",
                    "description": "灾情摘要，建议包含事故类型、位置、伤亡情况和现场状态",
                },
                "incident_category": {
                    "type": "string",
                    "description": "可选。已知的场景类别编码，如 EXPRESSWAY、HIGHWAY、PORT",
                },
                "disaster_type": {
                    "type": "string",
                    "description": "可选。已知的灾害类别编码，如 FLOOD、ICE_SNOW",
                },
                "incident_type": {
                    "type": "string",
                    "description": "可选。结构化事故类型，如交通事故、危化品泄漏",
                },
                "location_text": {
                    "type": "string",
                    "description": "可选。位置描述，如 G72高速K85处",
                },
                "casualty_status": {
                    "type": "string",
                    "description": "可选。伤亡情况摘要，如 2人受伤1人被困",
                },
                "scene_status": {
                    "type": "string",
                    "description": "可选。现场状态摘要，如 双向阻断、火势仍在蔓延",
                },
                "additional_context": {
                    "type": "string",
                    "description": "可选。其他上下文说明",
                },
            },
            "required": ["incident_summary"],
        }

    def execute(
        self,
        incident_summary: str,
        incident_category: str = "",
        disaster_type: str = "",
        incident_type: str = "",
        location_text: str = "",
        casualty_status: str = "",
        scene_status: str = "",
        additional_context: str = "",
    ) -> str:
        self.evaluator.provider = self.provider
        result = self.evaluator.evaluate(
            incident_summary=incident_summary,
            incident_category=incident_category,
            disaster_type=disaster_type,
            incident_type=incident_type,
            location_text=location_text,
            casualty_status=casualty_status,
            scene_status=scene_status,
            additional_context=additional_context,
        )
        return json.dumps(result, ensure_ascii=False, indent=2)
