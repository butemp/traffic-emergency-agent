"""独立的事件定级子模块。"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .service import EmergencyPlanService

if TYPE_CHECKING:
    from ..providers import OpenAIProvider

logger = logging.getLogger(__name__)


class SeverityEvaluator:
    """用独立大模型对话完成预案定级，减轻主对话上下文压力。"""

    SYSTEM_PROMPT = """你是交通运输应急事件定级助手，只负责做以下事情：
1. 判断事件的场景类别 incident_category
2. 判断灾害类别 disaster_type（可为空）
3. 对照预案分级标准，给出响应级别 response_level
4. 说明依据 reasoning
5. 指出仍缺哪些信息 missing_fields
6. 从可用场景中选择一个最匹配的 scene_type（可为空）

规则：
- 只能做定级，不要生成处置方案
- 优先依据给定的预案分级标准，不要脱离标准自由发挥
- 信息不足时可以输出“待确认”，但若已明显高风险，应宁可判高不判低
- missing_fields 只列真正影响定级判断的字段

输出要求：
- 只输出 JSON
- response_level 只能是：特别重大级、重大级、较大级、一般级、待确认
- confidence 为 0 到 1 之间的小数
"""

    def __init__(
        self,
        provider: "OpenAIProvider",
        plan_service: Optional[EmergencyPlanService] = None,
    ):
        self.provider = provider
        self.plan_service = plan_service or EmergencyPlanService()

    def evaluate(
        self,
        incident_summary: str,
        incident_category: str = "",
        disaster_type: str = "",
        incident_type: str = "",
        location_text: str = "",
        casualty_status: str = "",
        scene_status: str = "",
        additional_context: str = "",
    ) -> Dict[str, Any]:
        """基于预案分级标准做响应级别判定。"""
        resolved_category = (
            self.plan_service.normalize_incident_category(incident_category)
            or self.plan_service.infer_incident_category(
                text=incident_summary,
                location_text=location_text,
                incident_type=incident_type,
            )
        )
        resolved_disaster = (
            self.plan_service.normalize_disaster_type(disaster_type)
            or self.plan_service.infer_disaster_type(
                text=incident_summary,
                incident_type=incident_type,
                scene_status=scene_status,
            )
        )

        grading_bundle = self.plan_service.get_grading_bundle(
            incident_category=resolved_category,
            disaster_type=resolved_disaster,
        )
        main_module = grading_bundle.get("main_module")
        main_plan = grading_bundle.get("main_plan") or {}

        available_scene_types = self._collect_scene_types(main_plan)
        inferred_scene_type = self.plan_service.infer_scene_type(
            incident_category=resolved_category,
            incident_type=incident_type,
            disaster_type=resolved_disaster,
            scene_status=scene_status,
            raw_text=incident_summary,
            available_scene_names=available_scene_types,
        )

        if not main_module:
            return {
                "status": "error",
                "message": "未找到可用于定级的主预案分级标准",
                "incident_category": resolved_category,
                "disaster_type": resolved_disaster,
                "response_level": "待确认",
                "confidence": 0.0,
                "reasoning": "缺少可用的 grading_criteria 模块",
                "missing_fields": self._infer_missing_fields(
                    incident_type=incident_type,
                    location_text=location_text,
                    casualty_status=casualty_status,
                    scene_status=scene_status,
                ),
                "scene_type": inferred_scene_type,
            }

        try:
            response = self.provider.chat(
                [
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": self._build_user_prompt(
                        grading_bundle=grading_bundle,
                        incident_summary=incident_summary,
                        incident_type=incident_type,
                        location_text=location_text,
                        casualty_status=casualty_status,
                        scene_status=scene_status,
                        additional_context=additional_context,
                        available_scene_types=available_scene_types,
                    )},
                ],
                temperature=0.1,
                max_tokens=900,
            )
            payload = self._extract_json_payload(response.content or "")
        except Exception as error:
            logger.warning("SeverityEvaluator 调用失败，回退到启发式结果: %s", error)
            payload = {}

        return self._normalize_result(
            payload=payload,
            incident_summary=incident_summary,
            incident_category=resolved_category,
            disaster_type=resolved_disaster,
            incident_type=incident_type,
            location_text=location_text,
            casualty_status=casualty_status,
            scene_status=scene_status,
            inferred_scene_type=inferred_scene_type,
            grading_bundle=grading_bundle,
        )

    def _build_user_prompt(
        self,
        grading_bundle: Dict[str, Any],
        incident_summary: str,
        incident_type: str,
        location_text: str,
        casualty_status: str,
        scene_status: str,
        additional_context: str,
        available_scene_types: List[str],
    ) -> str:
        main_plan = grading_bundle.get("main_plan") or {}
        main_module = grading_bundle.get("main_module") or {}
        supplementary_plan = grading_bundle.get("supplementary_plan") or {}
        supplementary_module = grading_bundle.get("supplementary_module") or {}

        lines = [
            "请根据下列事件信息进行定级。",
            "",
            "【事件信息】",
            f"- incident_summary: {incident_summary or '无'}",
            f"- incident_type: {incident_type or '无'}",
            f"- location_text: {location_text or '无'}",
            f"- casualty_status: {casualty_status or '无'}",
            f"- scene_status: {scene_status or '无'}",
            f"- additional_context: {additional_context or '无'}",
            "",
            f"【主预案】{main_plan.get('plan_name', '未命名预案')}",
            self.plan_service.format_module_content("grading_criteria", main_module),
        ]

        if supplementary_module:
            lines.extend(
                [
                    "",
                    f"【补充预案】{supplementary_plan.get('plan_name', '未命名预案')}",
                    self.plan_service.format_module_content("grading_criteria", supplementary_module),
                ]
            )

        if available_scene_types:
            lines.extend(
                [
                    "",
                    "【可选 scene_type】",
                    "、".join(available_scene_types),
                ]
            )

        lines.extend(
            [
                "",
                "请输出如下 JSON：",
                json.dumps(
                    {
                        "incident_category": "EXPRESSWAY",
                        "disaster_type": "FLOOD",
                        "response_level": "较大级",
                        "confidence": 0.78,
                        "reasoning": "依据……",
                        "missing_fields": ["伤亡人数"],
                        "scene_type": "洪水与地质灾害事件",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            ]
        )
        return "\n".join(lines)

    def _collect_scene_types(self, main_plan: Dict[str, Any]) -> List[str]:
        scene_module = (main_plan.get("modules") or {}).get("scene_disposal") or {}
        scene_map = scene_module.get("scenes") or scene_module.get("dispatch_rules") or {}
        if isinstance(scene_map, dict):
            return list(scene_map.keys())
        return []

    def _extract_json_payload(self, content: str) -> Dict[str, Any]:
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

    def _normalize_result(
        self,
        payload: Dict[str, Any],
        incident_summary: str,
        incident_category: str,
        disaster_type: str,
        incident_type: str,
        location_text: str,
        casualty_status: str,
        scene_status: str,
        inferred_scene_type: str,
        grading_bundle: Dict[str, Any],
    ) -> Dict[str, Any]:
        response_level = self.plan_service.normalize_response_level(
            str(payload.get("response_level") or payload.get("level") or "")
        )
        if not response_level:
            response_level = self._heuristic_response_level(
                incident_summary=incident_summary,
                incident_type=incident_type,
                casualty_status=casualty_status,
                scene_status=scene_status,
            )

        confidence = payload.get("confidence", 0.0)
        try:
            confidence = float(confidence)
        except Exception:
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        missing_fields = payload.get("missing_fields")
        if not isinstance(missing_fields, list):
            missing_fields = self._infer_missing_fields(
                incident_type=incident_type,
                location_text=location_text,
                casualty_status=casualty_status,
                scene_status=scene_status,
            )

        resolved_category = (
            self.plan_service.normalize_incident_category(str(payload.get("incident_category", "")))
            or incident_category
        )
        resolved_disaster = (
            self.plan_service.normalize_disaster_type(str(payload.get("disaster_type", "")))
            or disaster_type
        )
        scene_type = (
            self.plan_service.match_scene_name(
                self._collect_scene_types(grading_bundle.get("main_plan") or {}),
                str(payload.get("scene_type", "")),
            )
            or inferred_scene_type
        )

        reasoning = str(payload.get("reasoning", "") or "").strip()
        if not reasoning:
            reasoning = "基于灾情描述与预案分级标准完成初步判定。"

        main_plan = grading_bundle.get("main_plan") or {}
        return {
            "status": "success",
            "incident_category": resolved_category,
            "disaster_type": resolved_disaster,
            "response_level": response_level,
            "confidence": confidence,
            "reasoning": reasoning,
            "missing_fields": missing_fields,
            "scene_type": scene_type,
            "plan_reference": {
                "plan_name": main_plan.get("plan_name", ""),
                "source_section": ((grading_bundle.get("main_module") or {}).get("source_section", "")),
            },
        }

    def _infer_missing_fields(
        self,
        incident_type: str,
        location_text: str,
        casualty_status: str,
        scene_status: str,
    ) -> List[str]:
        missing_fields: List[str] = []
        if not incident_type:
            missing_fields.append("事故类型")
        if not location_text:
            missing_fields.append("事故位置")
        if not casualty_status:
            missing_fields.append("伤亡情况")
        if not scene_status:
            missing_fields.append("现场状态")
        return missing_fields

    def _heuristic_response_level(
        self,
        incident_summary: str,
        incident_type: str,
        casualty_status: str,
        scene_status: str,
    ) -> str:
        merged_text = f"{incident_summary}\n{incident_type}\n{casualty_status}\n{scene_status}"
        if any(keyword in merged_text for keyword in ("30人以上死亡", "30人以上失踪", "48小时以上", "特大环境事件")):
            return "特别重大级"
        if any(keyword in merged_text for keyword in ("10人以上死亡", "30人以下死亡", "24小时以上", "重大环境事件", "爆炸")):
            return "重大级"
        if any(keyword in merged_text for keyword in ("3人以上死亡", "10人以上受伤", "双向阻断", "道路中断", "多人被困", "危化品", "滑坡")):
            return "较大级"
        if incident_type:
            return "一般级"
        return "待确认"
