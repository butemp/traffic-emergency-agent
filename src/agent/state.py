"""
对话状态管理

管理Agent的对话历史和状态。
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

from .message import Message, MessageRole

logger = logging.getLogger(__name__)


class ConversationState:
    """
    对话状态管理类

    负责维护对话历史，支持保存和加载对话记录。
    """

    def __init__(self, max_history: int = 20, save_path: Optional[str] = None):
        """
        初始化对话状态

        Args:
            max_history: 保留的最大历史消息数量
            save_path: 对话历史保存路径（None表示不保存）
        """
        self.max_history = max_history
        self.save_path = save_path
        self.session_id = str(uuid4())[:8]  # 会话ID（前8位）
        self.messages: List[Message] = []
        self.start_time = datetime.now()

        logger.info(f"初始化对话会话: session_id={self.session_id}, max_history={max_history}")

    def add_message(self, message: Message) -> None:
        """
        添加消息到历史记录

        Args:
            message: 要添加的消息
        """
        self.messages.append(message)
        logger.debug(f"添加消息: role={message.role.value}, content长度={len(message.content)}")

        # 如果超过最大历史数量，优先压缩早期上下文，而不是直接删除。
        # 直接删除可能破坏 assistant tool_call 与 tool 返回之间的配对关系。
        if len(self.messages) > self.max_history:
            self.compact_for_context(
                keep_recent=max(12, min(20, self.max_history // 2)),
                max_summary_chars=8000,
            )

    def get_history(self) -> List[dict]:
        """
        获取对话历史（OpenAI格式）

        Returns:
            OpenAI格式的消息列表
        """
        return [msg.to_openai_format() for msg in self.messages]

    def compact_for_context(
        self,
        keep_recent: int = 16,
        max_summary_chars: int = 8000,
    ) -> bool:
        """
        将较早的上下文压缩为摘要，保留最近消息原文。

        这是无模型依赖的轻量压缩，只处理发送给 LLM 的上下文历史；
        TaskState/tool_call_log 中的结构化状态仍继续保留。
        """
        if len(self.messages) <= keep_recent + 2:
            return False

        first_index = 1 if self.messages and self.messages[0].role.value == "system" else 0
        recent_start = self._safe_recent_start(first_index, keep_recent)
        old_messages = self.messages[first_index:recent_start]
        recent_messages = self.messages[recent_start:]

        if not old_messages:
            return False

        summary = self._build_context_summary(old_messages, max_summary_chars=max_summary_chars)
        summary_msg = Message(role=MessageRole.SYSTEM, content=summary)

        if first_index == 1:
            self.messages = [self.messages[0], summary_msg, *recent_messages]
        else:
            self.messages = [summary_msg, *recent_messages]

        logger.info(
            "上下文已压缩: old_messages=%s, kept_recent=%s, current_messages=%s",
            len(old_messages),
            len(recent_messages),
            len(self.messages),
        )
        return True

    def _safe_recent_start(self, first_index: int, keep_recent: int) -> int:
        start = max(first_index, len(self.messages) - keep_recent)
        while start > first_index and not self._has_valid_tool_pairs(self.messages[start:]):
            start -= 1
        return start

    @staticmethod
    def _has_valid_tool_pairs(messages: List[Message]) -> bool:
        tool_call_ids = set()
        for message in messages:
            for tool_call in message.tool_calls or []:
                tool_call_ids.add(tool_call.id)

        for message in messages:
            if message.role.value == "tool" and message.tool_call_id not in tool_call_ids:
                return False
        return True

    def _build_context_summary(self, messages: List[Message], max_summary_chars: int) -> str:
        lines = [
            "【上下文压缩摘要】",
            "以下内容由系统为控制上下文窗口自动压缩，保留早期对话、工具调用和纠偏信息的摘要。",
            "完整事实应优先以 TaskState 摘要、最近工具结果和最新用户输入为准；不要把摘要中的建议写成已经真实执行。",
            "",
        ]

        for index, message in enumerate(messages, start=1):
            item = self._summarize_message(index, message)
            if not item:
                continue
            lines.append(item)

            if sum(len(line) for line in lines) >= max_summary_chars:
                lines.append("...（更早上下文已继续省略）")
                break

        summary = "\n".join(lines)
        if len(summary) > max_summary_chars:
            summary = summary[: max_summary_chars - 20] + "\n...（摘要截断）"
        return summary

    @staticmethod
    def _summarize_message(index: int, message: Message) -> str:
        role = message.role.value
        content = ConversationState._compact_text(message.content, limit=420)

        if role == "assistant" and message.tool_calls:
            calls = []
            for tool_call in message.tool_calls:
                args = ConversationState._compact_text(json.dumps(tool_call.arguments, ensure_ascii=False), limit=180)
                calls.append(f"{tool_call.name}({args})")
            return f"{index}. assistant 调用工具: " + "；".join(calls)

        if role == "tool":
            return f"{index}. tool 返回摘要: {content}"

        if role == "system":
            if "上下文压缩摘要" in message.content:
                return f"{index}. system 历史压缩摘要: {content}"
            if "你刚刚调用了以下工具" in message.content:
                return ""
            return f"{index}. system 纠偏/流程提示: {content}"

        if role == "user":
            return f"{index}. user: {content}"

        if role == "assistant":
            return f"{index}. assistant: {content}"

        return f"{index}. {role}: {content}"

    @staticmethod
    def _compact_text(text: str, limit: int = 420) -> str:
        cleaned = re.sub(r"\s+", " ", text or "").strip()
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 3] + "..."

    def save(self) -> None:
        """
        保存对话历史到文件
        """
        if not self.save_path:
            return

        try:
            save_dir = Path(self.save_path)
            save_dir.mkdir(parents=True, exist_ok=True)

            filename = f"session_{self.session_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            filepath = save_dir / filename

            # 序列化对话历史
            data = {
                "session_id": self.session_id,
                "start_time": self.start_time.isoformat(),
                "end_time": datetime.now().isoformat(),
                "message_count": len(self.messages),
                "messages": [
                    {
                        "role": msg.role.value,
                        "content": msg.content,
                        "tool_calls": [
                            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                            for tc in msg.tool_calls
                        ] if msg.tool_calls else []
                    }
                    for msg in self.messages
                ]
            }

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            logger.info(f"对话历史已保存: {filepath}")

        except Exception as e:
            logger.error(f"保存对话历史失败: {e}")

    def clear(self) -> None:
        """
        清空对话历史
        """
        self.messages.clear()
        logger.info("对话历史已清空")
