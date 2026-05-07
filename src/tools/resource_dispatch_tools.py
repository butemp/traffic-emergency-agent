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
                    "description": "所需物资类别列表。优先填写内部编码，如 WARNING、PPE、RESCUE、VEHICLE、COMMS",
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
                "resources": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "兼容字段。模型不需要填写；如果误传 search_emergency_resources 的资源列表，工具会忽略并优先使用最近一次搜索上下文。",
                },
                "incident_location": {
                    "type": "object",
                    "description": "兼容字段。模型不需要填写；事故位置应在 search_emergency_resources 阶段传入。",
                },
                "strategy": {
                    "type": "string",
                    "description": "兼容字段。可写 fast_response 或 balanced；当前优化仍以最近一次搜索上下文为准。",
                },
            },
            "required": [],
        }

    def execute(
        self,
        required_categories: Optional[List[str]] = None,
        required_specialties: Optional[List[str]] = None,
        exclude_ids: Optional[List[str]] = None,
        preferred_ids: Optional[List[str]] = None,
        max_warehouses: int = 5,
        max_teams: int = 5,
        resources: Optional[List[Dict[str, Any]]] = None,
        incident_location: Optional[Dict[str, Any]] = None,
        strategy: str = "",
        **_: Any,
    ) -> str:
        if required_categories is None and getattr(self.engine, "last_search_context", None) is None:
            required_categories = self._infer_required_categories(resources)
        if getattr(self.engine, "last_search_context", None) is None and resources:
            self._seed_search_context_from_resources(
                resources=resources,
                incident_location=incident_location,
                required_categories=required_categories or [],
                required_specialties=required_specialties or [],
            )
        result = self.engine.optimize_dispatch_plan(
            required_categories=required_categories,
            required_specialties=required_specialties,
            exclude_ids=exclude_ids,
            preferred_ids=preferred_ids,
            max_warehouses=max_warehouses,
            max_teams=max_teams,
        )
        if resources:
            result["compatibility_note"] = (
                "模型传入了 resources/incident_location/strategy 兼容字段；"
                "工具已优先使用最近一次 search_emergency_resources 的搜索上下文生成调度方案。"
            )
        result["display_guidance"] = (
            "最终方案中资源类别请使用 materials_summary_zh、matched_categories_zh、covered_zh、still_missing_zh 等中文字段，"
            "不要直接输出 WARNING、PPE、SIGN、VEHICLE 等内部编码。"
        )
        return json.dumps(result, ensure_ascii=False, indent=2)

    def _infer_required_categories(self, resources: Optional[List[Dict[str, Any]]]) -> List[str]:
        """兼容模型误传 resources 时，从中文类别粗略反推内部需求编码。"""
        if not resources:
            return []

        label_to_code = {
            "交通标志标牌": "SIGN",
            "警示防护设备": "WARNING",
            "个人防护用品": "PPE",
            "消防器材": "FIRE",
            "工具与工程机械": "TOOL",
            "车辆装备": "VEHICLE",
            "抢险材料": "MATERIAL",
            "救生救援装备": "RESCUE",
            "通信照明设备": "COMMS",
            "除冰除雪物资": "DEICE",
        }
        inferred: List[str] = []
        for resource in resources:
            for label in resource.get("categories_zh", []) or []:
                code = label_to_code.get(str(label))
                if code and code not in inferred:
                    inferred.append(code)
        return inferred

    def _seed_search_context_from_resources(
        self,
        resources: List[Dict[str, Any]],
        incident_location: Optional[Dict[str, Any]],
        required_categories: List[str],
        required_specialties: List[str],
    ) -> None:
        """兼容模型把资源列表直接传给 optimize_dispatch_plan 的情况。"""
        warehouses: List[Dict[str, Any]] = []
        teams: List[Dict[str, Any]] = []

        for resource in resources:
            normalized = self._normalize_compat_resource(
                resource=resource,
                required_categories=required_categories,
                required_specialties=required_specialties,
            )
            if not normalized:
                continue
            if normalized["resource_type"] == "warehouse":
                warehouses.append(normalized)
            else:
                teams.append(normalized)

        self.engine.last_search_context = {
            "params": {
                "longitude": (incident_location or {}).get("longitude"),
                "latitude": (incident_location or {}).get("latitude"),
                "road_code": "",
                "stake": None,
                "radius_km": 50.0,
                "resource_type": "all",
                "required_categories": required_categories,
                "required_specialties": required_specialties,
                "exclude_ids": set(),
                "max_results": max(len(resources), 10),
            },
            "candidates": {
                "warehouses": warehouses,
                "teams": teams,
            },
            "coverage": {},
        }

    def _normalize_compat_resource(
        self,
        resource: Dict[str, Any],
        required_categories: List[str],
        required_specialties: List[str],
    ) -> Optional[Dict[str, Any]]:
        resource_id = str(resource.get("resource_id") or "").strip()
        name = str(resource.get("name") or "").strip()
        resource_type = str(resource.get("resource_type") or resource.get("type") or "").strip()
        if not resource_id or not name or resource_type not in {"warehouse", "team"}:
            return None

        categories = self._codes_from_zh_labels(resource.get("categories_zh", []) or [])
        if not categories:
            categories = [str(item) for item in resource.get("categories", []) or []]

        matched_categories = (
            sorted(set(categories) & set(required_categories))
            if required_categories else categories
        )
        specialties = [str(item) for item in resource.get("specialties", []) or []]
        matched_specialties = (
            sorted(set(specialties) & set(required_specialties))
            if required_specialties else specialties
        )

        distance_km = float(resource.get("distance_km") or 9999)
        normalized = {
            "resource_id": resource_id,
            "resource_type": resource_type,
            "name": name,
            "longitude": resource.get("longitude"),
            "latitude": resource.get("latitude"),
            "address": resource.get("address", ""),
            "road_code": resource.get("road_code", ""),
            "stake": resource.get("stake"),
            "distance_km": distance_km,
            "relevance_score": max(60.0, 100.0 - min(distance_km, 80.0)),
            "contact": resource.get("contact") or {"name": resource.get("principal", ""), "phone": resource.get("contact_phone", "")},
            "recommend_reasons": resource.get("recommend_reasons", []) or ["由兼容资源列表生成的候选资源"],
            "matched_categories": matched_categories,
            "matched_categories_zh": resource.get("matched_categories_zh") or resource.get("categories_zh", []),
            "categories": categories,
            "categories_zh": resource.get("categories_zh", []),
            "materials_summary": resource.get("materials_summary") or resource.get("materials_summary_zh", {}),
            "materials_summary_zh": resource.get("materials_summary_zh", {}),
            "matched_specialties": matched_specialties,
            "specialties": specialties,
            "team_size": resource.get("team_size"),
            "belong_org_name": resource.get("belong_org_name") or resource.get("source_org", ""),
        }
        return normalized

    def _codes_from_zh_labels(self, labels: List[Any]) -> List[str]:
        label_to_code = {
            "交通标志标牌": "SIGN",
            "警示防护设备": "WARNING",
            "个人防护用品": "PPE",
            "消防器材": "FIRE",
            "工具与工程机械": "TOOL",
            "车辆装备": "VEHICLE",
            "抢险材料": "MATERIAL",
            "救生救援装备": "RESCUE",
            "通信照明设备": "COMMS",
            "除冰除雪物资": "DEICE",
        }
        codes: List[str] = []
        for label in labels:
            code = label_to_code.get(str(label))
            if code and code not in codes:
                codes.append(code)
        return codes
