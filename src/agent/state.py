"""
对话状态管理

管理Agent的对话历史和状态。
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

from .message import Message

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

        # 如果超过最大历史数量，删除最旧的消息
        # 但要保留system消息（通常在开头）
        if len(self.messages) > self.max_history:
            # 保留system消息，删除其他最旧的消息
            system_messages = [m for m in self.messages if m.role.value == "system"]
            other_messages = [m for m in self.messages if m.role.value != "system"]

            # 删除最旧的非system消息
            if len(other_messages) > 1:
                other_messages.pop(0)
                self.messages = system_messages + other_messages

    def get_history(self) -> List[dict]:
        """
        获取对话历史（OpenAI格式）

        Returns:
            OpenAI格式的消息列表
        """
        return [msg.to_openai_format() for msg in self.messages]

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
