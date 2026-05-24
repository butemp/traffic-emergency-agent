"""标准化最终方案结构化章节。

这个模块不依赖 Agent、工具或模型，专门用于 API 返回前的最后兜底。
目标是：即使某个章节没有生成成功，调用方也能拿到稳定字段，缺失值为空字符串。
"""

from __future__ import annotations

from typing import Any, Dict, Mapping


TEXT_SECTION_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "emergency_disposal_overview": {
        "section_name": "应急处置总览",
        "fields": {
            "scene_basic_situation_overview": "一、事件现场基本情况",
            "plan_warning_response_overview": "二、预案匹配与组织预警和响应",
            "material_equipment_dispatch_overview": "三、物资装备与调度",
            "disposal_process_recommendations_overview": "四、处置流程建议",
            "secondary_risks_overview": "五、次生风险",
        },
    },
    "emergency_disposal_detail": {
        "section_name": "应急处置详情",
        "fields": {
            "event_location": "事件地点",
            "weather_condition": "天气情况",
            "event_summary": "事件简述",
            "surrounding_environment": "周边环境",
            "main_impact": "主要影响",
        },
    },
    "plan_warning_response": {
        "section_name": "预案匹配与组织预警和响应",
        "fields": {
            "matched_plan": "匹配预案",
            "event_level": "事件等级",
            "warning_release": "预警发布",
            "response_activation": "启动响应",
            "judgment_basis": "判断依据",
        },
    },
}

LIST_SECTION_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "material_equipment_dispatch": {
        "section_name": "物资装备与调度",
        "list_key": "items",
        "fields_zh_key": "物资装备与调度",
        "fields": {
            "required_material": "所需物资",
            "recommended_dispatch_source": "推荐调度来源",
            "distance": "距离",
            "estimated_arrival_time": "预计到达时间",
            "location_contact_info": "地点、联系人信息",
            "resource_gap": "资源缺口",
        },
    },
    "disposal_process_recommendations": {
        "section_name": "处置流程建议",
        "list_key": "items",
        "fields_zh_key": "处置流程建议",
        "fields": {
            "sequence": "序号",
            "action": "行动",
            "responsible_unit": "责任单位",
            "coordinating_unit": "协同单位",
            "reference_basis": "引用依据",
        },
    },
    "secondary_risks": {
        "section_name": "次生风险",
        "list_key": "items",
        "fields_zh_key": "次生风险",
        "fields": {
            "trigger_condition": "触发条件",
            "risk_description": "风险描述",
            "impact_consequence": "影响后果",
            "response_measure": "应对措施",
            "responsible_unit": "责任单位",
        },
    },
    "reference_basis": {
        "section_name": "引用依据",
        "list_key": "references",
        "fields_zh_key": "引用依据",
        "fields": {
            "basis_type": "依据类型",
            "basis_name": "依据名称",
            "reference_chapter": "引用章节/模块",
            "reference_content": "引用内容摘要",
            "supports_decision": "支撑决策",
        },
    },
}

ORGANIZATION_FIELDS = {
    "work_group": "工作组",
    "lead_unit": "牵头单位",
    "main_responsibilities": "主要职责",
}

EXPERT_SUPPORT_FIELDS = {
    "name": "姓名",
    "work_unit": "所在单位",
    "specialty_field": "专业方向",
    "professional_title": "职称",
    "phone": "联系电话",
    "dispatch_note": "调度说明",
}


def normalize_structured_sections(value: Any) -> Dict[str, Dict[str, Any]]:
    """把任意结构化章节输出规整到固定 schema。"""
    source = value if isinstance(value, Mapping) else {}
    normalized: Dict[str, Dict[str, Any]] = {}

    for section_key, schema in TEXT_SECTION_SCHEMAS.items():
        normalized[section_key] = _normalize_text_section(source.get(section_key), schema)

    normalized["emergency_organization"] = _normalize_organization_section(
        source.get("emergency_organization")
    )

    for section_key, schema in LIST_SECTION_SCHEMAS.items():
        normalized[section_key] = _normalize_list_section(source.get(section_key), schema)

    return normalized


