"""创建任务，轮询结果，并打印固定字段字典。"""

import os
import time
from pprint import pprint

import requests


BASE_URL = os.getenv("TRAFFIC_AGENT_API_BASE", "http://localhost:8000/api/v1")
POLL_INTERVAL_SECONDS = 5


def create_task():
    """创建一个应急指挥任务。"""
    payload = {
        "incident_description": (
            "2026年4月8日11时24分，北海市合浦县廉州镇迎宾大道发生交通事故。"
            "一辆大货车右转弯时与电动车相撞，电动车驾驶员经抢救无效死亡。"
            "现场交通拥堵，需开展交通管制、现场警戒、清障、家属安抚和新闻发布。"
        )
    }
    response = requests.post(f"{BASE_URL}/tasks", json=payload, timeout=30)
    response.raise_for_status()
    return response.json()["task_id"]


def wait_task_done(task_id):
    """轮询任务直到完成。"""
    while True:
        response = requests.get(f"{BASE_URL}/tasks/{task_id}", timeout=30)
        response.raise_for_status()
        data = response.json()

        status = data["status"]
        progress = data.get("progress", {})
        print(f"[{status}] {progress.get('current_action', '')}")

        if status == "completed":
            return data["result"]
        if status in ("failed", "cancelled"):
            raise RuntimeError(data.get("error", {"message": "任务失败"}))

        time.sleep(POLL_INTERVAL_SECONDS)


def pick_item(items):
    """示例只打印每个数组的第一条，避免输出太长。"""
    return items[0] if isinstance(items, list) and items else {}


def chinese_fields(section, list_name=None):
    """读取中文字段；list_name 不为空时读取对应数组。"""
    fields = section.get("fields_zh", {})
    if list_name:
        return fields.get(list_name, [])
    return fields


def build_output_dict(result):
    """把 API 结果整理成字段清晰的字典。"""
    sections = result.get("structured_sections", {})

    overview = sections.get("emergency_disposal_overview", {})
    detail = sections.get("emergency_disposal_detail", {})
    plan = sections.get("plan_warning_response", {})
    organization = sections.get("emergency_organization", {})
    materials = sections.get("material_equipment_dispatch", {})
    process = sections.get("disposal_process_recommendations", {})
    risks = sections.get("secondary_risks", {})
    references = sections.get("reference_basis", {})

    return {
        "task_result": {
            "plan_markdown_preview": result.get("plan_markdown", "")[:300],
            "section_names": list(result.get("sections", {}).keys()),
        },
        "应急处置总览": chinese_fields(overview),
        "应急处置详情": chinese_fields(detail),
        "预案匹配与组织预警和响应": chinese_fields(plan),
        "应急组织机构": pick_item(chinese_fields(organization, "应急组织机构")),
        "物资装备与调度": pick_item(chinese_fields(materials, "物资装备与调度")),
        "处置流程建议": pick_item(chinese_fields(process, "处置流程建议")),
        "次生风险": pick_item(chinese_fields(risks, "次生风险")),
        "引用依据": pick_item(chinese_fields(references, "引用依据")),
    }


if __name__ == "__main__":
    task_id = create_task()
    print(f"任务已创建: {task_id}")

    result = wait_task_done(task_id)
    output = build_output_dict(result)

    print("\n结构化字段字典:")
    pprint(output, width=120, sort_dicts=False)


# 预计返回结构说明：
#
# {
#   "task_result": {
#       "plan_markdown_preview": "最终 Markdown 方案前 300 字",
#       "section_names": ["应急处置总览", "一、事件现场基本情况", "二、预案匹配与组织预警和响应", "三、应急组织机构", "四、物资装备与调度", "五、处置流程建议（包括后期处置、新闻发布）", "六、次生风险", "七、引用依据"]
#   },
#   "应急处置总览": {
#       "一、事件现场基本情况": "",
#       "二、预案匹配与组织预警和响应": "",
#       "三、物资装备与调度": "",
#       "四、处置流程建议": "",
#       "五、次生风险": ""
#   },
#   "应急处置详情": {
#       "事件地点": "",
#       "天气情况": "",
#       "事件简述": "",
#       "周边环境": "",
#       "主要影响": ""
#   },
#   "预案匹配与组织预警和响应": {
#       "匹配预案": "",
#       "事件等级": "",
#       "预警发布": "",
#       "启动响应": "",
#       "判断依据": ""
#   },
#   "应急组织机构": {
#       "工作组": "",
#       "牵头单位": "",
#       "主要职责": ""
#   },
#   "物资装备与调度": {
#       "所需物资": "",
#       "推荐调度来源": "",
#       "距离": "",
#       "预计到达时间": "",
#       "地点、联系人信息": "",
#       "资源缺口": ""
#   },
#   "处置流程建议": {
#       "序号": "",
#       "行动": "",
#       "责任单位": "",
#       "协同单位": "",
#       "引用依据": ""
#   },
#   "次生风险": {
#       "触发条件": "",
#       "风险描述": "",
#       "影响后果": "",
#       "应对措施": "",
#       "责任单位": ""
#   },
#   "引用依据": {
#       "依据类型": "",
#       "依据名称": "",
#       "引用章节/模块": "",
#       "引用内容摘要": "",
#       "支撑决策": ""
#   }
# }
