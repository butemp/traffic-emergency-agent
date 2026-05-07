"""章节化最终应急指挥方案生成流水线。"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .task_state import TaskState

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SectionSpec:
    """最终方案单章节生成规范。"""

    key: str
    title: str
    filename: str
    min_chars: int
    required_terms: tuple[str, ...]
    instructions: str


@dataclass
class SectionReview:
    """单章节审核结果。"""

    passed: bool
    score: int = 0
    issues: List[str] = field(default_factory=list)
    revision_advice: List[str] = field(default_factory=list)
    raw_payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FinalPlanPipelineResult:
    """章节化流水线输出结果。"""

    final_markdown: str
    run_dir: Path
    evidence_path: Path
    section_texts: Dict[str, str]
    section_paths: Dict[str, Path]
    review_paths: Dict[str, List[Path]]
    exhausted_sections: List[str] = field(default_factory=list)


SECTION_SPECS: tuple[SectionSpec, ...] = (
    SectionSpec(
        key="event_overview",
        title="一、事件概述",
        filename="01_event_overview.md",
        min_chars=260,
        required_terms=("事件类型", "事发时间", "事发位置", "经纬度", "事件描述", "伤亡情况", "道路影响", "天气状况", "路况状况"),
        instructions=(
            "用表格让指挥员快速掌握事件全貌。必须覆盖事件类型、时间、位置、经纬度、"
            "伤亡/被困、道路影响、天气、路况、信息来源和待确认项。"
        ),
    ),
    SectionSpec(
        key="response_level",
        title="二、响应定级",
        filename="02_response_level.md",
        min_chars=300,
        required_terms=("响应级别", "定级依据", "响应启动主体", "适用预案", "预案依据", "复核条件"),
        instructions=(
            "说明响应级别、级别代码、定级依据、启动主体、适用预案、叠加预案、预案条款摘要、"
            "复核升级/降级条件。不能只写结论。"
        ),
    ),
    SectionSpec(
        key="command_structure",
        title="三、指挥架构",
        filename="03_command_structure.md",
        min_chars=650,
        required_terms=("总指挥", "副总指挥", "应急管理", "公安", "消防", "医疗", "专家", "职责", "首要动作"),
        instructions=(
            "必须详细列出总指挥、副总指挥和不少于 7 个工作组。工作组至少覆盖综合协调、"
            "公安交管、消防救援、医疗救援、抢险清障、专家技术支持、信息发布与舆情、善后安抚。"
            "如果专家库有结果，必须写专家姓名、单位、专业方向和建议支持方式。"
        ),
    ),
    SectionSpec(
        key="warning_release",
        title="四、预警发布",
        filename="04_warning_release.md",
        min_chars=320,
        required_terms=("预警级别", "发布主体", "发布流程", "发布渠道", "预警内容", "更新频率", "解除条件", "预案依据"),
        instructions=(
            "写清预警级别、发布主体、发布流程、渠道、内容要点、更新频率、解除条件，"
            "并给出可直接改写发布的预警提示文本。"
        ),
    ),
    SectionSpec(
        key="action_plan",
        title="五、处置行动方案",
        filename="05_action_plan.md",
        min_chars=900,
        required_terms=("先期处置", "全面响应", "持续处置", "现场警戒", "交通", "二次排查", "家属", "舆情", "责任单位", "时间要求"),
        instructions=(
            "按三个阶段写行动表，合计不少于 12 条。每条必须包含行动内容、责任单位、协同单位、"
            "时间要求、预案/工具依据。必须包含涉险人员二次排查、其他伤员排查、检伤分类和转运、"
            "家属联络安抚、现场警戒、交通分流、二次事故防范。"
        ),
    ),
    SectionSpec(
        key="resource_dispatch",
        title="六、资源调度方案",
        filename="06_resource_dispatch.md",
        min_chars=1000,
        required_terms=(
            "第一梯队", "第二梯队", "外部资源", "专家技术支持", "资源覆盖", "联系人", "电话",
            "调度路径", "可调配物资", "用途", "使用位置", "调度理由", "缺口", "补充建议",
        ),
        instructions=(
            "这是最关键章节之一。必须基于实际资源、专家和路线数据写。按 #### 第一梯队、#### 第二梯队、"
            "#### 外部资源补充、#### 专家技术支持、#### 关键物资用途说明、#### 资源覆盖与缺口分析组织。"
            "每个资源单独成行，写清资源名称、类型、所属单位/出发地、可调配物资/队伍能力、距离、"
            "预计到达、调度路径、联系人、电话。关键物资用途说明要写用途、使用位置、调度理由、注意事项。"
        ),
    ),
    SectionSpec(
        key="reporting",
        title="七、信息报送与新闻发布",
        filename="07_reporting.md",
        min_chars=480,
        required_terms=("初报", "续报", "终报", "报送对象", "新闻发布", "舆情", "责任单位", "回应口径"),
        instructions=(
            "覆盖初报、续报、终报、报送对象、方式、时限、新闻发布主体、发布内容、舆情监测、"
            "回应口径和家属沟通边界。"
        ),
    ),
    SectionSpec(
        key="risks",
        title="八、风险提示与注意事项",
        filename="08_risks.md",
        min_chars=1000,
        required_terms=("安全风险", "处置风险", "衍生风险", "风险描述", "触发条件", "影响后果", "应对措施", "责任单位", "监测指标", "升级条件"),
        instructions=(
            "必须分为 #### 安全风险、#### 处置风险、#### 衍生风险。每类至少 3 条，优先写 10-12 条。"
            "每条风险必须用表格写清风险描述、触发条件、影响后果、应对措施、责任单位、监测指标、升级条件，"
            "并结合本次事故的天气、路况、伤亡、资源缺口、舆情和家属安抚实际情况。"
        ),
    ),
    SectionSpec(
        key="references",
        title="九、依据引用",
        filename="09_references.md",
        min_chars=340,
        required_terms=("预案名称", "引用章节", "引用内容", "支撑", "工具结果", "案例"),
        instructions=(
            "汇总预案、法规/RAG、工具结果、资源调度、路线规划、风险评估和历史案例依据。"
            "用表格写清依据名称、章节/模块、引用内容摘要、支撑哪个处置决策。"
        ),
    ),
)

STANDARD_SECTION_TITLES = tuple(spec.title for spec in SECTION_SPECS)


class FinalPlanPipeline:
    """把最终方案拆成事实包、章节生成、章节审核和最终合并。"""

    WRITER_SYSTEM_PROMPT = """你是交通应急指挥方案章节撰写助手。