def _normalize_text_section(value: Any, schema: Dict[str, Any]) -> Dict[str, Any]:
    source = value if isinstance(value, Mapping) else {}
    fields_zh = source.get("fields_zh", {}) if isinstance(source.get("fields_zh"), Mapping) else {}
    section: Dict[str, Any] = {"section_name": _text(source.get("section_name") or schema["section_name"])}
    zh_payload: Dict[str, str] = {}

    for english_key, chinese_key in schema["fields"].items():
        field_value = _text(source.get(english_key) or fields_zh.get(chinese_key))
        section[english_key] = field_value
        zh_payload[chinese_key] = field_value

    section["fields_zh"] = zh_payload
    return section


def _normalize_organization_section(value: Any) -> Dict[str, Any]:
    source = value if isinstance(value, Mapping) else {}
    groups = source.get("groups")
    if not isinstance(groups, list):
        fields_zh = source.get("fields_zh", {}) if isinstance(source.get("fields_zh"), Mapping) else {}
        groups = fields_zh.get("应急组织机构") if isinstance(fields_zh.get("应急组织机构"), list) else []

    normalized_groups = [_normalize_item(item, ORGANIZATION_FIELDS) for item in groups if isinstance(item, Mapping)]
    if not normalized_groups:
        normalized_groups = [_empty_item(ORGANIZATION_FIELDS)]

    # 专家库支持 — 兜底字段，由 pipeline 直接从 task_state.available_resources 注入
    expert_support_raw = source.get("expert_support")
    if not isinstance(expert_support_raw, list):
        fields_zh = source.get("fields_zh", {}) if isinstance(source.get("fields_zh"), Mapping) else {}
        expert_support_raw = (
            fields_zh.get("专家库支持") if isinstance(fields_zh.get("专家库支持"), list) else []
        )
    normalized_experts = [
        _normalize_item(item, EXPERT_SUPPORT_FIELDS)
        for item in expert_support_raw
        if isinstance(item, Mapping)
    ]

    return {
        "section_name": _text(source.get("section_name") or "应急组织机构"),
        "groups": normalized_groups,
        "expert_support": normalized_experts,
        "fields_zh": {
            "应急组织机构": [_to_chinese_item(item, ORGANIZATION_FIELDS) for item in normalized_groups],
            "专家库支持": [_to_chinese_item(item, EXPERT_SUPPORT_FIELDS) for item in normalized_experts],
        },
    }


def _normalize_list_section(value: Any, schema: Dict[str, Any]) -> Dict[str, Any]:
    source = value if isinstance(value, Mapping) else {}
    list_key = schema["list_key"]
    fields_zh_key = schema["fields_zh_key"]
    items = source.get(list_key)

    if not isinstance(items, list):
        fields_zh = source.get("fields_zh", {}) if isinstance(source.get("fields_zh"), Mapping) else {}
        items = fields_zh.get(fields_zh_key) if isinstance(fields_zh.get(fields_zh_key), list) else []

    normalized_items = [_normalize_item(item, schema["fields"]) for item in items if isinstance(item, Mapping)]
    if not normalized_items:
        normalized_items = [_empty_item(schema["fields"])]

    return {
        "section_name": _text(source.get("section_name") or schema["section_name"]),
        list_key: normalized_items,
        "fields_zh": {
            fields_zh_key: [_to_chinese_item(item, schema["fields"]) for item in normalized_items],
        },
    }


def _normalize_item(item: Mapping[str, Any], fields: Mapping[str, str]) -> Dict[str, str]:
    return {
        english_key: _text(item.get(english_key) or item.get(chinese_key))
        for english_key, chinese_key in fields.items()
    }


def _empty_item(fields: Mapping[str, str]) -> Dict[str, str]:
    return {english_key: "" for english_key in fields}


def _to_chinese_item(item: Mapping[str, Any], fields: Mapping[str, str]) -> Dict[str, str]:
    return {chinese_key: _text(item.get(english_key)) for english_key, chinese_key in fields.items()}


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)
