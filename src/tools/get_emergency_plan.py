"""应急预案精确取用工具。"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .base import BaseTool
from ..emergency_plans import EmergencyPlanService


_SHARED_PLAN_SERVICE: Optional[EmergencyPlanService] = None


def get_shared_plan_service() -> EmergencyPlanService:
    """获取共享的预案服务实例。"""
    global _SHARED_PLAN_SERVICE
    if _SHARED_PLAN_SERVICE is None:
        _SHARED_PLAN_SERVICE = EmergencyPlanService()
    return _SHARED_PLAN_SERVICE


class GetEmergencyPlan(BaseTool):
    """按场景类别和模块精确获取应急预案内容。"""

    def __init__(self, plan_service: Optional[EmergencyPlanService] = None):
        super().__init__(data_path=None)
        self.plan_service = plan_service or get_shared_plan_service()

    @property
    def name(self) -> str:
        return "get_emergency_plan"

    @property
    def description(self) -> str:
        return (
            "根据事件场景类别、灾害类别、响应级别和所需模块，"
            "精确获取对应的应急预案内容。适用于 INTAKE 定级和 PLAN_GENERATION 方案编排。"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "incident_category": {
                    "type": "string",
                    "enum": [
                        "EXPRESSWAY",
                        "HIGHWAY",
                        "ROAD_TRANSPORT",
                        "PORT",
                        "WATERWAY",
                        "WATERWAY_XIJIANG",
                        "WATER_TRANSPORT",
                        "CITY_BUS",
                        "URBAN_RAIL",
                        "CONSTRUCTION",
                    ],
                    "description": "场景类别编码",
                },
                "disaster_type": {
                    "type": "string",
                    "enum": ["", "FLOOD", "ICE_SNOW", "EARTHQUAKE", "PUBLIC_HEALTH", "CYBER"],
                    "description": "灾害类别编码，无则留空",
                },
                "module": {
                    "type": "string",
                    "enum": [
                        "grading_criteria",
                        "command_structure",
                        "response_measures",
                        "scene_disposal",
                        "warning_rules",
                    ],
                    "description": "需要获取的预案模块",
                },
                "level": {
                    "type": "string",
                    "enum": ["", "特别重大级", "重大级", "较大级", "一般级"],
                    "description": "响应级别。获取指挥架构和响应措施时建议填写",
                },
                "scene_type": {
                    "type": "string",
                    "description": "分场景处置类型，如“洪水与地质灾害事件”或“交通拥堵事件”",
                },
            },
            "required": ["incident_category", "module"],
        }

    def execute(
        self,
        incident_category: str,
        module: str,
        disaster_type: str = "",
        level: str = "",
        scene_type: str = "",
    ) -> str:
        result = self.plan_service.get_emergency_plan(
            incident_category=incident_category,
            disaster_type=disaster_type,
            module=module,
            level=level,
            scene_type=scene_type,
        )
        return json.dumps(result, ensure_ascii=False, indent=2)
