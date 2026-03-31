"""
工具基类

定义所有工具的基础接口和注册机制。
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class BaseTool(ABC):
    """
    工具基类

    所有工具都需要继承这个类，并实现execute方法。
    """

    def __init__(self, data_path: str = None):
        """
        初始化工具

        Args:
            data_path: 工具数据路径（可选）
        """
        self.data_path = data_path
        # 如果子类没有覆盖name属性，则设置默认值
        if not hasattr(type(self), 'name'):
            self.name = self.__class__.__name__
        logger.debug(f"初始化工具: {self.name}")

    @property
    @abstractmethod
    def description(self) -> str:
        """
        工具描述

        Returns:
            工具的功能描述，用于LLM理解工具用途
        """
        pass

    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """
        工具参数定义

        Returns:
            JSON Schema格式的参数定义
        """
        pass

    @abstractmethod
    def execute(self, **kwargs) -> str:
        """
        执行工具

        Args:
            **kwargs: 工具参数

        Returns:
            工具执行结果（字符串格式）
        """
        pass

    def run(self, **kwargs) -> str:
        """
        [兼容性别名] 执行工具 (run -> execute)
        Chainlit 或某些框架可能习惯调用 .run()
        """
        return self.execute(**kwargs)

    def to_openai_format(self) -> Dict[str, Any]:
        """
        转换为OpenAI Function Calling格式

        Returns:
            OpenAI格式的工具定义
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }


class ToolRegistry:
    """
    工具注册表

    管理所有可用的工具。
    """

    def __init__(self):
        """初始化工具注册表"""
        self._tools: Dict[str, BaseTool] = {}
        logger.info("初始化工具注册表")

    def register(self, tool: BaseTool) -> None:
        """
        注册工具

        Args:
            tool: 要注册的工具实例
        """
        self._tools[tool.name] = tool
        logger.info(f"注册工具: {tool.name}")

    def get(self, name: str) -> BaseTool:
        """
        获取工具

        Args:
            name: 工具名称

        Returns:
            工具实例

        Raises:
            KeyError: 工具不存在
        """
        if name not in self._tools:
            logger.error(f"工具不存在: {name}")
            raise KeyError(f"工具不存在: {name}")
        return self._tools[name]

    def list_tools(self) -> List[str]:
        """
        列出所有工具名称

        Returns:
            工具名称列表
        """
        return list(self._tools.keys())

    def to_openai_formats(self) -> List[Dict[str, Any]]:
        """
        获取所有工具的OpenAI格式定义

        Returns:
            OpenAI格式的工具定义列表
        """
        return [tool.to_openai_format() for tool in self._tools.values()]
