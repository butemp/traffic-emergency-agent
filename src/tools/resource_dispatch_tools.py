"""
资源调度工具。

对资源调度引擎做薄封装，提供给 Agent 的 Function Calling 能力：
- search_emergency_resources
- optimize_dispatch_plan
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .base import BaseTool
from ..resource_dispatch import ResourceDispatchEngine


_SHARED_ENGINE: Optional[ResourceDispatchEngine] = None


def get_shared_engine() -> ResourceDispatchEngine:
    """获取默认共享引擎，保证搜索与优化能共享同一份上下文。"""
    global _SHARED_ENGINE
    if _SHARED_ENGINE is None:
        _SHARED_ENGINE = ResourceDispatchEngine()
    return _SHARED_ENGINE


class SearchEmergencyResources(BaseTool):
    """搜索附近应急仓库与救援队伍，并给出覆盖度分析。"""

    def __init__(self, engine: Optional[ResourceDispatchEngine] = None):
        super().__init__(data_path=None)
        self.engine = engine or get_shared_engine()

    @property
    def name(self) -> str:
        return "search_emergency_resources"

    @property
    def description(self) -> str:
        return (
            "根据事故位置和所需资源类别，搜索附近的应急仓库和救援队伍，"
            "返回候选资源列表、覆盖度分析和补充建议。"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "longitude": {
                    "type": "number",
                    "description": "事故点经度",
                },
                "latitude": {
                    "type": "number",
                    "description": "事故点纬度",
                },
                "road_code": {
                    "type": "string",
                    "description": "事故所在路段编号，如 G72、G80。有则填写，可提高同路段资源匹配精度",
                },
                "stake": {
                    "type": "number",
                    "description": "事故桩号，如 120.5。有则填写",
                },
                "required_categories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "所需物资类别列表。可选值：SIGN、WARNING、PPE、FIRE、TOOL、"
                        "VEHICLE、MATERIAL、RESCUE、COMMS、DEICE。"
                        "这些是工具内部参数编码，最终方案展示时必须转为中文类别名称"
                    ),
                },
                "required_specialties": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "所需救援队伍专长。可选值：rescue、clearance、emergency_repair",
                },
                "radius_km": {
                    "type": "number",
                    "description": "搜索半径（公里），默认 50",
                    "default": 50,
                },
                "resource_type": {
                    "type": "string",
                    "enum": ["all", "warehouse", "team"],
                    "description": "搜索资源范围，默认 all",
                    "default": "all",
                },
                "exclude_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "排除的资源 ID 列表，用于用户反馈后的重新搜索",
                },
                "max_results": {
                    "type": "integer",
                    "description": "每类资源最多返回多少条候选，默认 10",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 20,
                },
            },
            "required": ["longitude", "latitude", "required_categories"],
        }

    def execute(
        self,
        longitude: float,
        latitude: float,
        required_categories: List[str],
        road_code: str = "",
        stake: Optional[float] = None,
        required_specialties: Optional[List[str]] = None,
        radius_km: float = 50,
        resource_type: str = "all",
        exclude_ids: Optional[List[str]] = None,
        max_results: int = 10,
    ) -> str:
        result = self.engine.search_resources(
            longitude=longitude,
            latitude=latitude,
            road_code=road_code,
            stake=stake,
            required_categories=required_categories,
            required_specialties=required_specialties,
            radius_km=radius_km,
            resource_type=resource_type,
            exclude_ids=exclude_ids,
            max_results=max_results,
        )
        result["display_guidance"] = (
            "最终方案中资源类别请使用 *_zh 字段或 category_label 中文名称，"
            "不要直接输出 WARNING、PPE、SIGN、VEHICLE 等内部编码。"
        )
        return json.dumps(result, ensure_ascii=False, indent=2)


class OptimizeDispatchPlan(BaseTool):
    """基于最近一次资源搜索结果，生成分梯队调度方案。"""

    def __init__(self, engine: Optional[ResourceDispatchEngine] = None):
        super().__init__(data_path=None)
        self.engine = engine or get_shared_engine()

    @property
    def name(self) -> str:
        return "optimize_dispatch_plan"

    @property
    def description(self) -> str:
        return (
            "基于最近一次 search_emergency_resources 搜索到的候选资源，"
            "生成最优的分梯队调度方案。"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "required_categories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "所需物资类别列表",
                },
                "required_specialties": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "所需队伍专长列表",
                },
                "exclude_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "排除的资源 ID（用户明确不要的）",
                },
                "preferred_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "必须包含的资源 ID（用户指定要用的）",
                },
                "max_warehouses": {
                    "type": "integer",
                    "description": "最多选几个仓库，默认 5",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 10,
                },
                "max_teams": {
                    "type": "integer",
                    "description": "最多选几支队伍，默认 5",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 10,
                },
            },
            "required": ["required_categories"],
        }

    def execute(
        self,
        required_categories: List[str],
        required_specialties: Optional[List[str]] = None,
        exclude_ids: Optional[List[str]] = None,
        preferred_ids: Optional[List[str]] = None,
        max_warehouses: int = 5,
        max_teams: int = 5,
    ) -> str:
        result = self.engine.optimize_dispatch_plan(
            required_categories=required_categories,
            required_specialties=required_specialties,
            exclude_ids=exclude_ids,
            preferred_ids=preferred_ids,
            max_warehouses=max_warehouses,
            max_teams=max_teams,
        )
        result["display_guidance"] = (
            "最终方案中资源类别请使用 materials_summary_zh、matched_categories_zh、covered_zh、still_missing_zh 等中文字段，"
            "不要直接输出 WARNING、PPE、SIGN、VEHICLE 等内部编码。"
        )
        return json.dumps(result, ensure_ascii=False, indent=2)
