"""
Provider模块

提供与不同大模型API的适配器。
"""

from .openai_provider import OpenAIProvider

__all__ = ["OpenAIProvider"]
