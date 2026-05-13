"""
基于本地 JSON 文件的 Chainlit Data Layer。

读取 data/conversations/ 下的会话 JSON 文件，
在前端侧边栏展示历史对话列表，支持点击查看。
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from chainlit.data import BaseDataLayer
from chainlit.types import (
    Feedback,
    PageInfo,
    PaginatedResponse,
    ThreadDict,
    ThreadFilter,
)

logger = logging.getLogger(__name__)

CONVERSATIONS_DIR = Path(__file__).resolve().parents[1] / "data" / "conversations"


class JsonDataLayer(BaseDataLayer):
    """从本地 JSON 对话文件提供只读的历史浏览能力。"""

    def __init__(self, conversations_dir: Optional[str] = None):
        self.conversations_dir = Path(conversations_dir) if conversations_dir else CONVERSATIONS_DIR
        self._thread_cache: Dict[str, dict] = {}
        self._cache_timestamp: float = 0
        self._users: Dict[str, Any] = {}
        logger.info("JsonDataLayer 初始化: dir=%s, exists=%s", self.conversations_dir, self.conversations_dir.exists())

    def _load_all_sessions(self) -> Dict[str, dict]:
        """扫描目录加载所有会话文件（带 30 秒缓存）。"""
        now = time.time()
        if self._thread_cache and now - self._cache_timestamp < 30:
            return self._thread_cache

        result: Dict[str, dict] = {}
        if not self.conversations_dir.exists():
            logger.warning("对话目录不存在: %s", self.conversations_dir)
            return result

        for filepath in sorted(self.conversations_dir.glob("session_*.json"), reverse=True):
            try:
                with filepath.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                session_id = data.get("session_id", filepath.stem)
                # 跳过消息过少的会话
                msgs = data.get("messages", [])
                user_msgs = [m for m in msgs if m.get("role") == "user"]
                if not user_msgs:
                    continue
                result[session_id] = {
                    "filepath": str(filepath),
                    **data,
                }
            except Exception as e:
                logger.warning("加载会话文件失败: %s, error=%s", filepath, e)

        self._thread_cache = result
        self._cache_timestamp = now
        logger.info("已加载 %s 个历史会话", len(result))
        return result

    def _extract_thread_name(self, messages: list) -> str:
        """提取第一条用户消息作为线程名称。"""
        for msg in messages:
            if msg.get("role") == "user":
                content = (msg.get("content") or "").strip()
                if content:
                    return content[:80] + ("..." if len(content) > 80 else "")
        return "未命名会话"

    def _build_thread_dict(self, session_id: str, data: dict) -> ThreadDict:
        """将 JSON 数据转为 Chainlit ThreadDict 格式。"""
        messages = data.get("messages", [])
        thread_name = self._extract_thread_name(messages)

        created_at = data.get("start_time", "")
        try:
            created_at_dt = datetime.fromisoformat(created_at).isoformat()
        except (ValueError, TypeError):
            created_at_dt = datetime.now().isoformat()

        # 构造 steps（简单字典格式，不依赖 LiteralStep）
        steps = []
        for i, msg in enumerate(messages):
            role = msg.get("role", "")
            if role == "system":
                continue

            content = msg.get("content", "") or ""
            step = {
                "id": f"{session_id}_step_{i}",
                "threadId": session_id,
                "name": role,
                "type": "user_message" if role == "user" else ("tool" if role == "tool" else "assistant_message"),
                "input": content if role == "user" else "",
                "output": content if role != "user" else "",
                "createdAt": created_at_dt,
            }
            steps.append(step)

        return {
            "id": session_id,
            "name": thread_name,
            "createdAt": created_at_dt,
            "userId": "default",
            "userIdentifier": "user",
            "steps": steps,
            "metadata": {
                "message_count": data.get("message_count", len(messages)),
                "start_time": data.get("start_time", ""),
                "end_time": data.get("end_time", ""),
            },
            "tags": [],
        }

    # ---- Chainlit Data Layer 接口实现 ----

    async def get_thread(self, thread_id: str) -> Optional[ThreadDict]:
        sessions = self._load_all_sessions()
        data = sessions.get(thread_id)
        if not data:
            return None
        return self._build_thread_dict(thread_id, data)

    async def list_threads(
        self,
        pagination: "PageInfo",
        filters: "ThreadFilter",
    ) -> "PaginatedResponse[ThreadDict]":
        sessions = self._load_all_sessions()

        # 按时间倒序排列
        sorted_items = sorted(
            sessions.items(),
            key=lambda x: x[1].get("start_time", ""),
            reverse=True,
        )

        # 分页
        cursor = getattr(pagination, "cursor", None)
        first = getattr(pagination, "first", None) or 20
        start_index = 0

        if cursor:
            for i, (sid, _) in enumerate(sorted_items):
                if sid == cursor:
                    start_index = i + 1
                    break

        page_items = sorted_items[start_index: start_index + first]
        threads = [self._build_thread_dict(sid, data) for sid, data in page_items]

        has_next = start_index + first < len(sorted_items)
        end_cursor = page_items[-1][0] if page_items else None
        start_cursor = page_items[0][0] if page_items else None

        return PaginatedResponse(
            data=threads,
            pageInfo=PageInfo(
                hasNextPage=has_next,
                startCursor=start_cursor,
                endCursor=end_cursor,
            ),
        )

    async def get_thread_author(self, thread_id: str) -> str:
        return "user"

    async def create_step(self, step_dict: Any) -> None:
        pass

    async def create_user(self, user) -> None:
        identifier = getattr(user, "identifier", "") or "default"
        if not hasattr(user, "id"):
            user.id = identifier
        self._users[identifier] = user

    async def get_user(self, identifier: str) -> Optional[Any]:
        user = self._users.get(identifier)
        if user and not hasattr(user, "id"):
            user.id = identifier
        return user

    async def upsert_feedback(self, feedback: "Feedback") -> str:
        return ""

    async def delete_thread(self, thread_id: str) -> None:
        pass

    async def update_thread(
        self,
        thread_id: str,
        name: Optional[str] = None,
        user_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
        tags: Optional[List[str]] = None,
    ) -> None:
        pass

    async def delete_feedback(self, feedback_id: str) -> bool:
        return True

    async def update_step(self, step_dict: Any) -> None:
        pass

    async def build_debug_url(self) -> str:
        return ""

    async def create_element(self, element: Any) -> None:
        pass

    async def get_element(self, thread_id: str, element_id: str) -> Optional[Any]:
        return None

    async def delete_element(self, element_id: str) -> None:
        pass

    async def delete_step(self, step_id: str) -> None:
        pass

    async def close(self) -> None:
        pass
