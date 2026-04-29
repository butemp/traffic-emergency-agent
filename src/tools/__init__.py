"""
工具模块

实现Agent可调用的工具函数。
"""

from .base import BaseTool, ToolRegistry
from .query_regulations import QueryRegulations
from .query_historical_cases import QueryHistoricalCases
from .risk_assessment import RiskAssessment
from .media_caption import MediaCaption
from .get_emergency_plan import GetEmergencyPlan
from .evaluate_incident_severity import EvaluateIncidentSeverity
from .search_map_resources import SearchMapResources  # 新增资源搜索工具
from .resource_dispatch_tools import SearchEmergencyResources, OptimizeDispatchPlan
from .expert_tools import SearchExperts
from .gaode_tools import (
    CheckTrafficStatus,
    GetWeatherByLocation,
    GeocodeAddress,
    ReverseGeocode,
    SearchNearbyPOIs,
    PlanDispatchRoutes,
    GaodeConfig
)

__all__ = [
    "BaseTool",
    "ToolRegistry",
    "QueryRegulations",
    "QueryHistoricalCases",
    "RiskAssessment",
    "MediaCaption",
    "GetEmergencyPlan",
    "EvaluateIncidentSeverity",
    "SearchMapResources", # 导出新工具
    "SearchEmergencyResources",
    "OptimizeDispatchPlan",
    "SearchExperts",
    "CheckTrafficStatus",
    "GetWeatherByLocation",
    "GeocodeAddress",
    "ReverseGeocode",
    "SearchNearbyPOIs",
    "PlanDispatchRoutes",
    "GaodeConfig"
]
