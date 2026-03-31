"""
查询法规/规则/应急预案工具

从本地文件中查询交通应急相关的法规、规则和应急预案。
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, List
from .base import BaseTool

logger = logging.getLogger(__name__)


class QueryRegulations(BaseTool):
    """
    查询法规工具

    根据关键词、事故类型、严重程度等条件查询相关法规和预案。
    """

    def __init__(self, data_path: str = "data/regulations"):
        """
        初始化工具

        Args:
            data_path: 法规数据文件目录
        """
        super().__init__(data_path)
        # 加载所有法规数据
        self._regulations = self._load_regulations()
        logger.info(f"加载法规数据: {len(self._regulations)}条")

    def _load_regulations(self) -> List[Dict[str, Any]]:
        """
        从本地加载法规数据

        Returns:
            法规列表
        """
        regulations = []
        data_dir = Path(self.data_path)

        if not data_dir.exists():
            logger.warning(f"法规数据目录不存在: {self.data_path}")
            return regulations

        # 支持JSON和JSONL格式
        for file_path in data_dir.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        regulations.extend(data)
                    elif isinstance(data, dict):
                        regulations.append(data)
                    logger.debug(f"加载文件: {file_path.name}")
            except Exception as e:
                logger.error(f"加载文件失败 {file_path}: {e}")

        # 也支持jsonl格式
        for file_path in data_dir.glob("*.jsonl"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            regulations.append(json.loads(line))
                    logger.debug(f"加载文件: {file_path.name}")
            except Exception as e:
                logger.error(f"加载文件失败 {file_path}: {e}")

        return regulations

    @property
    def description(self) -> str:
        """工具描述"""
        return """查询交通应急相关的法规、规则和应急预案。

可根据关键词、事故类型、严重程度等条件查询。返回相关的法规条文和处置要求。"""

    @property
    def parameters(self) -> Dict[str, Any]:
        """参数定义"""
        return {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "string",
                    "description": "查询关键词，如'高速公路封闭'、'交通事故'等"
                },
                "accident_type": {
                    "type": "string",
                    "description": "事故类型，如'交通事故'、'自然灾害'、'危化品泄漏'等",
                    "enum": ["交通事故", "自然灾害", "危化品泄漏", "其他"]
                },
                "severity": {
                    "type": "string",
                    "description": "事故严重程度",
                    "enum": ["特别重大", "重大", "较大", "一般"]
                }
            }
        }

    def execute(self, keywords: str = "", accident_type: str = "", severity: str = "") -> str:
        """
        执行查询

        Args:
            keywords: 关键词
            accident_type: 事故类型
            severity: 严重程度

        Returns:
            查询结果（JSON格式字符串）
        """
        logger.info(f"执行法规查询: keywords={keywords}, type={accident_type}, severity={severity}")

        # 过滤条件
        filtered = self._regulations

        if keywords:
            keyword_list = keywords.split()
            filtered = [
                r for r in filtered
                if any(kw in r.get("title", "").lower() or kw in r.get("content", "").lower()
                       for kw in keyword_list)
            ]
            logger.debug(f"关键词过滤后: {len(filtered)}条")

        if accident_type:
            filtered = [r for r in filtered if r.get("accident_type") == accident_type]
            logger.debug(f"事故类型过滤后: {len(filtered)}条")

        if severity:
            filtered = [r for r in filtered if r.get("severity") == severity]
            logger.debug(f"严重程度过滤后: {len(filtered)}条")

        if not filtered:
            logger.warning("未找到匹配的法规")
            return json.dumps({
                "status": "not_found",
                "message": "未找到匹配的法规，请尝试其他关键词或条件",
                "count": 0
            }, ensure_ascii=False, indent=2)

        logger.info(f"查询成功: 找到{len(filtered)}条相关法规")
        return json.dumps({
            "status": "success",
            "count": len(filtered),
            "results": filtered[:5]  # 最多返回5条结果
        }, ensure_ascii=False, indent=2)