你只负责撰写指定的一个章节，不要输出其他章节。

硬性规则：
- 只能基于证据包和已有候选方案中的事实写，不能编造仓库、队伍、专家、路线、电话或预案条款。
- 系统没有真实通知、派遣、下达指令或启动现实行动的能力；所有动作必须写成“建议、拟派、应由人工联系、待现场确认”。
- 信息缺失时写“暂未获取”或“待现场确认”，不要空着，也不要自行补。
- 资源类别必须使用中文名称，不能输出 WARNING、PPE、SIGN、VEHICLE、RESCUE、COMMS 等内部编码。
- 章节标题必须严格使用“### {section_title}”。
- 只输出当前章节 Markdown，不要输出 agent_control，不要输出 JSON，不要解释你的写作过程。
"""

    REVIEW_SYSTEM_PROMPT = """你是交通应急指挥方案章节审核助手。

请只审核指定章节是否能直接进入最终方案。重点检查：
1. 是否只包含指定章节，标题是否正确；
2. 是否足够详细，是否覆盖该章节必填字段；
3. 是否基于证据包，是否有凭空编造；
4. 是否把建议动作写成已经执行；
5. Markdown 表格是否规范；
6. 是否出现 WARNING、PPE、SIGN、VEHICLE 等内部英文资源编码。

