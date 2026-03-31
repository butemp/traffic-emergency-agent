"""
工具模块

实现Agent可调用的工具函数。
"""

from .base import BaseTool, ToolRegistry
from .query_regulations import QueryRegulations
from .query_historical_cases import QueryHistoricalCases
from .risk_assessment import RiskAssessment
from .media_caption import MediaCaption
from .search_map_resources import SearchMapResources  # 新增资源搜索工具
from .gaode_tools import (
    CheckTrafficStatus,
    GetWeatherByLocation,
    GeocodeAddress,
    ReverseGeocode,
    SearchNearbyPOIs,
    GaodeConfig
)

__all__ = [
    "BaseTool",
    "ToolRegistry",
    "QueryRegulations",
    "QueryHistoricalCases",
    "RiskAssessment",
    "MediaCaption",
    "SearchMapResources", # 导出新工具
    "CheckTrafficStatus",
    "GetWeatherByLocation",
    "GeocodeAddress",
    "ReverseGeocode",
    "SearchNearbyPOIs",
    "GaodeConfig"
]

