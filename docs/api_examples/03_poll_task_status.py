"""创建任务并轮询直到完成。"""

import time
import requests

BASE = "http://localhost:8000/api/v1"

EXPECTED_STRUCTURED_FORMAT = {
    "emergency_disposal_overview": [
        "scene_basic_situation_overview",
        "plan_warning_response_overview",
        "material_equipment_dispatch_overview",
        "disposal_process_recommendations_overview",
        "secondary_risks_overview",
    ],
    "emergency_disposal_detail": ["event_location", "weather_condition", "event_summary", "surrounding_environment", "main_impact"],
    "plan_warning_response": ["matched_plan", "event_level", "warning_release", "response_activation", "judgment_basis"],
    "emergency_organization": ["groups"],
    "material_equipment_dispatch": ["items"],
    "disposal_process_recommendations": ["items"],
    "secondary_risks": ["items"],
    "reference_basis": ["references"],
}

EXPECTED_LIST_ITEM_FIELDS = {
    "emergency_organization": ("groups", ["work_group", "lead_unit", "main_responsibilities"]),
    "material_equipment_dispatch": ("items", ["required_material", "recommended_dispatch_source", "distance", "estimated_arrival_time", "location_contact_info", "resource_gap"]),
    "disposal_process_recommendations": ("items", ["sequence", "action", "responsible_unit", "coordinating_unit", "reference_basis"]),
    "secondary_risks": ("items", ["trigger_condition", "risk_description", "impact_consequence", "response_measure", "responsible_unit"]),
    "reference_basis": ("references", ["basis_type", "basis_name", "reference_chapter", "reference_content", "supports_decision"]),
}


def assert_structured_sections_format(sections):
    """校验 API 返回的 structured_sections 是否满足固定字段格式。"""
    if not isinstance(sections, dict):
        raise ValueError("structured_sections 必须是对象")

    for section_key, required_fields in EXPECTED_STRUCTURED_FORMAT.items():
        if section_key not in sections:
            raise ValueError(f"structured_sections 缺少章节: {section_key}")
        section = sections[section_key]
        if not isinstance(section, dict):
            raise ValueError(f"{section_key} 必须是对象")
        for field in required_fields:
            if field not in section:
                raise ValueError(f"{section_key} 缺少字段: {field}")

    for section_key, (list_key, item_fields) in EXPECTED_LIST_ITEM_FIELDS.items():
        items = sections[section_key].get(list_key)
        if not isinstance(items, list) or not items:
            raise ValueError(f"{section_key}.{list_key} 必须是非空数组")
        for item in items:
            if not isinstance(item, dict):
                raise ValueError(f"{section_key}.{list_key} 的元素必须是对象")
            for field in item_fields:
                if field not in item:
                    raise ValueError(f"{section_key}.{list_key} 缺少字段: {field}")
                if item[field] is None:
                    raise ValueError(f"{section_key}.{list_key}.{field} 不能是 None，应为空字符串")


# 创建任务
task_id = requests.post(f"{BASE}/tasks", json={
    "incident_description": "G72高速K85处三车追尾，2人受伤",
}).json()["task_id"]
print(f"任务已创建: {task_id}\n")

# 轮询（建议 3-5 秒间隔）
while True:
    data = requests.get(f"{BASE}/tasks/{task_id}").json()
    status = data["status"]
    progress = data.get("progress", {})
    pipeline = progress.get('pipeline_status', '')
    action = progress.get('current_action', '')
    print(f"[{status}] {action}" + (f" | {pipeline}" if pipeline else ""))

    if status == "completed":
        result = data["result"]
        structured_sections = result.get("structured_sections", {})
        assert_structured_sections_format(structured_sections)
        print("\nstructured_sections 格式校验通过")

        print(f"\n方案前 500 字:\n{result['plan_markdown'][:500]}")
        print(f"\n章节: {list(result['sections'].keys())}")
        overview = structured_sections.get("emergency_disposal_overview", {})
        if overview:
            print("\n应急处置总览:")
            for key, value in overview.get("fields_zh", {}).items():
                print(f"- {key}: {value}")

        detail = structured_sections.get("emergency_disposal_detail", {})
        if detail:
            print("\n应急处置详情:")
            for key, value in detail.get("fields_zh", {}).items():
                print(f"- {key}: {value}")
        plan_response = structured_sections.get("plan_warning_response", {})
        if plan_response:
            print("\n预案匹配与组织预警和响应:")
            for key, value in plan_response.get("fields_zh", {}).items():
                print(f"- {key}: {value}")
        organization = structured_sections.get("emergency_organization", {})
        if organization:
            print("\n应急组织机构:")
            for item in organization.get("groups", []):
                print(
                    f"- {item.get('work_group')}: "
                    f"{item.get('lead_unit')} | {item.get('main_responsibilities')}"
                )

        material_dispatch = structured_sections.get("material_equipment_dispatch", {})
        if material_dispatch:
            print("\n物资装备与调度:")
            for item in material_dispatch.get("items", []):
                print(
                    f"- {item.get('所需物资') or item.get('required_material')}: "
                    f"{item.get('推荐调度来源') or item.get('recommended_dispatch_source')} | "
                    f"{item.get('距离') or item.get('distance')} | "
                    f"{item.get('预计到达时间') or item.get('estimated_arrival_time')}"
                )

        disposal_process = structured_sections.get("disposal_process_recommendations", {})
        if disposal_process:
            print("\n处置流程建议:")
            for item in disposal_process.get("items", [])[:5]:
                print(
                    f"- {item.get('sequence')}: {item.get('action')} | "
                    f"{item.get('responsible_unit')} | {item.get('reference_basis')}"
                )

        secondary_risks = structured_sections.get("secondary_risks", {})
        if secondary_risks:
            print("\n次生风险:")
            for item in secondary_risks.get("items", [])[:5]:
                print(
                    f"- {item.get('risk_description')} | "
                    f"{item.get('trigger_condition')} | {item.get('response_measure')}"
                )

        references = structured_sections.get("reference_basis", {})
        if references:
            print("\n引用依据:")
            for item in references.get("references", [])[:5]:
                print(
                    f"- {item.get('basis_name')} | "
                    f"{item.get('reference_chapter')} | {item.get('supports_decision')}"
                )
        break

    if status in ("failed", "cancelled"):
        print(f"\n任务终止: {data.get('error', {})}")
        break

    time.sleep(5)
