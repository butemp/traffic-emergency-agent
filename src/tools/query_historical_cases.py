"""
查询历史案例工具

从本地文件中查询历史应急指挥案例。
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, List
from .base import BaseTool

logger = logging.getLogger(__name__)


class QueryHistoricalCases(BaseTool):
    """
    查询历史案例工具

    根据事故类型、地点、关键词等条件查询相似的历史处置案例。
    """

    @property
    def name(self) -> str:
        """工具名称"""
        return "query_historical_cases"

    def __init__(self, data_path: str = "data/historical_cases"):
        """
        初始化工具

        Args:
            data_path: 历史案例数据文件目录
        """
        super().__init__(data_path)
        # 加载所有历史案例
        self._cases = self._load_cases()
        logger.info(f"加载历史案例: {len(self._cases)}条")

    def _load_cases(self) -> List[Dict[str, Any]]:
        """
        从本地加载历史案例数据

        Returns:
            案例列表
        """
        cases = []
        data_dir = Path(self.data_path)

        if not data_dir.exists():
            logger.warning(f"历史案例数据目录不存在: {self.data_path}")
            return cases

        # 支持JSON和JSONL格式
        for file_path in data_dir.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        cases.extend(data)
                    elif isinstance(data, dict):
                        cases.append(data)
                    logger.debug(f"加载文件: {file_path.name}")
            except Exception as e:
                logger.error(f"加载文件失败 {file_path}: {e}")

        # 也支持jsonl格式
        for file_path in data_dir.glob("*.jsonl"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            cases.append(json.loads(line))
                    logger.debug(f"加载文件: {file_path.name}")
            except Exception as e:
                logger.error(f"加载文件失败 {file_path}: {e}")

        return cases

    @property
    def description(self) -> str:
        """工具描述"""
        return """查询历史应急指挥案例。

可根据事故类型、地点、关键词等条件查询相似的历史案例。返回案例的处置过程、经验教训等信息。"""

    @property
    def parameters(self) -> Dict[str, Any]:
        """参数定义"""
        return {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "string",
                    "description": "查询关键词，如'追尾'、'封闭'、'救援'等"
                },
                "accident_type": {
                    "type": "string",
                    "description": "事故类型，如'交通事故'、'自然灾害'等",
                    "enum": ["交通事故", "自然灾害", "危化品泄漏", "设施故障", "其他"]
                },
                "location": {
                    "type": "string",
                    "description": "地点关键词，如'G4高速'、'京港澳'等"
                }
            }
        }

    def execute(self, keywords: str = "", accident_type: str = "", location: str = "") -> str:
        """
        执行查询

        Args:
            keywords: 关键词
            accident_type: 事故类型
            location: 地点

        Returns:
            查询结果（JSON格式字符串）
        """
        logger.info(f"执行历史案例查询: keywords={keywords}, type={accident_type}, location={location}")

        # 过滤条件
        filtered = self._cases

        if keywords:
            keyword_list = keywords.split()
            filtered = [
                c for c in filtered
                if any(kw in c.get("title", "").lower() or
                       kw in c.get("description", "").lower() or
                       kw in str(c.get("response_actions", "")).lower()
                       for kw in keyword_list)
            ]
            logger.debug(f"关键词过滤后: {len(filtered)}条")

        if accident_type:
            filtered = [c for c in filtered if c.get("accident_type") == accident_type]
            logger.debug(f"事故类型过滤后: {len(filtered)}条")

        if location:
            filtered = [c for c in filtered if location in c.get("location", "")]
            logger.debug(f"地点过滤后: {len(filtered)}条")

        if not filtered:
            logger.warning("未找到匹配的历史案例")
            return json.dumps({
                "status": "not_found",
                "message": "未找到匹配的历史案例，请尝试其他查询条件",
                "count": 0
            }, ensure_ascii=False, indent=2)

        logger.info(f"查询成功: 找到{len(filtered)}条相关案例")
        return json.dumps({
            "status": "success",
            "count": len(filtered),
            "results": filtered[:5]  # 最多返回5条结果
        }, ensure_ascii=False, indent=2)
