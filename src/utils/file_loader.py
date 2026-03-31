"""
文件加载工具

提供便捷的文件加载函数。
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def load_json_files(directory: str) -> List[Dict[str, Any]]:
    """
    加载目录下所有JSON文件

    Args:
        directory: 目录路径

    Returns:
        JSON数据列表
    """
    data = []
    data_dir = Path(directory)

    if not data_dir.exists():
        logger.warning(f"目录不存在: {directory}")
        return data

    # 加载.json和.jsonl文件
    for pattern in ["*.json", "*.jsonl"]:
        for file_path in data_dir.glob(pattern):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    if file_path.suffix == ".jsonl":
                        # JSONL格式：每行一个JSON对象
                        for line in f:
                            if line.strip():
                                data.append(json.loads(line))
                    else:
                        # JSON格式
                        file_data = json.load(f)
                        if isinstance(file_data, list):
                            data.extend(file_data)
                        elif isinstance(file_data, dict):
                            data.append(file_data)

                logger.debug(f"加载文件: {file_path.name}, 数据条数: {len(data)}")

            except Exception as e:
                logger.error(f"加载文件失败 {file_path}: {e}")

    return data
