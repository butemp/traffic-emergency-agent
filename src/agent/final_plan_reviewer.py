"""最终应急指挥方案审核器。"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List

from ..providers.defaults import DEFAULT_TEXT_MAX_TOKENS

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
    section_reviews: List[Dict[str, Any]] = field(default_factory=list)
    raw_payload: Dict[str, Any] = field(default_factory=dict)


class FinalPlanReviewer:
    """用独立大模型对最终方案做格式和内容审核。"""

    SYSTEM_PROMPT = """你是交通应急指挥方案审核助手，只负责审核最终输出方案，不负责生成新方案。

请根据给定的任务上下文和候选最终方案，判断它是否可以直接展示给用户。

方案应该按以下结构组织（必须严格遵守，不能增删章节）：

【应急处置总览】（5 个要点：一、事件现场基本情况；二、预案匹配与组织预警和响应；三、物资装备与调度；四、处置流程建议；五、次生风险）

【应急处置详情】（7 个固定章节）：
- 一、事件现场基本情况
- 二、预案匹配与组织预警和响应
- 三、应急组织机构
- 四、物资装备与调度
- 五、处置流程建议（包括后期处置、新闻发布）
- 六、次生风险
- 七、引用依据

除"三、应急组织机构"固定输出两张表外，每个详情章节只能有一张固定字段表，列名严格按规范不能改写：
- 一：字段、内容（5 行：事件地点/天气情况/事件简述/周边环境/主要影响）
- 二：字段、内容（5 行：匹配预案/事件等级/预警发布/启动响应/判断依据）
- 三：固定两张独立 Markdown 表格。第一张为工作组表：工作组、牵头单位、主要职责（至少 7 个工作组：现场指挥组/综合协调组/抢险处置组/医疗救护组/后勤保障组/信息发布组/专家组）；第二张为"专家库支持"表：专家姓名、所在单位、专业方向、联系电话、建议支持方式
- 四：所需物资、推荐调度来源、距离、预计到达时间、地点、联系人信息、资源缺口（6 列）
- 五：序号、行动、责任单位、协同单位、引用依据（5 列，至少 10 行）
- 六：触发条件、风险描述、影响后果、应对措施、责任单位（5 列，至少 5 条）
- 七：依据类型、依据名称、引用章节/模块、引用内容摘要、支撑决策（5 列）

审核标准：
0. 完整性优先；只要包含上述总览 + 7 章节详情，且除第三节固定两张表外每章只有一张固定表，则视为结构合格
1. 是否严格按上述【应急处置总览】+【应急处置详情】结构输出，且 7 章节顺序固定不变
2. 是否使用建议性表述，不能谎称已经通知队伍、下达指令、启动真实行动
3. 各章节固定表的列名是否完全匹配（API 会按列名结构化提取，不能改写）
4. 资源类别是否使用中文名称，不能直接输出 WARNING、PPE、SIGN、VEHICLE、RESCUE、COMMS 等内部编码
5. 七、引用依据 的"引用章节/模块"列是否填了 get_emergency_plan 返回的 hit_path（如 "应急响应.处置措施.Ⅱ级应急响应处置措施"），而非笼统的"第X节"
6. 三、应急组织机构 的"应急工作组"是否拆成多行（每行一组），而不是把（1）（2）（3）粘在一段文字里
6.1 三、应急组织机构 的"专家库支持"是否单独使用 Markdown 表格，且列名为"专家姓名、所在单位、专业方向、联系电话、建议支持方式"；如果写成项目符号列表或普通段落，应判定不合格
7. 四、物资装备与调度 的每一行是否基于 search_resources 实际返回，不能编造仓库名、电话、物资
8. 五、处置流程建议 是否至少 10 行，覆盖：现场警戒、伤员排查、二次排查、家属联络、二次事故防范、清障恢复、信息报送（初报/续报/终报）、新闻发布、舆情监测、总结评估
9. 六、次生风险 是否至少 5 条；应对措施是否具体到动作（如"上游设置渐变式警戒区+锥桶渠化"），不要写"加强管理"
10. 如某字段确实缺失，是否明确写"暂未获取"或"待现场确认"，而不是直接漏掉
11. Markdown 格式是否规范：所有表格是否有表头行和分隔行（|---|---|），每行列数是否与表头一致，表格前后是否留空行
12. 是否出现额外的过时章节名（如"事件概述"/"响应定级"/"预警发布"/"指挥架构"/"资源调度方案"/"信息报送与新闻发布"/"风险提示与注意事项"/"依据引用"等），如有应判定结构不合格
13. 是否出现额外子表（如"补充说明"/"事件基础信息"/"第一梯队/第二梯队"/"关键物资用途说明"/"资源覆盖与缺口分析"/"安全风险/处置风险/衍生风险"），用户已要求精简，这些不应出现

