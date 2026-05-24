"""应急预案精确取用工具。

支持三种取数模式：
- module 别名：常用模块的简称（command_structure / response_measures / grading_criteria / ...）
- section_path：中文章节路径，'.' 分隔，末尾支持 '*' 通配
- search_keyword：在预案内全文搜索关键词

详细 module 别名清单可调 EmergencyPlanService.list_scenes()['module_aliases']（plan_index.json）。
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .base import BaseTool
from ..emergency_plans import EmergencyPlanService


_SHARED_PLAN_SERVICE: Optional[EmergencyPlanService] = None


def get_shared_plan_service() -> EmergencyPlanService:
    """获取共享的预案服务实例（懒加载，默认走 parsered_data 数据源）。"""
    global _SHARED_PLAN_SERVICE
    if _SHARED_PLAN_SERVICE is None:
        _SHARED_PLAN_SERVICE = EmergencyPlanService()
    return _SHARED_PLAN_SERVICE


class GetEmergencyPlan(BaseTool):
    """按场景类别和模块/路径/关键词精确获取应急预案内容（parsered_data 数据源）。"""

    def __init__(self, plan_service: Optional[EmergencyPlanService] = None):
        super().__init__(data_path=None)
        self.plan_service = plan_service or get_shared_plan_service()

    @property
    def name(self) -> str:
        return "get_emergency_plan"

    @property
    def description(self) -> str:
        return (
            "按事件场景类别（incident_category）+ 模块别名（module）/ 中文章节路径（section_path）/ 关键词（search_keyword）"
            "三种方式精确取应急预案内容。预案数据为镜像 PDF 章节结构的中文键 JSON，覆盖："
            "组织体系、预防与预警、应急响应（含按级别细分的处置措施）、后期处置、应急保障、预案管理、"
            "附件（含分级标准/响应流程图/信息来源表/通知模板）。"
            "返回 content（原始子树）和 content_text（已 Markdown 化的可读文本）+ hit_path（实际命中路径，用于'七、引用依据'）。"
            "三种查询模式至少传一种；module/section_path 取不到时可改用 search_keyword 全文搜索。"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "incident_category": {
                    "type": "string",
                    "enum": [
                        "EXPRESSWAY", "HIGHWAY", "ROAD_TRANSPORT",
                        "PORT", "WATERWAY", "WATERWAY_XIJIANG", "WATER_TRANSPORT",
                        "CITY_BUS", "URBAN_RAIL", "CONSTRUCTION", "GENERAL",
                    ],
                    "description": "场景类别编码。系统会按 plan_index.scene_plans 路由到对应预案；专项预案缺失时自动回退到 GENERAL（综合预案）",
                },
                "module": {
                    "type": "string",
                    "description": (
                        "模块别名。常用："
                        "command_structure（组织指挥体系）、response_measures（应急响应措施总览）、"
                        "warning_rules（预防与预警全章）、grading_criteria（附件2响应分级表）、"
                        "warning_grading_criteria（附件1预警分级表）、"
                        "info_reporting（信息报送）、news_release（新闻发布）、"
                        "post_processing（后期处置-善后/抚恤/总结评估）、"
                        "emergency_support（应急保障-通信/物资/运力/队伍/资金/技术）、"
                        "plan_management（预案管理-演练/评估/培训/奖惩）、"
                        "initial_disposal（先期处置）、response_adjustment（响应调整及终止）、"
                        "response_start_template / response_end_template（II级响应启动/终止通知模板）、"
                        "warning_start_template / warning_end_template（II级预警通知模板）、"
                        "response_flowchart（应急响应流程图）、info_sources（信息来源一览表）、"
                        "细分组：leadership_group / leadership_office / work_groups / field_team / expert_group、"
                        "应急保障细分：communication_support / material_support / transport_support / team_support / funding_support / tech_support。"
                        "如 module='response_measures' 同时传 level，会自动改查对应级别的子节（response_measures_i/ii/iii/iv）。"
                    ),
                },
                "section_path": {
                    "type": "string",
                    "description": (
                        "中文章节路径，'.' 分隔，末尾支持 '*' 通配。"
                        "适用于 module 别名不够用时直接走原文档章节，例如 "
                        "'组织体系.自治区应急指挥机构.应急工作组' 或 '附件.附件2*' 或 '应急响应.处置措施.Ⅱ级应急响应处置措施'。"
                        "可先调 module=command_structure / warning_rules 等大类拿到 content_text 后再决定要不要钻深"
                    ),
                },
                "search_keyword": {
                    "type": "string",
                    "description": "在预案全文搜关键词，返回所有命中章节路径和上下文片段。适用于不知道路径但知道关键词的场景，例如 '抚恤'、'防御措施'、'征用补偿'",
                },
                "disaster_type": {
                    "type": "string",
                    "enum": ["", "FLOOD", "ICE_SNOW", "EARTHQUAKE", "PUBLIC_HEALTH", "CYBER"],
                    "description": "灾害类别编码。如有，会同时取对应灾害补充预案的同 module/section/keyword 内容，挂在 supplementary_plan 字段",
                },
                "level": {
                    "type": "string",
                    "enum": ["", "特别重大级", "重大级", "较大级", "一般级"],
                    "description": "响应级别。当 module='response_measures' 时会自动改查对应级别的子节（response_measures_i/ii/iii/iv）",
                },
                "scene_type": {
                    "type": "string",
                    "description": "兼容字段。分场景处置类型，目前 parsered_data 风格预案里没有专门的 scene_disposal 字典，此参数主要用于上下文标注",
                },
            },
            "required": ["incident_category"],
        }

    def execute(
        self,
        incident_category: str,
        module: str = "",
        section_path: str = "",
        search_keyword: str = "",
        disaster_type: str = "",
        level: str = "",
        scene_type: str = "",
    ) -> str:
        result = self.plan_service.get_emergency_plan(
            incident_category=incident_category,
            module=module,
            section_path=section_path,
            search_keyword=search_keyword,
            disaster_type=disaster_type,
            level=level,
            scene_type=scene_type,
        )
        return json.dumps(result, ensure_ascii=False, indent=2)