只输出 JSON：
{
  "passed": true,
  "score": 90,
  "issues": ["问题1"],
  "revision_advice": ["修改建议1"]
}
"""

    def __init__(
        self,
        provider: Any,
        output_root: Optional[str | Path] = None,
        max_section_rounds: Optional[int] = None,
        section_max_tokens: Optional[int] = None,
        review_max_tokens: Optional[int] = None,
    ):
        self.provider = provider
        self.output_root = Path(output_root or os.getenv("FINAL_PLAN_OUTPUT_DIR", "outputs/final_plan_runs"))
        self.max_section_rounds = max_section_rounds or self._int_env("FINAL_PLAN_SECTION_REVIEW_ROUNDS", 2)
        self.section_max_tokens = section_max_tokens or self._int_env("FINAL_PLAN_SECTION_MAX_TOKENS", 12000)
        self.review_max_tokens = review_max_tokens or self._int_env("FINAL_PLAN_SECTION_REVIEW_MAX_TOKENS", 4096)

    def generate(
        self,
        task_state: TaskState,
        seed_plan: str = "",
        global_feedback: str = "",
    ) -> FinalPlanPipelineResult:
        """生成完整章节化最终方案。"""
        run_dir = self._create_run_dir()
        sections_dir = run_dir / "sections"
        reviews_dir = run_dir / "reviews"
        sections_dir.mkdir(parents=True, exist_ok=True)
        reviews_dir.mkdir(parents=True, exist_ok=True)

        evidence = self._build_evidence_bundle(task_state=task_state, seed_plan=seed_plan)
        evidence_path = run_dir / "evidence_bundle.md"
        self._write_text(evidence_path, evidence)

        section_texts: Dict[str, str] = {}
        section_paths: Dict[str, Path] = {}
        review_paths: Dict[str, List[Path]] = {}
        exhausted_sections: List[str] = []

        for spec in SECTION_SPECS:
            text, paths, exhausted = self._generate_section_with_review(
                spec=spec,
                evidence=evidence,
                seed_plan=seed_plan,
                global_feedback=global_feedback,
                sections_dir=sections_dir,
                reviews_dir=reviews_dir,
            )
            section_texts[spec.title] = text
            section_path = sections_dir / spec.filename
            self._write_text(section_path, text)
            section_paths[spec.title] = section_path
            review_paths[spec.title] = paths
            if exhausted:
                exhausted_sections.append(spec.title)

        final_markdown = self._merge_sections(section_texts)
        self._write_text(run_dir / "final_plan.md", final_markdown)

        return FinalPlanPipelineResult(
            final_markdown=final_markdown,
            run_dir=run_dir,
            evidence_path=evidence_path,
            section_texts=section_texts,
            section_paths=section_paths,
            review_paths=review_paths,
            exhausted_sections=exhausted_sections,
        )

    def repair_from_review(
        self,
        task_state: TaskState,
        pipeline_result: FinalPlanPipelineResult,
        review_result: Any,
        guardrail_issues: List[str],
        attempt: int,
    ) -> FinalPlanPipelineResult:
        """根据全局审核意见只重写问题章节。"""
        failed_titles = self._select_failed_sections(review_result, guardrail_issues)
        if not failed_titles:
            failed_titles = {"三、指挥架构", "五、处置行动方案", "六、资源调度方案", "八、风险提示与注意事项"}

        evidence = self._read_text(pipeline_result.evidence_path)
        sections_dir = pipeline_result.run_dir / "sections"
        reviews_dir = pipeline_result.run_dir / "reviews"
        section_texts = dict(pipeline_result.section_texts)
        section_paths = dict(pipeline_result.section_paths)
        review_paths = {title: list(paths) for title, paths in pipeline_result.review_paths.items()}
        exhausted_sections = list(pipeline_result.exhausted_sections)
        global_feedback = self._format_global_feedback(review_result, guardrail_issues)

        for spec in SECTION_SPECS:
            if spec.title not in failed_titles:
                continue

            section_feedback = self._filter_feedback_for_section(spec.title, global_feedback)
            previous_draft = section_texts.get(spec.title, "")
            text, paths, exhausted = self._generate_section_with_review(
                spec=spec,
                evidence=evidence,
                seed_plan=previous_draft,
                global_feedback=section_feedback,
                sections_dir=sections_dir,
                reviews_dir=reviews_dir,
                tag=f"global_retry_{attempt}",
            )
            section_texts[spec.title] = text
            section_path = sections_dir / spec.filename
            self._write_text(section_path, text)
            section_paths[spec.title] = section_path
            review_paths.setdefault(spec.title, []).extend(paths)
            if exhausted and spec.title not in exhausted_sections:
                exhausted_sections.append(spec.title)

        final_markdown = self._merge_sections(section_texts)
        self._write_text(pipeline_result.run_dir / f"final_plan_global_retry_{attempt}.md", final_markdown)
        self._write_text(pipeline_result.run_dir / "final_plan.md", final_markdown)

        return FinalPlanPipelineResult(
            final_markdown=final_markdown,
            run_dir=pipeline_result.run_dir,
            evidence_path=pipeline_result.evidence_path,
            section_texts=section_texts,
            section_paths=section_paths,
            review_paths=review_paths,
            exhausted_sections=exhausted_sections,
        )

    def _generate_section_with_review(
        self,
        spec: SectionSpec,
        evidence: str,
        seed_plan: str,
        global_feedback: str,
        sections_dir: Path,
        reviews_dir: Path,
        tag: str = "",
    ) -> tuple[str, List[Path], bool]:
        review_paths: List[Path] = []
        current_text = ""
        last_review = SectionReview(passed=False, issues=["尚未生成章节"])

        for round_index in range(1, self.max_section_rounds + 1):
            prompt = self._build_section_prompt(
                spec=spec,
                evidence=evidence,
                seed_plan=seed_plan,
                global_feedback=global_feedback,
                previous_draft=current_text,
                last_review=last_review,
            )
            response = self.provider.chat(
                [
                    {"role": "system", "content": self.WRITER_SYSTEM_PROMPT.format(section_title=spec.title)},
                    {"role": "user", "content": prompt},
                ],
                tools=None,
                temperature=0.25,
                max_tokens=self.section_max_tokens,
            )
            current_text = self._normalize_section_text(spec, response.content or "")

            attempt_suffix = f"_{tag}" if tag else ""
            attempt_path = sections_dir / f"{spec.filename.removesuffix('.md')}{attempt_suffix}_attempt{round_index}.md"
            self._write_text(attempt_path, current_text)

            last_review = self._review_section(spec, evidence, current_text)
            review_path = reviews_dir / f"{spec.filename.removesuffix('.md')}{attempt_suffix}_review{round_index}.json"
            self._write_text(review_path, json.dumps(last_review.raw_payload or {
                "passed": last_review.passed,
                "score": last_review.score,
                "issues": last_review.issues,
                "revision_advice": last_review.revision_advice,
            }, ensure_ascii=False, indent=2))
            review_paths.append(review_path)

            if last_review.passed:
                return current_text, review_paths, False

        return current_text, review_paths, True

    def _build_section_prompt(
        self,
        spec: SectionSpec,
        evidence: str,
        seed_plan: str,
        global_feedback: str,
        previous_draft: str,
        last_review: SectionReview,
    ) -> str:
        parts = [
            f"请生成章节：{spec.title}",
            "",
            "【章节写作要求】",
            spec.instructions,
            "",
            "【必含关键词/信息】",
            "、".join(spec.required_terms),
            "",
            "【证据包】",
            evidence,
        ]

        if seed_plan:
            parts.extend(["", "【已有候选方案，仅可作为风格和线索参考，事实仍以证据包为准】", self._limit_text(seed_plan, 12000)])

        if global_feedback:
            parts.extend(["", "【本轮需要重点修复的审核意见】", self._limit_text(global_feedback, 5000)])

        if previous_draft:
            parts.extend(
                [
                    "",
                    "【上一版本章节】",
                    previous_draft,
                    "",
                    "【上一版审核问题】",
                    "\n".join(f"- {issue}" for issue in last_review.issues) or "- 未给出问题",
                    "【上一版修改建议】",
                    "\n".join(f"- {item}" for item in last_review.revision_advice) or "- 请补齐缺失内容",
                ]
            )

        parts.extend(
            [
                "",
                "请只输出当前章节 Markdown，标题必须是：",
                f"### {spec.title}",
            ]
        )
        return "\n".join(parts)

    def _review_section(self, spec: SectionSpec, evidence: str, section_text: str) -> SectionReview:
        deterministic_issues = self._collect_deterministic_section_issues(spec, section_text)

        prompt = "\n".join(
            [
                f"【待审核章节】{spec.title}",
                "",
                "【章节要求】",
                spec.instructions,
                "",
                "【必含关键词/信息】",
                "、".join(spec.required_terms),
                "",
                "【证据包摘要】",
                self._limit_text(evidence, 9000),
                "",
                "【章节内容】",
                section_text,
            ]
        )

        payload: Dict[str, Any] = {}
        try:
            response = self.provider.chat(
                [
                    {"role": "system", "content": self.REVIEW_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                tools=None,
                temperature=0.1,
                max_tokens=self.review_max_tokens,
            )
            payload = self._extract_json_payload(response.content or "")
        except Exception as error:
            logger.warning("章节审核调用失败: section=%s, error=%s", spec.title, error)

        review = self._normalize_review(payload)
        if deterministic_issues:
            review.passed = False
            review.issues = [*deterministic_issues, *review.issues]
            review.revision_advice.append("请先修复系统硬性校验问题，再补齐章节细节。")

        if review.score <= 0 and not review.passed:
            review.score = 50
        review.raw_payload = {
            "passed": review.passed,
            "score": review.score,
            "issues": review.issues,
            "revision_advice": review.revision_advice,
            "model_payload": payload,
        }
        return review

    def _collect_deterministic_section_issues(self, spec: SectionSpec, section_text: str) -> List[str]:
        issues: List[str] = []
        stripped = section_text.strip()
        if not stripped.startswith(f"### {spec.title}"):
            issues.append(f"章节标题不正确，必须以“### {spec.title}”开头。")

        visible_length = len(re.sub(r"\s+", "", stripped))
        if visible_length < spec.min_chars:
            issues.append(f"章节内容过于简略，当前约 {visible_length} 字，建议至少 {spec.min_chars} 字。")

        missing_terms = [term for term in spec.required_terms if term not in stripped]
        allowed_missing = 2 if spec.key in {"resource_dispatch", "risks", "command_structure", "action_plan"} else 3
        if len(missing_terms) > allowed_missing:
            issues.append("章节缺少关键内容：" + "、".join(missing_terms[:8]))

        if self._contains_nonexistent_execution_claim(stripped):
            issues.append("章节中出现了“已通知/已派遣/已下达”等虚构现实执行表述。")

        leaked_codes = [
            code for code in ("WARNING", "PPE", "SIGN", "VEHICLE", "RESCUE", "COMMS", "DEICE", "MATERIAL")
            if re.search(rf"(?<![A-Za-z]){code}(?![A-Za-z])", stripped)
        ]
        if leaked_codes:
            issues.append("资源类别包含内部英文编码：" + "、".join(leaked_codes))

        return issues

    def _build_evidence_bundle(self, task_state: TaskState, seed_plan: str = "") -> str:
        incident = task_state.incident_info
        environment = task_state.environment_info
        lines = [
            "# 应急指挥方案证据包",
            "",
            f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"- 当前阶段：{task_state.current_phase.value}",
            "",
            "## TaskState 摘要",
            task_state.build_context_summary(),
            "",
            "## 灾情信息",
            self._safe_json(
                {
                    "incident_type": incident.incident_type,
                    "severity": incident.severity,
                    "incident_category": incident.incident_category,
                    "disaster_type": incident.disaster_type,
                    "scene_type": incident.scene_type,
                    "response_level": incident.response_level,
                    "response_level_reason": incident.response_level_reason,
                    "response_level_confidence": incident.response_level_confidence,
                    "location_text": incident.location_text,
                    "location_coords": incident.location_coords,
                    "time_text": incident.time_text,
                    "casualty_status": incident.casualty_status,
                    "casualties": incident.casualties,
                    "scene_status": incident.scene_status,
                    "hazmat_involved": incident.hazmat_involved,
                    "hazmat_type": incident.hazmat_type,
                    "road_info": incident.road_info,
                    "vehicles_involved": incident.vehicles_involved,
                    "additional_context": incident.additional_context,
                }
            ),
            "",
            "## 环境与态势信息",
            self._safe_json(
                {
                    "formatted_address": environment.formatted_address,
                    "weather": environment.weather,
                    "traffic": environment.traffic,
                    "media_summary": environment.media_summary,
                    "nearby_pois": environment.nearby_pois[:12],
                    "route_notes": environment.additional_notes[:20],
                }
            ),
            "",
            "## 可用资源、专家与调度路线",
            self._format_resources(task_state.available_resources),
            "",
            "## 预案、法规、案例和知识依据",
            self._format_knowledge_refs(task_state.knowledge_refs),
            "",
            "## 风险评估结果",
            self._safe_json([self._compact_mapping(item.raw_result or {
                "overall_score": item.overall_score,
                "risk_level": item.risk_level,
                "summary": item.summary,
                "suggestions": item.suggestions,
            }, 3000) for item in task_state.evaluation_results]),
            "",
            "## 工具调用记录",
            self._format_tool_log(task_state.tool_call_log),
        ]

        if seed_plan:
            lines.extend(["", "## 主模型候选方案", self._limit_text(seed_plan, 12000)])

        return "\n".join(lines)

    def _format_resources(self, resources: List[Dict[str, Any]]) -> str:
        if not resources:
            return "暂未记录可用资源。"

        lines: List[str] = []
        for index, resource in enumerate(resources[:30], start=1):
            lines.append(f"### 资源 {index}: {resource.get('name') or resource.get('warehouse_name') or '未命名资源'}")
            lines.append(self._safe_json(self._compact_mapping(resource, 5000)))
        if len(resources) > 30:
            lines.append(f"... 另有 {len(resources) - 30} 条资源未展开。")
        return "\n\n".join(lines)

    def _format_knowledge_refs(self, refs: List[Any]) -> str:
        if not refs:
            return "暂未记录预案、法规或案例依据。"

        lines: List[str] = []
        for index, ref in enumerate(refs[:24], start=1):
            excerpt = self._limit_text(getattr(ref, "excerpt", "") or "", 1200)
            lines.append(
                "\n".join(
                    [
                        f"### 依据 {index}: {getattr(ref, 'title', '') or '未命名依据'}",
                        f"- 类型：{getattr(ref, 'source_type', '') or '未知'}",
                        f"- 来源：{getattr(ref, 'source_path', '') or '未注明'}",
                        f"- 分数：{getattr(ref, 'score', None)}",
                        f"- 元数据：{self._safe_json(getattr(ref, 'metadata', {}) or {})}",
                        f"- 摘要：{excerpt}",
                    ]
                )
            )
        if len(refs) > 24:
            lines.append(f"... 另有 {len(refs) - 24} 条依据未展开。")
        return "\n\n".join(lines)

    def _format_tool_log(self, records: List[Any]) -> str:
        if not records:
            return "暂未记录工具调用。"

        lines = [
            "| 序号 | 工具 | 是否成功 | 参数摘要 | 结果预览 | 错误 |",
            "|---|---|---|---|---|---|",
        ]
        for index, record in enumerate(records[-30:], start=1):
            args = self._limit_text(self._safe_json(getattr(record, "arguments", {}) or {}), 500).replace("\n", " ")
            preview = self._limit_text(getattr(record, "result_preview", "") or "", 500).replace("\n", " ")
            lines.append(
                "| {index} | {tool} | {success} | {args} | {preview} | {error} |".format(
                    index=index,
                    tool=getattr(record, "tool_name", "") or "",
                    success="是" if getattr(record, "success", False) else "否",
                    args=args.replace("|", "/"),
                    preview=preview.replace("|", "/"),
                    error=(getattr(record, "error_message", "") or "").replace("|", "/"),
                )
            )
        return "\n".join(lines)

    def _merge_sections(self, section_texts: Dict[str, str]) -> str:
        lines = [
            "# 标准化应急指挥方案",
            "",
            f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "> 说明：本方案为应急指挥建议稿，系统不会自动通知、派遣或下达现实指令，所有调度动作需由人工指挥席确认执行。",
            "",
        ]
        for spec in SECTION_SPECS:
            text = section_texts.get(spec.title, "").strip()
            if not text:
                text = f"### {spec.title}\n\n[待补充]"
            lines.append(text)
            lines.append("")
        return "\n".join(lines).strip()

    def _normalize_section_text(self, spec: SectionSpec, raw_text: str) -> str:
        text = self._strip_control_blocks(raw_text or "").strip()
        text = self._extract_requested_section(spec, text)
        if not text.startswith(f"### {spec.title}"):
            text = re.sub(rf"^#+\s*{re.escape(spec.title)}", f"### {spec.title}", text).strip()
        if not text.startswith(f"### {spec.title}"):
            text = f"### {spec.title}\n\n{text}".strip()
        return text

    def _extract_requested_section(self, spec: SectionSpec, text: str) -> str:
        start = text.find(spec.title)
        if start < 0:
            return text

        heading_start = text.rfind("\n", 0, start)
        section_start = 0 if heading_start < 0 else heading_start + 1
        end = len(text)
        for title in STANDARD_SECTION_TITLES:
            if title == spec.title:
                continue
            pos = text.find(title, start + len(spec.title))
            if pos > start and pos < end:
                heading_pos = text.rfind("\n", 0, pos)
                end = heading_pos if heading_pos >= 0 else pos
        return text[section_start:end].strip()

    @staticmethod
    def _strip_control_blocks(text: str) -> str:
        cleaned = re.sub(r"```agent_control\s*\{.*?\}\s*```", "", text, flags=re.DOTALL)
        cleaned = re.sub(r"```json\s*\{\s*\"agent_control\"\s*:\s*\{.*?\}\s*\}\s*```", "", cleaned, flags=re.DOTALL)
        cleaned = re.sub(r"(?:^|\n)\s*(?:json\s*)?\{\s*\"agent_control\"\s*:\s*\{.*\}\s*\}\s*$", "", cleaned, flags=re.DOTALL)
        return cleaned.strip()

    def _normalize_review(self, payload: Dict[str, Any]) -> SectionReview:
        if not payload:
            return SectionReview(
                passed=False,
                score=0,
                issues=["章节审核器未返回可解析 JSON"],
                revision_advice=["请重新生成本章节，并严格满足章节要求。"],
                raw_payload={},
            )

        issues = payload.get("issues", []) or []
        advice = payload.get("revision_advice", []) or []
        if isinstance(issues, str):
            issues = [issues]
        if isinstance(advice, str):
            advice = [advice]

        return SectionReview(
            passed=bool(payload.get("passed", False)),
            score=int(payload.get("score", 0) or 0),
            issues=[str(item) for item in issues if str(item).strip()],
            revision_advice=[str(item) for item in advice if str(item).strip()],
            raw_payload=payload,
        )

    def _extract_json_payload(self, content: str) -> Dict[str, Any]:
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

    def _select_failed_sections(self, review_result: Any, guardrail_issues: List[str]) -> set[str]:
        failed: set[str] = set()

        for item in getattr(review_result, "section_reviews", []) or []:
            if not isinstance(item, dict) or item.get("passed"):
                continue
            section_name = str(item.get("section", "") or "")
            matched = self._match_section_title(section_name)
            if matched:
                failed.add(matched)

        feedback_text = self._format_global_feedback(review_result, guardrail_issues)
        for title in self._map_feedback_to_sections(feedback_text):
            failed.add(title)
        return failed

    def _map_feedback_to_sections(self, feedback_text: str) -> set[str]:
        mapping = {
            "一、事件概述": ("事件概述", "时间", "位置", "坐标", "天气", "路况", "伤亡"),
            "二、响应定级": ("响应定级", "定级", "响应级别", "启动主体"),
            "三、指挥架构": ("指挥架构", "应急管理", "消防", "专家", "工作组", "总指挥"),
            "四、预警发布": ("预警", "发布主体", "发布流程", "发布渠道"),
            "五、处置行动方案": ("处置行动", "二次排查", "家属", "检伤", "现场警戒", "行动"),
            "六、资源调度方案": ("资源调度", "资源", "物资", "路线", "调度路径", "高德", "联系人", "电话", "梯队", "英文编码"),
            "七、信息报送与新闻发布": ("信息报送", "新闻发布", "舆情", "初报", "续报", "终报"),
            "八、风险提示与注意事项": ("风险", "注意事项", "安全风险", "处置风险", "衍生风险"),
            "九、依据引用": ("依据", "引用", "预案", "法规", "案例", "工具结果"),
        }
        matched: set[str] = set()
        for title, keywords in mapping.items():
            if any(keyword in feedback_text for keyword in keywords):
                matched.add(title)
        return matched

    def _filter_feedback_for_section(self, section_title: str, feedback_text: str) -> str:
        lines = []
        for line in feedback_text.splitlines():
            if section_title in line or any(keyword in line for keyword in self._section_keywords(section_title)):
                lines.append(line)
        return "\n".join(lines) or feedback_text

    def _section_keywords(self, section_title: str) -> tuple[str, ...]:
        for spec in SECTION_SPECS:
            if spec.title == section_title:
                return spec.required_terms
        return ()

    @staticmethod
    def _match_section_title(text: str) -> str:
        for title in STANDARD_SECTION_TITLES:
            if title in text:
                return title
        return ""

    @staticmethod
    def _format_global_feedback(review_result: Any, guardrail_issues: List[str]) -> str:
        lines: List[str] = []
        if guardrail_issues:
            lines.append("【硬性校验问题】")
            lines.extend(f"- {issue}" for issue in guardrail_issues)

        issues = getattr(review_result, "issues", []) or []
        advice = getattr(review_result, "revision_advice", []) or []
        if issues:
            lines.append("【全局审核问题】")
            lines.extend(f"- {issue}" for issue in issues)
        if advice:
            lines.append("【全局修改建议】")
            lines.extend(f"- {item}" for item in advice)
        return "\n".join(lines)

    @staticmethod
    def _contains_nonexistent_execution_claim(text: str) -> bool:
        markers = (
            "已执行的行动", "已通知", "已下达指令", "已启动应急响应", "已派遣", "已调派",
            "已联系", "已协调", "已通过系统向联系人",
        )
        if any(marker in text for marker in markers):
            return True
        patterns = (
            r"通知.{0,20}出发",
            r"要求.{0,20}立即前往",
            r"我将立即启动应急响应",
            r"我将优先派遣",
        )
        return any(re.search(pattern, text) for pattern in patterns)

    def _create_run_dir(self) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = self.output_root / f"plan_{timestamp}_{os.getpid()}"
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    @staticmethod
    def _write_text(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    @staticmethod
    def _read_text(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    @staticmethod
    def _safe_json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)

    def _compact_mapping(self, value: Any, max_chars: int) -> Any:
        if isinstance(value, dict):
            compacted = {key: self._compact_mapping(item, max_chars=max_chars) for key, item in value.items()}
            text = self._safe_json(compacted)
            if len(text) <= max_chars:
                return compacted
            return self._limit_text(text, max_chars)
        if isinstance(value, list):
            return [self._compact_mapping(item, max_chars=max_chars) for item in value[:30]]
        if isinstance(value, str):
            return self._limit_text(value, max_chars)
        return value

    @staticmethod
    def _limit_text(text: str, max_chars: int) -> str:
        if not text:
            return ""
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 20] + "\n...（内容截断）"

    @staticmethod
    def _int_env(name: str, default: int) -> int:
        value = os.getenv(name)
        if not value:
            return default
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default
