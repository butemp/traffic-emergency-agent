"""
消息模型

定义Agent通信中使用的消息结构。
"""

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Any


class MessageRole(Enum):
    """消息角色枚举"""
    USER = "user"           # 用户消息
    ASSISTANT = "assistant"  # 助手消息
    SYSTEM = "system"       # 系统消息
    TOOL = "tool"           # 工具返回结果


@dataclass
class ToolCall:
    """
    工具调用信息

    Attributes:
        id: 工具调用的唯一标识符
        name: 工具名称
        arguments: 工具调用参数（字典格式）
    """
    id: str
    name: str
    arguments: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """转换为字典格式（用于OpenAI API）"""
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False)
            }
        }


@dataclass
class Message:
    """
    消息类

    表示对话中的一条消息，可以是用户消息、助手消息或工具返回结果。

    Attributes:
        role: 消息角色（user/assistant/system/tool）
        content: 消息内容
        tool_calls: 工具调用列表（仅assistant角色可能有）
        tool_call_id: 工具调用ID（仅tool角色需要）
    """
    role: MessageRole
    content: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    tool_call_id: Optional[str] = None

    def to_openai_format(self) -> dict:
        """
        转换为OpenAI API格式

        Returns:
            符合OpenAI API格式的消息字典
        """
        msg = {
            "role": self.role.value,
            "content": self.content
        }

        # 如果是助手消息且有工具调用
        if self.role == MessageRole.ASSISTANT and self.tool_calls:
            msg["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
            # 如果有工具调用，content可以为空
            if not msg["content"]:
                msg["content"] = None

        # 如果是工具返回消息
        if self.role == MessageRole.TOOL:
            msg["tool_call_id"] = self.tool_call_id

        return msg

    @classmethod
    def from_openai_format(cls, data: dict) -> "Message":
        """
        从OpenAI API格式创建消息对象

        Args:
            data: OpenAI API返回的消息字典

        Returns:
            Message对象
        """
        role = MessageRole(data["role"])
        content = data.get("content", "")

        # 处理工具调用
        tool_calls = []
        if "tool_calls" in data and data["tool_calls"]:
            for tc in data["tool_calls"]:
                tool_calls.append(ToolCall(
                    id=tc["id"],
                    name=tc["function"]["name"],
                    arguments=json.loads(tc["function"]["arguments"])
                ))

        return cls(
            role=role,
            content=content,
            tool_calls=tool_calls
        )


@dataclass
class ChatResponse:
    """
    聊天响应类

    表示LLM的响应结果。

    Attributes:
        content: 响应内容
        tool_calls: 工具调用列表
        model: 使用的模型名称
        usage: token使用情况
    """
    content: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    model: str = ""
    usage: dict = field(default_factory=dict)

    @classmethod
    def from_openai(cls, response: Any) -> "ChatResponse":
        """
        从OpenAI API响应创建ChatResponse对象

        Args:
            response: OpenAI API返回的响应对象

        Returns:
            ChatResponse对象
        """
        choice = response.choices[0]
        message = choice.message

        # 解析工具调用
        tool_calls = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments)
                ))

        # 获取响应内容
        content = message.content or ""

        return cls(
            content=content,
            tool_calls=tool_calls,
            model=response.model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            } if hasattr(response, "usage") else {}
        )
