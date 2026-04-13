"""最终应急指挥方案审核器。"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List

if TYPE_CHECKING:
    from ..providers import OpenAIProvider
    from .task_state import TaskState

logger = logging.getLogger(__name__)


@dataclass
class FinalPlanReviewResult:
    """最终方案审核结果。"""

    passed: bool
    score: int = 0
    summary: str = ""
    issues: List[str] = field(default_factory=list)
    revision_advice: List[str] = field(default_factory=list)
    raw_payload: Dict[str, Any] = field(default_factory=dict)


class FinalPlanReviewer:
    """用独立大模型对最终方案做格式和内容审核。"""

    SYSTEM_PROMPT = """你是交通应急指挥方案审核助手，只负责审核最终输出方案，不负责生成新方案。

请根据给定的任务上下文和候选最终方案，判断它是否可以直接展示给用户。

审核标准：
1. 是否满足标准化应急指挥方案格式，尤其是固定章节和顺序是否完整
2. 是否使用建议性表述，不能谎称已经通知队伍、下达指令、启动真实行动
3. 是否覆盖核心内容：事件概述、响应定级、指挥架构、预警发布、处置行动、资源调度、风险提示、依据引用
4. 如果某些信息确实缺失，是否明确写了“暂未获取”或“待现场确认”，而不是直接漏掉
5. 是否存在明显空洞、缺少关键依据、内容前后矛盾或过度简略的问题

输出要求：
- 只输出 JSON
- 不要输出 markdown
- JSON 结构如下：
{
  "passed": true,
  "score": 92,
  "summary": "一句话结论",
  "issues": ["问题1", "问题2"],
  "revision_advice": ["修改建议1", "修改建议2"]
}
"""

    def __init__(self, provider: "OpenAIProvider", max_tokens: int | None = None):
        self.provider = provider
        self.max_tokens = max_tokens or int(os.getenv("FINAL_REVIEW_MAX_TOKENS", "32000"))

    def review(self, task_state: "TaskState", candidate_plan: str) -> FinalPlanReviewResult:
        """审核最终方案。"""
        try:
            response = self.provider.chat(
                [
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": self._build_user_prompt(task_state, candidate_plan)},
                ],
                temperature=0.1,
                max_tokens=self.max_tokens,
            )
            payload = self._extract_json_payload(response.content or "")
        except Exception as error:
            logger.warning("FinalPlanReviewer 调用失败，回退到保守不通过结果: %s", error)
            payload = {}

        return self._normalize_result(payload)

    def _build_user_prompt(self, task_state: "TaskState", candidate_plan: str) -> str:
        """构造审核输入。"""
        return "\n".join(
            [
                "请审核下面这份候选最终方案。",
                "",
                "【任务上下文摘要】",
                task_state.build_context_summary(),
                "",
                "【候选最终方案】",
                candidate_plan or "空",
            ]
        )

    def _extract_json_payload(self, content: str) -> Dict[str, Any]:
        """从模型响应中提取 JSON。"""
        if not content:
            return {}

        candidates = [
            content.strip(),
            re.sub(r"^```json\s*", "", content.strip()).rstrip("`").strip(),
        ]
        matched = re.search(r"\{.*\}", content, re.DOTALL)
        if matched:
            candidates.append(matched.group(0))

        for candidate in candidates:
            try:
                return json.loads(candidate)
            except Exception:
                continue

        return {}

    def _normalize_result(self, payload: Dict[str, Any]) -> FinalPlanReviewResult:
        """将审核结果归一化。"""
        if not payload:
            return FinalPlanReviewResult(
                passed=False,
                score=0,
                summary="审核器未返回可解析结果，默认判定为需要重写。",
                issues=["审核器未返回可解析 JSON"],
                revision_advice=["请重新生成最终方案，并严格遵守既定模板和建议性表述要求。"],
                raw_payload={},
            )

        issues = payload.get("issues", []) or []
        advice = payload.get("revision_advice", []) or []

        if isinstance(issues, str):
            issues = [issues]
        if isinstance(advice, str):
            advice = [advice]

        return FinalPlanReviewResult(
            passed=bool(payload.get("passed", False)),
            score=int(payload.get("score", 0) or 0),
            summary=str(payload.get("summary", "") or ""),
            issues=[str(item) for item in issues if str(item).strip()],
            revision_advice=[str(item) for item in advice if str(item).strip()],
            raw_payload=payload,
        )