输出要求：
- 只输出 JSON
- 不要输出 markdown
- JSON 结构如下：
{
  "passed": true,
  "score": 92,
  "summary": "一句话结论",
  "issues": ["问题1", "问题2"],
  "revision_advice": ["修改建议1", "修改建议2"],
  "section_reviews": [
    {
      "section": "三、应急组织机构",
      "passed": false,
      "score": 60,
      "issues": ["应急工作组段落未拆成多行表格"],
      "revision_advice": "把段落里的（1）综合协调组、（2）应急指挥组等按编号拆成独立的表格行"
    }
  ]
}
"""

    def __init__(self, provider: "OpenAIProvider", max_tokens: int | None = None):
        self.provider = provider
        configured_tokens = os.getenv("FINAL_REVIEW_MAX_TOKENS") or os.getenv("OPENAI_MAX_TOKENS")
        try:
            fallback_tokens = int(configured_tokens) if configured_tokens else DEFAULT_TEXT_MAX_TOKENS
        except (TypeError, ValueError):
            fallback_tokens = DEFAULT_TEXT_MAX_TOKENS
        self.max_tokens = max_tokens or fallback_tokens

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
                section_reviews=[],
                raw_payload={},
            )

        issues = payload.get("issues", []) or []
        advice = payload.get("revision_advice", []) or []
        section_reviews = payload.get("section_reviews", []) or []

        if isinstance(issues, str):
            issues = [issues]
        if isinstance(advice, str):
            advice = [advice]
        if isinstance(section_reviews, dict):
            section_reviews = [section_reviews]
        if not isinstance(section_reviews, list):
            section_reviews = []

        normalized_section_reviews: List[Dict[str, Any]] = []
        for item in section_reviews:
            if not isinstance(item, dict):
                continue
            normalized = {
                "section": str(item.get("section", "") or ""),
                "passed": bool(item.get("passed", False)),
                "score": int(item.get("score", 0) or 0),
                "issues": item.get("issues", []) or [],
                "revision_advice": str(item.get("revision_advice", "") or ""),
            }
            if isinstance(normalized["issues"], str):
                normalized["issues"] = [normalized["issues"]]
            normalized["issues"] = [str(issue) for issue in normalized["issues"] if str(issue).strip()]
            normalized_section_reviews.append(normalized)

        for item in normalized_section_reviews:
            if item.get("passed"):
                continue
            section = item.get("section") or "未指定章节"
            for issue in item.get("issues", []):
                issues.append(f"{section}: {issue}")
            if item.get("revision_advice"):
                advice.append(f"{section}: {item['revision_advice']}")

        return FinalPlanReviewResult(
            passed=bool(payload.get("passed", False)),
            score=int(payload.get("score", 0) or 0),
            summary=str(payload.get("summary", "") or ""),
            issues=[str(item) for item in issues if str(item).strip()],
            revision_advice=[str(item) for item in advice if str(item).strip()],
            section_reviews=normalized_section_reviews,
            raw_payload=payload,
        )
