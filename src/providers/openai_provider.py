"""
OpenAI API Provider

提供OpenAI API的调用接口，支持工具调用（Function Calling）。
兼容所有OpenAI格式的API，包括：
- OpenAI官方API
- 阿里云百炼 DashScope API
- Azure OpenAI
- DeepSeek
- 其他兼容OpenAI格式的API
"""

import logging
import os
from typing import List, Optional, Any

from openai import OpenAI
from ..agent.message import ChatResponse
from .defaults import (
    DEFAULT_TEXT_API_KEY,
    DEFAULT_TEXT_BASE_URL,
    DEFAULT_TEXT_MAX_TOKENS,
    DEFAULT_TEXT_MODEL,
)

logger = logging.getLogger(__name__)


class OpenAIProvider:
    """
    OpenAI API Provider

    封装OpenAI API调用，支持chat completion和工具调用。
    兼容所有OpenAI格式的API（如Azure OpenAI、DashScope、DeepSeek等）。
    """

    def __init__(
        self,
        api_key: str = None,
        base_url: Optional[str] = None,
        model: str = DEFAULT_TEXT_MODEL,
        temperature: float = 0.7,
        max_tokens: int = DEFAULT_TEXT_MAX_TOKENS,
        provider: str = "auto"
    ):
        """
        初始化OpenAI Provider

        Args:
            api_key: API密钥（默认从环境变量读取）
            base_url: API基础URL（可选，默认根据provider自动设置）
            model: 使用的模型名称（默认 DeepSeek-V3.2）
            temperature: 温度参数（0-1，越高越随机）
            max_tokens: 最大生成token数
            provider: 服务提供商（auto/dashscope/openai/deepseek）

        支持的环境变量：
        - DASHSCOPE_API_KEY: 阿里云百炼API Key
        - OPENAI_API_KEY: OpenAI API Key
        """
        # 自动获取API Key
        if api_key is None:
            api_key = (
                os.getenv("OPENAI_API_KEY") or
                os.getenv("DASHSCOPE_API_KEY") or
                DEFAULT_TEXT_API_KEY
            )
            if not api_key:
                raise ValueError(
                    "请设置API Key：\n"
                    "- 阿里云百炼: 设置 DASHSCOPE_API_KEY 环境变量\n"
                    "- OpenAI-compatible: 设置 OPENAI_API_KEY 环境变量"
                )

        # 根据provider自动设置base_url
        if base_url is None:
            base_url = os.getenv("OPENAI_BASE_URL") or None

        if base_url is None:
            if provider == "auto":
                # 自动检测
                if model == DEFAULT_TEXT_MODEL:
                    provider = "openai_compatible_default"
                elif "dashscope" in os.getenv("DASHSCOPE_API_KEY", "").lower() or model.startswith("qwen"):
                    provider = "dashscope"
                elif os.getenv("OPENAI_API_KEY"):
                    provider = "openai"

            # 设置默认base_url
            if provider == "dashscope":
                base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
                logger.info("使用阿里云百炼 DashScope API")
            elif provider == "openai_compatible_default":
                base_url = DEFAULT_TEXT_BASE_URL
                logger.info("使用默认 OpenAI-compatible 文本模型端点")
            elif provider == "openai":
                base_url = "https://api.openai.com/v1"
                logger.info("使用OpenAI API")
            else:
                base_url = DEFAULT_TEXT_BASE_URL if model == DEFAULT_TEXT_MODEL else "https://api.openai.com/v1"

        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

        # 初始化OpenAI客户端
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )

        logger.info(f"初始化Provider: model={model}, base_url={base_url}")

    def chat(
        self,
        messages: List[dict],
        tools: Optional[List[dict]] = None,
        **kwargs
    ) -> ChatResponse:
        """
        发送聊天请求

        Args:
            messages: 消息列表（OpenAI格式）
            tools: 工具定义列表（可选）
            **kwargs: 其他参数（会覆盖初始化时的设置）

        Returns:
            ChatResponse对象

        Raises:
            Exception: API调用失败时抛出异常
        """
        # 合并参数
        params = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
        }

        # 如果有工具定义，添加工具调用支持
        if tools:
            params["tools"] = tools
            params["tool_choice"] = "auto"  # 让模型自动决定是否调用工具
            logger.debug(f"启用工具调用，工具数量: {len(tools)}")

        # 记录请求信息
        logger.info(f"发送请求: model={params['model']}, 消息数量={len(messages)}")

        try:
            # 调用OpenAI API
            response = self.client.chat.completions.create(**params)

            # 记录响应信息
            logger.info(
                f"收到响应: model={response.model}, "
                f"tokens={response.usage.total_tokens if hasattr(response, 'usage') else 'N/A'}, "
                f"finish_reason={response.choices[0].finish_reason}"
            )

            # 转换为ChatResponse对象
            return ChatResponse.from_openai(response)

        except Exception as e:
            logger.error(f"OpenAI API调用失败: {e}")
            raise
