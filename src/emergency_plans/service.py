"""应急预案精确取用服务。"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


INCIDENT_CATEGORY_ALIASES: Dict[str, List[str]] = {
    "EXPRESSWAY": ["高速公路", "高速公路支线", "连接线"],
    "HIGHWAY": ["普通公路", "普通国道", "国道", "省道", "县道", "乡道", "公路桥梁", "公路隧道"],
    "ROAD_TRANSPORT": ["道路运输", "客运站", "货运站", "道路客运", "道路货运"],
    "PORT": ["主要港口", "地区性重要港口", "一般港口", "危险货物码头", "仓储场所", "港口客运枢纽", "港口", "码头"],
    "WATERWAY": ["航道", "重要航道", "界河航道"],
    "WATERWAY_XIJIANG": ["西江水道", "西江黄金水道", "西江航运干线"],
    "WATER_TRANSPORT": ["水路运输", "水运保障", "水路客运", "水路货运"],
    "CITY_BUS": ["城市公交", "城市公共汽电车", "公交"],
    "URBAN_RAIL": ["城市轨道交通", "地铁", "轨道交通"],
    "CONSTRUCTION": ["公路水运工程", "工程施工", "施工工地"],
}

DISASTER_TYPE_ALIASES: Dict[str, List[str]] = {
    "FLOOD": ["洪水台风", "洪水", "台风", "暴雨", "积水", "洪涝", "内涝", "洪水地质灾害"],
    "ICE_SNOW": ["低温雨雪冰冻", "冰雪", "结冰", "冻雨", "大雪", "寒潮"],
    "EARTHQUAKE": ["地震", "地震地质灾害"],
    "PUBLIC_HEALTH": ["公共卫生", "公共卫生事件", "疫情", "传染病"],
    "CYBER": ["网络安全", "网络攻击", "系统瘫痪"],
}

RESPONSE_LEVEL_NAMES = {
    "I": "特别重大级",
    "II": "重大级",
    "III": "较大级",
    "IV": "一般级",
}

SCENE_TYPE_KEYWORDS: List[Tuple[Tuple[str, ...], str]] = [
    (("危化品", "泄漏", "爆炸", "追尾", "相撞", "车祸"), "交通运输事故和危险化学品泄漏事故"),
    (("洪水", "暴雨", "台风", "滑坡", "塌方", "泥石流", "山体"), "洪水与地质灾害事件"),
    (("冰雪", "结冰", "冻雨", "大雾", "浓雾", "低温"), "气象灾害事件"),
    (("拥堵", "积压", "排队"), "交通拥堵事件"),
]


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "").strip().lower()


class EmergencyPlanService:
    """负责加载预案、映射类别并精确提取模块。"""

    def __init__(
        self,
        data_dir: str = "data/regulations/data",
        registry_path: Optional[str] = None,
    ):
        self.data_dir = Path(data_dir)
        self.registry_path = Path(registry_path) if registry_path else self.data_dir / "plan_registry.json"
        self.registry = self._load_registry()
        self.plans = self._load_plans()

        logger.info(
            "EmergencyPlanService 初始化完成: data_dir=%s, registry=%s, plans=%s",
            self.data_dir,
            self.registry_path,
            len(self.plans),
        )

    @classmethod
    def normalize_incident_category(cls, value: str) -> str:
        """将中文或编码统一转换为场景类别编码。"""
        if not value:
            return ""

        raw = str(value).strip()
        upper = raw.upper()
        if upper in INCIDENT_CATEGORY_ALIASES:
            return upper

        normalized = _normalize_text(raw)
        for code, aliases in INCIDENT_CATEGORY_ALIASES.items():
            if normalized == _normalize_text(code):
                return code
            if any(normalized == _normalize_text(alias) for alias in aliases):
                return code
        return ""

    @classmethod
    def normalize_disaster_type(cls, value: str) -> str:
        """将中文或编码统一转换为灾害类别编码。"""
        if not value:
            return ""

        raw = str(value).strip()
        upper = raw.upper()
        if upper in DISASTER_TYPE_ALIASES:
            return upper

        normalized = _normalize_text(raw)
        for code, aliases in DISASTER_TYPE_ALIASES.items():
            if normalized == _normalize_text(code):
                return code
            if any(normalized == _normalize_text(alias) for alias in aliases):
                return code
        return ""

    @classmethod
    def normalize_response_level(cls, value: str) -> str:
        """统一响应级别名称。"""
        if not value:
            return ""

        normalized = _normalize_text(value)
        if normalized in {"i", "i级", "特别重大", "特别重大级", "i级特别重大"}:
            return "特别重大级"
        if normalized in {"ii", "ii级", "重大", "重大级", "ii级重大"}:
            return "重大级"
        if normalized in {"iii", "iii级", "较大", "较大级", "iii级较大"}:
            return "较大级"
        if normalized in {"iv", "iv级", "一般", "一般级", "iv级一般"}:
            return "一般级"

        if "特别重大" in normalized:
            return "特别重大级"
        if normalized.startswith("重大") or normalized.endswith("重大级"):
            return "重大级"
        if "较大" in normalized:
            return "较大级"
        if "一般" in normalized:
            return "一般级"
        return ""

    @classmethod
    def infer_incident_category(
        cls,
        text: str,
        location_text: str = "",
        incident_type: str = "",
    ) -> str:
        """根据上下文做轻量场景类别推断。"""
        merged_text = f"{text or ''}\n{location_text or ''}\n{incident_type or ''}"

        if any(keyword in merged_text for keyword in ("高速", "收费站", "服务区")):
            return "EXPRESSWAY"
        if re.search(r"\bG\d+\b", merged_text):
            return "EXPRESSWAY"
        if any(keyword in merged_text for keyword in ("国道", "省道", "县道", "乡道", "公路", "隧道", "桥梁")):
            return "HIGHWAY"
        if any(keyword in merged_text for keyword in ("港口", "码头", "泊位", "客运枢纽")):
            return "PORT"
        if any(keyword in merged_text for keyword in ("航道", "断航", "船闸")):
            return "WATERWAY"
        if any(keyword in merged_text for keyword in ("公交", "公交车站", "公交场站")):
            return "CITY_BUS"
        if any(keyword in merged_text for keyword in ("地铁", "轨道交通", "轻轨")):
            return "URBAN_RAIL"
        if any(keyword in merged_text for keyword in ("施工", "工地", "作业面")):
            return "CONSTRUCTION"
        return ""

    @classmethod
    def infer_disaster_type(
        cls,
        text: str,
        incident_type: str = "",
        scene_status: str = "",
    ) -> str:
        """根据上下文做轻量灾害类别推断。"""
        merged_text = f"{text or ''}\n{incident_type or ''}\n{scene_status or ''}"

        if any(keyword in merged_text for keyword in ("暴雨", "洪水", "台风", "积水", "内涝", "滑坡", "塌方", "泥石流")):
            return "FLOOD"
        if any(keyword in merged_text for keyword in ("结冰", "冻雨", "冰雪", "低温", "大雪", "寒潮")):
            return "ICE_SNOW"
        if "地震" in merged_text:
            return "EARTHQUAKE"
        if any(keyword in merged_text for keyword in ("疫情", "传染病", "公共卫生")):
            return "PUBLIC_HEALTH"
        if any(keyword in merged_text for keyword in ("网络", "系统", "黑客", "攻击")):
            return "CYBER"
        return ""

    @classmethod
    def infer_scene_type(
        cls,
        incident_category: str,
        incident_type: str = "",
        disaster_type: str = "",
        scene_status: str = "",
        raw_text: str = "",
        available_scene_names: Optional[Iterable[str]] = None,
    ) -> str:
        """根据事故信息匹配更细的分场景处置类型。"""
        merged_text = f"{incident_category}\n{incident_type}\n{disaster_type}\n{scene_status}\n{raw_text}"

        candidate = ""
        for keywords, scene_name in SCENE_TYPE_KEYWORDS:
            if any(keyword in merged_text for keyword in keywords):
                candidate = scene_name
                break

        if not available_scene_names:
            return candidate

        names = list(available_scene_names)
        if not names:
            return candidate
        if not candidate:
            return names[0]

        matched = cls.match_scene_name(names, candidate)
        return matched or names[0]

    @classmethod
    def match_scene_name(cls, scene_names: Iterable[str], scene_type: str) -> str:
        """在现有场景名中做宽松匹配。"""
        target = _normalize_text(scene_type)
        if not target:
            return ""

        for name in scene_names:
            normalized_name = _normalize_text(name)
            if target == normalized_name:
                return name
            if target in normalized_name or normalized_name in target:
                return name

        alias_map = {
            "交通事故和危化品泄漏": "交通运输事故和危险化学品泄漏事故",
            "交通事故和危险化学品泄漏": "交通运输事故和危险化学品泄漏事故",
            "洪水与地质灾害": "洪水与地质灾害事件",
            "气象灾害": "气象灾害事件",
            "交通拥堵": "交通拥堵事件",
        }
        alias = alias_map.get(scene_type, "")
        if alias:
            return cls.match_scene_name(scene_names, alias)
        return ""

    def get_emergency_plan(
        self,
        incident_category: str,
        module: str,
        disaster_type: str = "",
        level: str = "",
        scene_type: str = "",
    ) -> Dict[str, Any]:
        """按条件精确获取预案模块内容。"""
        normalized_category = self.normalize_incident_category(incident_category)
        normalized_disaster = self.normalize_disaster_type(disaster_type)
        normalized_level = self.normalize_response_level(level)

        primary_plan = self._resolve_scene_plan(normalized_category)
        fallback_plan = self._resolve_fallback_plan()
        module_plan = primary_plan
        module_data = (primary_plan or {}).get("modules", {}).get(module)
        fallback_used = False

        if not module_data and fallback_plan and fallback_plan is not primary_plan:
            fallback_module = fallback_plan.get("modules", {}).get(module)
            if fallback_module:
                module_plan = fallback_plan
                module_data = fallback_module
                fallback_used = True

        if module_plan is None or module_data is None:
            return {
                "status": "not_found",
                "message": f"未找到 incident_category={normalized_category or incident_category} 对应的 {module} 模块",
                "incident_category": normalized_category,
                "disaster_type": normalized_disaster,
                "module": module,
            }

        available_scene_types = self._list_scene_types(module_data)
        resolved_scene_type = ""
        if module == "scene_disposal" and scene_type:
            resolved_scene_type = self.infer_scene_type(
                incident_category=normalized_category,
                disaster_type=normalized_disaster,
                scene_status="",
                incident_type="",
                raw_text=scene_type,
                available_scene_names=available_scene_types,
            )
        if scene_type:
            matched_scene = self.match_scene_name(available_scene_types, scene_type)
            if matched_scene:
                resolved_scene_type = matched_scene

        content = self.format_module_content(
            module=module,
            module_data=module_data,
            level=normalized_level,
            scene_type=resolved_scene_type or scene_type,
        )

        result: Dict[str, Any] = {
            "status": "success",
            "incident_category": normalized_category,
            "disaster_type": normalized_disaster,
            "module": module,
            "level": normalized_level,
            "scene_type": resolved_scene_type or scene_type,
            "plan_name": module_plan.get("plan_name", ""),
            "plan_role": module_plan.get("plan_role", ""),
            "content": content,
            "source_reference": self._build_source_reference(module_plan, module_data),
            "available_scene_types": available_scene_types,
            "fallback_used": fallback_used,
            "supplementary_plan": None,
        }

        supplementary_plan = self._resolve_disaster_plan(normalized_disaster)
        if supplementary_plan and supplementary_plan is not module_plan:
            supplementary_module = supplementary_plan.get("modules", {}).get(module)
            if supplementary_module:
                result["supplementary_plan"] = {
                    "plan_name": supplementary_plan.get("plan_name", ""),
                    "plan_role": supplementary_plan.get("plan_role", ""),
                    "content": self.format_module_content(
                        module=module,
                        module_data=supplementary_module,
                        level=normalized_level,
                        scene_type=resolved_scene_type or scene_type,
                    ),
                    "source_reference": self._build_source_reference(supplementary_plan, supplementary_module),
                }

        return result

    def get_grading_bundle(
        self,
        incident_category: str,
        disaster_type: str = "",
    ) -> Dict[str, Any]:
        """返回定级时需要的主预案和补充预案模块。"""
        normalized_category = self.normalize_incident_category(incident_category)
        normalized_disaster = self.normalize_disaster_type(disaster_type)

        primary_plan = self._resolve_scene_plan(normalized_category) or self._resolve_fallback_plan()
        supplementary_plan = self._resolve_disaster_plan(normalized_disaster)

        main_module = (primary_plan or {}).get("modules", {}).get("grading_criteria")
        supplementary_module = (supplementary_plan or {}).get("modules", {}).get("grading_criteria")

        return {
            "incident_category": normalized_category,
            "disaster_type": normalized_disaster,
            "main_plan": primary_plan,
            "main_module": main_module,
            "supplementary_plan": supplementary_plan,
            "supplementary_module": supplementary_module,
        }

    def format_module_content(
        self,
        module: str,
        module_data: Dict[str, Any],
        level: str = "",
        scene_type: str = "",
    ) -> str:
        """将模块内容格式化为适合模型阅读的文本。"""
        if module == "grading_criteria":
            return self._format_grading_criteria(module_data)
        if module == "command_structure":
            return self._format_command_structure(module_data, level)
        if module == "response_measures":
            return self._format_response_measures(module_data, level)
        if module == "scene_disposal":
            return self._format_scene_disposal(module_data, scene_type)
        if module == "warning_rules":
            return self._format_warning_rules(module_data)
        return json.dumps(module_data, ensure_ascii=False, indent=2)

    def _load_registry(self) -> Dict[str, Any]:
        if self.registry_path.exists():
            with open(self.registry_path, "r", encoding="utf-8") as file:
                return json.load(file)
        return self._default_registry()

    def _default_registry(self) -> Dict[str, Any]:
        return {
            "scene_plans": {
                "EXPRESSWAY": {
                    "plan_file": "plan_2.json",
                    "plan_name": "广西高速公路突发事件应急预案",
                    "description": "高速公路及其支线、连接线上的突发事件专项预案",
                },
                "HIGHWAY": {
                    "plan_file": "plan_4.json",
                    "plan_name": "广西壮族自治区公路交通突发事件应急预案",
                    "description": "普通公路及其桥梁、隧道等设施上的突发事件专项预案",
                },
                "ROAD_TRANSPORT": {
                    "plan_file": "plan_1.json",
                    "plan_name": "广西壮族自治区交通运输综合应急预案",
                    "description": "当前仓库中暂无道路运输专项预案，先回退到综合预案",
                },
                "PORT": {
                    "plan_file": "plan_5.json",
                    "plan_name": "广西壮族自治区港口突发事件应急预案",
                    "description": "港口、码头、仓储场所等港口突发事件专项预案",
                },
                "WATERWAY": {
                    "plan_file": "plan_1.json",
                    "plan_name": "广西壮族自治区交通运输综合应急预案",
                    "description": "当前仓库中暂无航道专项预案，先回退到综合预案",
                },
                "WATERWAY_XIJIANG": {
                    "plan_file": "plan_1.json",
                    "plan_name": "广西壮族自治区交通运输综合应急预案",
                    "description": "当前仓库中暂无西江水道专项预案，先回退到综合预案",
                },
                "WATER_TRANSPORT": {
                    "plan_file": "plan_1.json",
                    "plan_name": "广西壮族自治区交通运输综合应急预案",
                    "description": "当前仓库中暂无水路运输保障专项预案，先回退到综合预案",
                },
                "CITY_BUS": {
                    "plan_file": "plan_1.json",
                    "plan_name": "广西壮族自治区交通运输综合应急预案",
                    "description": "当前仓库中暂无城市公交专项预案，先回退到综合预案",
                },
                "URBAN_RAIL": {
                    "plan_file": "plan_1.json",
                    "plan_name": "广西壮族自治区交通运输综合应急预案",
                    "description": "当前仓库中暂无城市轨道交通专项预案，先回退到综合预案",
                },
                "CONSTRUCTION": {
                    "plan_file": "plan_1.json",
                    "plan_name": "广西壮族自治区交通运输综合应急预案",
                    "description": "当前仓库中暂无公路水运工程专项预案，先回退到综合预案",
                },
            },
            "disaster_plans": {},
            "fallback_plan": {
                "plan_file": "plan_1.json",
                "plan_name": "广西壮族自治区交通运输综合应急预案",
                "description": "当前专项预案覆盖不到时使用的总纲预案",
            },
        }

    def _load_plans(self) -> Dict[str, Dict[str, Any]]:
        plans: Dict[str, Dict[str, Any]] = {}
        if not self.data_dir.exists():
            logger.warning("预案数据目录不存在: %s", self.data_dir)
            return plans

        for plan_file in sorted(self.data_dir.glob("plan_*.json")):
            try:
                with open(plan_file, "r", encoding="utf-8") as file:
                    plans[plan_file.name] = json.load(file)
            except Exception as error:
                logger.error("加载预案失败: file=%s, error=%s", plan_file, error)
        return plans

    def _resolve_scene_plan(self, incident_category: str) -> Optional[Dict[str, Any]]:
        if not incident_category:
            return None

        registry_item = self.registry.get("scene_plans", {}).get(incident_category)
        if registry_item:
            plan = self.plans.get(registry_item.get("plan_file", ""))
            if plan:
                return plan

        return self._scan_plan_by_incident_category(incident_category)

    def _resolve_disaster_plan(self, disaster_type: str) -> Optional[Dict[str, Any]]:
        if not disaster_type:
            return None

        registry_item = self.registry.get("disaster_plans", {}).get(disaster_type)
        if registry_item:
            plan = self.plans.get(registry_item.get("plan_file", ""))
            if plan:
                return plan

        return self._scan_plan_by_disaster_type(disaster_type)

    def _resolve_fallback_plan(self) -> Optional[Dict[str, Any]]:
        fallback = self.registry.get("fallback_plan", {})
        plan_file = fallback.get("plan_file", "")
        return self.plans.get(plan_file)

    def _scan_plan_by_incident_category(self, incident_category: str) -> Optional[Dict[str, Any]]:
        aliases = INCIDENT_CATEGORY_ALIASES.get(incident_category, [])
        best_plan: Optional[Dict[str, Any]] = None
        best_role_priority = 99
        best_match_score = -1

        for plan in self.plans.values():
            categories = [str(item) for item in plan.get("incident_categories", [])]
            match_score = sum(1 for category in categories if category in aliases)
            if not match_score:
                continue

            role = str(plan.get("plan_role", ""))
            role_priority = 0 if "专项" in role else 1
            if (
                best_plan is None
                or role_priority < best_role_priority
                or (role_priority == best_role_priority and match_score > best_match_score)
            ):
                best_plan = plan
                best_role_priority = role_priority
                best_match_score = match_score

        return best_plan

    def _scan_plan_by_disaster_type(self, disaster_type: str) -> Optional[Dict[str, Any]]:
        aliases = DISASTER_TYPE_ALIASES.get(disaster_type, [])
        best_plan: Optional[Dict[str, Any]] = None
        best_role_priority = 99
        best_match_score = -1

        for plan in self.plans.values():
            disaster_types = [str(item) for item in plan.get("disaster_types", [])]
            match_score = sum(1 for item in disaster_types if item in aliases)
            if not match_score:
                continue

            role = str(plan.get("plan_role", ""))
            role_priority = 0 if "专项" in role else 1
            if (
                best_plan is None
                or role_priority < best_role_priority
                or (role_priority == best_role_priority and match_score > best_match_score)
            ):
                best_plan = plan
                best_role_priority = role_priority
                best_match_score = match_score

        return best_plan

    def _build_source_reference(self, plan: Dict[str, Any], module_data: Dict[str, Any]) -> str:
        plan_name = plan.get("plan_name", "应急预案")
        source_section = module_data.get("source_section", "")
        return f"《{plan_name}》{source_section}".strip()

    def _list_scene_types(self, module_data: Dict[str, Any]) -> List[str]:
        scene_map = module_data.get("scenes") or module_data.get("dispatch_rules") or {}
        if isinstance(scene_map, dict):
            return list(scene_map.keys())
        return []

    def _level_lookup_candidates(self, level: str) -> List[str]:
        normalized = self.normalize_response_level(level)
        if normalized == "特别重大级":
            return ["I", "I_II", "特别重大_重大", "特别重大_重大级"]
        if normalized == "重大级":
            return ["II", "I_II", "特别重大_重大", "特别重大_重大级"]
        if normalized == "较大级":
            return ["III", "III_IV", "较大_一般", "较大_一般级"]
        if normalized == "一般级":
            return ["IV", "III_IV", "较大_一般", "较大_一般级"]
        return []

    def _pick_level_data(self, by_level: Dict[str, Any], level: str) -> Dict[str, Any]:
        if not isinstance(by_level, dict) or not by_level:
            return {}
        if not level:
            first_key = next(iter(by_level.keys()))
            return by_level.get(first_key, {})

        for candidate in self._level_lookup_candidates(level):
            if candidate in by_level:
                return by_level[candidate]

        target_level = self.normalize_response_level(level)
        for key, item in by_level.items():
            label = _normalize_text(str(item.get("level_label", key)))
            if _normalize_text(target_level).replace("级", "") in label:
                return item

        return {}

    def _format_grading_criteria(self, module_data: Dict[str, Any]) -> str:
        levels = module_data.get("levels", {})
        if not isinstance(levels, dict) or not levels:
            return "该预案未提供明确的分级标准。"

        lines = [module_data.get("description", "事件分级标准")]
        for level_name, level_data in levels.items():
            normalized_level = self.normalize_response_level(level_name) or level_name
            response_authority = level_data.get("response_authority", "")
            lines.append(f"\n【{normalized_level}】")
            if response_authority:
                lines.append(f"响应主体：{response_authority}")
            for criterion in level_data.get("criteria", []) or []:
                lines.append(f"- {criterion}")
        return "\n".join(lines).strip()

    def _format_command_structure(self, module_data: Dict[str, Any], level: str) -> str:
        level_data = self._pick_level_data(module_data.get("by_level", {}), level)
        if not level_data:
            return "未找到该级别对应的指挥架构。"

        lines = [module_data.get("description", "组织指挥体系")]
        if level_data.get("level_label"):
            lines.append(f"适用级别：{level_data['level_label']}")
        if level_data.get("command"):
            lines.append(f"指挥主体：{level_data['command']}")
        if level_data.get("commander"):
            lines.append(f"指挥长：{level_data['commander']}")
        if level_data.get("note"):
            lines.append(f"说明：{level_data['note']}")

        work_groups = level_data.get("work_groups", []) or []
        if work_groups:
            lines.append("工作组职责：")
            for group in work_groups:
                name = group.get("name", "工作组")
                lead = group.get("lead", "未说明")
                duties = group.get("duties", "")
                lines.append(f"- {name}（牵头：{lead}）")
                if duties:
                    lines.append(f"  职责：{duties}")

        optional_groups = level_data.get("optional_groups", []) or []
        if optional_groups:
            lines.append("视情组建：")
            for group in optional_groups:
                name = group.get("name", "工作组")
                condition = group.get("condition", "")
                duties = group.get("duties", "")
                detail = f"- {name}"
                if condition:
                    detail += f"（{condition}）"
                lines.append(detail)
                if duties:
                    lines.append(f"  职责：{duties}")

        return "\n".join(lines).strip()

    def _format_response_measures(self, module_data: Dict[str, Any], level: str) -> str:
        level_data = self._pick_level_data(module_data.get("by_level", {}), level)
        if not level_data:
            return "未找到该级别对应的响应措施。"

        lines = [module_data.get("description", "应急响应措施")]
        if level_data.get("level_label"):
            lines.append(f"适用级别：{level_data['level_label']}")
        if level_data.get("text"):
            lines.append(f"总体要求：{level_data['text']}")

        measures = level_data.get("measures", []) or []
        if measures:
            lines.append("标准动作：")
            for measure in measures:
                if isinstance(measure, str):
                    lines.append(f"- {measure}")
                    continue
                name = measure.get("name", "措施")
                content = measure.get("content", "")
                lines.append(f"- {name}：{content}")

        return "\n".join(lines).strip()

    def _format_scene_disposal(self, module_data: Dict[str, Any], scene_type: str) -> str:
        scene_map = module_data.get("scenes") or module_data.get("dispatch_rules") or {}
        if not isinstance(scene_map, dict) or not scene_map:
            return module_data.get("note", "该预案未提供明确的分场景处置内容。")

        if not scene_type:
            return "可用场景类型：" + "、".join(scene_map.keys())

        matched_scene = self.match_scene_name(scene_map.keys(), scene_type) or scene_type
        content = scene_map.get(matched_scene)
        if content is None:
            return "未找到该场景的处置方案。可用场景类型：" + "、".join(scene_map.keys())

        if isinstance(content, dict):
            text = content.get("content") or content.get("text") or json.dumps(content, ensure_ascii=False, indent=2)
        else:
            text = str(content)

        return f"适用场景：{matched_scene}\n{text}".strip()

    def _format_warning_rules(self, module_data: Dict[str, Any]) -> str:
        levels = module_data.get("levels", {})
        if not isinstance(levels, dict) or not levels:
            return "该预案未提供明确的预警发布规则。"

        lines = [module_data.get("description", "预警发布规则")]
        for warning_name, warning_data in levels.items():
            lines.append(f"\n【{warning_name}】")
            if warning_data.get("trigger"):
                lines.append(f"触发条件：{warning_data['trigger']}")
            if warning_data.get("publisher"):
                lines.append(f"发布主体：{warning_data['publisher']}")
            if warning_data.get("start_flow"):
                lines.append(f"发布流程：{warning_data['start_flow']}")
            if warning_data.get("release_flow"):
                lines.append(f"发布流程：{warning_data['release_flow']}")
            if warning_data.get("end_flow"):
                lines.append(f"解除流程：{warning_data['end_flow']}")
            defense_measures = warning_data.get("defense_measures")
            if isinstance(defense_measures, list):
                lines.append("防御措施：")
                for item in defense_measures:
                    lines.append(f"- {item}")
            elif defense_measures:
                lines.append(f"防御措施：{defense_measures}")
        return "\n".join(lines).strip()
