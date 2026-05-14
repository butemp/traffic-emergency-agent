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
from ..utils.structured_sections import normalize_structured_sections

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
    example: str = ""


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
    structured_sections: Dict[str, Dict[str, Any]]
    section_paths: Dict[str, Path]
    review_paths: Dict[str, List[Path]]
    exhausted_sections: List[str] = field(default_factory=list)


SECTION_SPECS: tuple[SectionSpec, ...] = (
    SectionSpec(
        key="event_overview",
        title="一、事件概述",
        filename="01_event_overview.md",
        min_chars=260,
        required_terms=(
            "应急处置详情", "事件地点", "天气情况", "事件简述", "周边环境", "主要影响",
            "事件类型", "事发时间", "事发位置", "经纬度", "伤亡情况",
        ),
        instructions=(
            "先输出“应急处置详情”固定字段表，字段必须包含：事件地点、天气情况、事件简述、周边环境、主要影响。"
            "随后可补充事件类型、事发时间、经纬度、伤亡/被困、道路影响、路况、信息来源和待确认项。"
            "这 5 个固定字段将被 API 结构化提取，名称不能改写。"
        ),
        example=(
            "### 一、事件概述\n"
            "\n"
            "#### 应急处置详情\n"
            "\n"
            "| 字段 | 内容 |\n"
            "| --- | --- |\n"
            "| 事件地点 | G72泉南高速K85公里处（柳州往南宁方向） |\n"
            "| 天气情况 | 中雨，气温22℃，能见度约500米，可能影响现场通行和救援效率 |\n"
            "| 事件简述 | 现场发生多车追尾事故，涉及1辆重型半挂车和2辆小型客车，3人被困、2人受伤 |\n"
            "| 周边环境 | 附近有收费站、服务区、居民点和高速主线车流等敏感点 |\n"
            "| 主要影响 | 可能造成交通拥堵、人员聚集、燃油泄漏、二次碰撞等次生风险 |\n"
            "\n"
            "#### 事件基础信息\n"
            "\n"
            "| 字段 | 内容 |\n"
            "| --- | --- |\n"
            "| 事件类型 | 交通事故（多车追尾） |\n"
            "| 事发时间 | 2026年5月8日 14:30 |\n"
            "| 事发位置 | G72泉南高速K85公里处（柳州往南宁方向） |\n"
            "| 经纬度 | 108.3201°E, 22.8450°N |\n"
            "| 事件描述 | 一辆重型半挂车因雨天路滑制动不及，与前方两辆小型客车发生追尾碰撞，重型半挂车侧翻占据行车道和超车道，碎片散落约200米路段 |\n"
            "| 伤亡情况 | 2人受伤（其中1人腿部骨折、1人头部擦伤），3人被困于小型客车内 |\n"
            "| 车辆涉及 | 重型半挂车1辆、小型客车2辆 |\n"
            "| 道路影响 | 柳州往南宁方向双车道完全阻断，南宁往柳州方向因围观减速拥堵约2公里 |\n"
            "| 是否涉及危化品 | 现场有燃油泄漏（半挂车油箱破损），暂未发现其他危化品 |\n"
            "| 天气状况 | 中雨，气温22℃，东南风3级，能见度约500米 |\n"
            "| 路况状况 | 事发路段双向六车道，路面湿滑，事故点前方500米为长下坡路段 |\n"
            "| 信息来源 | 12122报警电话、高速交警巡逻反馈、高德实时路况 |\n"
            "| 待确认事项 | 被困人员伤情需到场后评估；燃油泄漏量和扩散范围待现场确认 |\n"
        ),
    ),
    SectionSpec(
        key="response_level",
        title="二、响应定级",
        filename="02_response_level.md",
        min_chars=300,
        required_terms=("预案匹配与组织预警和响应", "匹配预案", "事件等级", "预警发布", "启动响应", "判断依据"),
        instructions=(
            "必须先输出“预案匹配与组织预警和响应”固定字段表，字段必须包含：匹配预案、事件等级、预警发布、启动响应、判断依据。"
            "字段名称不能改写，因为 API 会按这些字段进行结构化提取。随后可补充响应启动主体、预案条款摘要、复核升级/降级条件。"
        ),
        example=(
            "### 二、响应定级\n"
            "\n"
            "#### 预案匹配与组织预警和响应\n"
            "\n"
            "| 字段 | 内容 |\n"
            "| --- | --- |\n"
            "| 匹配预案 | 《广西壮族自治区交通运输综合应急预案》 |\n"
            "| 事件等级 | 一般级（IV级） |\n"
            "| 预警发布 | 建议由合浦县交通运输主管部门按一般预警要求发布交通事故预警信息，并通过交通广播、可变信息板和新媒体提示绕行与避险 |\n"
            "| 启动响应 | 建议启动一般级（IV级）应急响应 |\n"
            "| 判断依据 | 依据预案附件2人员伤亡标准：事件造成1人死亡，符合一般级响应条件；事故发生在普通道路，暂未达到较大及以上响应标准 |\n"
            "\n"
            "#### 补充说明\n"
            "\n"
            "| 字段 | 内容 |\n"
            "| --- | --- |\n"
            "| 响应启动主体 | 合浦县交通运输主管部门主要负责人批准启动，具体流程包括接报信息、初步研判、确认伤亡情况、依据预案条款提出启动建议，并报请批准。 |\n"
            "| 叠加预案 | 无 |\n"
            "| 预案条款摘要 | 预案附件2明确了一般级响应的启动条件，包括人员伤亡和经济损失标准；同时，预案第2节规定了组织指挥体系，明确由县级交通运输主管部门负责一般级响应的启动与指挥。 |\n"
            "| 复核条件 | 由现场指挥人员每2小时评估一次现场情况，如发现伤亡人数超过3人、事故影响范围扩大或交通中断加剧，需立即上报并建议升级响应级别；如现场确认无新增伤亡且交通恢复，可由合浦县交通运输主管部门降级或终止响应。 |\n"
        ),
    ),
    SectionSpec(
        key="command_structure",
        title="三、指挥架构",
        filename="03_command_structure.md",
        min_chars=650,
        required_terms=("应急组织机构", "现场指挥组", "综合协调组", "抢险处置组", "医疗救护组", "后勤保障组", "信息发布组", "专家组", "工作组", "牵头单位", "主要职责"),
        instructions=(
            "必须先输出“应急组织机构”固定表格，字段列必须为：工作组、牵头单位、主要职责。"
            "工作组至少包含：现场指挥组、综合协调组、抢险处置组、医疗救护组、后勤保障组、信息发布组、专家组。"
            "字段名称不能改写，因为 API 会按这些字段进行结构化提取。"
            "可在表格后补充总指挥、副总指挥、专家姓名和协同说明。"
        ),
        example=(
            "### 三、指挥架构\n"
            "\n"
            "#### 应急组织机构\n"
            "\n"
            "| 工作组 | 牵头单位 | 主要职责 |\n"
            "| --- | --- | --- |\n"
            "| 现场指挥组 | 属地政府或现场应急指挥部 | 统一指挥现场处置，研判态势，统筹警戒、救援、清障、医疗、信息发布等工作 |\n"
            "| 综合协调组 | 交通运输主管部门或应急管理部门 | 负责信息汇总、部门协调、资源调度、会商组织和指令流转 |\n"
            "| 抢险处置组 | 消防救援部门、交通养护/运营单位 | 负责人员搜救、现场排险、车辆清障、道路抢通和次生风险控制 |\n"
            "| 医疗救护组 | 卫生健康部门或属地医疗机构 | 负责伤员检伤分类、现场急救、转运衔接和医疗资源协调 |\n"
            "| 后勤保障组 | 属地政府、交通运输主管部门 | 负责物资保障、装备补给、人员饮水餐食、照明通信和临时安置保障 |\n"
            "| 信息发布组 | 宣传部门或指挥部授权单位 | 负责信息报送、新闻发布、舆情监测、公众提示和统一回应口径 |\n"
            "| 专家组 | 指挥部办公室或行业主管部门 | 负责专业研判、技术咨询、风险评估和处置措施优化建议 |\n"
            "\n"
            "**专家库支持**（依据证据包候选专家名单）：\n"
            "\n"
            "- 廖俊锋（广西交通安全研究中心）：专业方向为应急管理、安全管理；建议支持方式为由指挥部办公室或值班人员人工联系专家参与远程会商或现场技术支持\n"
            "- 郑屈（广西交通安全研究中心）：专业方向为安全应急管理；建议支持方式为由指挥部办公室或值班人员人工联系专家参与远程会商或现场技术支持\n"
            "- 林静（南宁轨道交通集团有限责任公司）：专业方向为轨道交通安全质量监管；建议支持方式为由指挥部办公室或值班人员人工联系专家参与远程会商或现场技术支持\n"
            "- 梁进钦（广西壮族自治区钦北公路养护中心）：专业方向为养护工程安全生产和应急管理；建议支持方式为由指挥部办公室或值班人员人工联系专家参与远程会商或现场技术支持\n"
            "- 谭光成（广西安生安全技术有限公司）：专业方向为安全生产与应急管理政策法规；建议支持方式为由指挥部办公室或值班人员人工联系专家参与远程会商或现场技术支持\n"
            "\n"
            "**备注**：\n"
            "\n"
            "- 所有工作组人员派遣和资源调度应由人工联系确认，待现场进一步核实需求。\n"
            "- 指挥架构运行需遵循应急管理统一领导、分级负责原则，确保现场处置高效有序。\n"
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
        example=(
            "### 四、预警发布\n"
            "\n"
            "#### 预警级别\n"
            "\n"
            "根据《广西壮族自治区交通运输综合应急预案》3.4节，本次事件响应级别为一般级，对应预警级别为一般预警（IV级）。\n"
            "\n"
            "#### 发布主体\n"
            "\n"
            "合浦县交通运输局为预警发布主体，负责组织预警信息的审核与发布。\n"
            "\n"
            "#### 发布流程\n"
            "\n"
            "- 信息收集：接报事故信息，收集现场状况、交通影响、伤亡情况等。\n"
            "- 风险评估：由合浦县交通运输局组织初步研判，确认预警级别。\n"
            "- 审批程序：预警内容经合浦县交通运输局主要负责人审核批准。\n"
            "- 发布执行：通过指定渠道对外发布预警信息，并同步报送上级主管部门。\n"
            "\n"
            "#### 发布渠道\n"
            "\n"
            "- 交通广播（如FM93.5等）\n"
            "- 可变信息板\n"
            "- 政府官方网站\n"
            "- 新媒体平台（如微信公众号、微博）\n"
            "\n"
            "#### 预警内容要点\n"
            "\n"
            "- 事件类型：道路运输类交通事故\n"
            "- 事发位置：广西壮族自治区北海市合浦县廉州镇迎宾大道\n"
            "- 当前状况：交通事故现场，交通缓行，有人员死亡\n"
            "- 影响范围：迎宾大道及周边关联道路\n"
            "- 建议措施：减速慢行、绕行避让\n"
            "- 更新安排：每30分钟更新路况与处置进展\n"
            "- 安全提示：注意行车安全，服从现场指挥\n"
            "\n"
            "#### 更新频率\n"
            "\n"
            "预警信息每30分钟更新一次，重点更新交通状况变化、处置进展、管制调整等信息。\n"
            "\n"
            "#### 解除条件\n"
            "\n"
            "预警解除需满足以下条件：\n"
            "\n"
            "- 事故现场处置完毕\n"
            "- 交通恢复正常通行\n"
            "- 经现场指挥确认无衍生风险\n"
            "\n"
            "#### 预案依据\n"
            "\n"
            "本预警发布依据《广西壮族自治区交通运输综合应急预案》3.4节中关于IV级预警的规则执行。\n"
            "\n"
            "#### 可直接发布的预警提示文本\n"
            "\n"
            "> **合浦县交通运输局交通事故预警提示**\n"
            ">\n"
            "> 发布时间：待现场确认\n"
            ">\n"
            "> 预警级别：一般预警（IV级）\n"
            ">\n"
            "> 事件描述：合浦县廉州镇迎宾大道发生交通事故，现场交通缓行，有人员伤亡。\n"
            ">\n"
            "> 影响路段：迎宾大道右转弯段及相邻道路。\n"
            ">\n"
            "> 当前措施：现场已实施交通管制，救援力量正在处置。\n"
            ">\n"
            "> 公众提示：请过往车辆减速慢行，尽量选择绕行路线，注意避让救援车辆。\n"
            ">\n"
            "> 更新安排：每30分钟通过官方渠道更新信息。\n"
            ">\n"
            "> 请服从现场指挥，注意行车安全。\n"
            ">\n"
            "> （合浦县交通运输局发布）\n"
        ),
    ),
    SectionSpec(
        key="action_plan",
        title="五、处置行动方案",
        filename="05_action_plan.md",
        min_chars=900,
        required_terms=(
            "处置流程建议", "序号", "行动", "责任单位", "协同单位", "引用依据",
            "先期处置", "全面响应", "持续处置", "后期处置", "新闻发布",
            "现场警戒", "交通", "二次排查", "家属", "舆情", "时间要求",
        ),
        instructions=(
            "必须输出“处置流程建议（包括后期处置、新闻发布）”固定表格，核心列至少包含：序号、行动、责任单位、协同单位、引用依据。"
            "随后可按三个阶段展开，合计不少于 12 条。每条必须包含行动内容、责任单位、协同单位、时间要求、预案/工具依据。"
            "必须包含涉险人员二次排查、其他伤员排查、检伤分类和转运、家属联络安抚、现场警戒、交通分流、二次事故防范、后期处置、新闻发布。"
        ),
        example=(
            "### 五、处置行动方案\n"
            "\n"
            "#### 处置流程建议（包括后期处置、新闻发布）\n"
            "\n"
            "| 序号 | 行动 | 责任单位 | 协同单位 | 引用依据 |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| 1 | 现场警戒与交通管制，设置警示防护设备，防止二次事故 | 合浦县公安局交通管理大队 | 合浦县交通运输局、消防救援大队 | 《广西壮族自治区交通运输综合应急预案》4.5节 |\n"
            "| 2 | 涉险人员二次排查，确认无遗漏伤亡 | 合浦县消防救援大队 | 合浦县公安局、医疗救援机构 | 《广西壮族自治区交通运输综合应急预案》4.5节 |\n"
            "| 3 | 家属联络与安抚，联系遇难者家属并开展安抚工作 | 合浦县民政局 | 合浦县公安局、卫生健康局 | 《广西壮族自治区交通运输综合应急预案》4.5节 |\n"
            "| 4 | 新闻发布与舆情回应，统一发布事故处置进展和交通绕行提示 | 合浦县委宣传部 | 合浦县交通运输局、公安局 | 《广西壮族自治区交通运输综合应急预案》信息发布要求 |\n"
            "\n"
            "#### 第一阶段：先期处置（0-30分钟）\n"
            "\n"
            "| 序号 | 行动内容 | 责任单位 | 协同单位 | 时间要求 | 预案/工具依据 |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| 1 | 现场警戒与交通管制，设置警示防护设备，防止二次事故 | 合浦县公安局交通管理大队 | 合浦县交通运输局、消防救援大队 | 立即实施 | 《广西壮族自治区交通运输综合应急预案》4.5节 |\n"
            "| 2 | 伤员排查与急救，对现场受伤人员进行检伤分类和初步救治 | 合浦县卫生健康局 | 合浦县公安局、消防救援大队 | 15分钟内 | 《广西壮族自治区交通运输综合应急预案》4.5节 |\n"
            "| 3 | 涉险人员二次排查，确认无遗漏伤亡 | 合浦县消防救援大队 | 合浦县公安局、医疗救援机构 | 20分钟内 | 《广西壮族自治区交通运输综合应急预案》4.5节 |\n"
            "| 4 | 其他伤员排查，扩大搜索范围，确保所有受伤人员得到及时救治 | 合浦县卫生健康局 | 合浦县公安局、消防救援大队 | 持续进行 | 《广西壮族自治区交通运输综合应急预案》4.5节 |\n"
            "| 5 | 家属联络与安抚，联系遇难者家属并开展安抚工作 | 合浦县民政局 | 合浦县公安局、卫生健康局 | 持续进行 | 《广西壮族自治区交通运输综合应急预案》4.5节 |\n"
            "| 6 | 二次事故防范，使用锥桶等警示防护设备设置警戒区 | 合浦县公安局交通管理大队 | 合浦县交通运输局、公安局 | 持续进行 | 《广西壮族自治区交通运输综合应急预案》4.5节 |\n"
            "| 7 | 信息初步报送，向相关部门报告事故基本情况 | 合浦县交通运输局 | 合浦县人民政府办公室 | 30分钟内 | 《广西壮族自治区交通运输综合应急预案》4.5节 |\n"
            "\n"
            "#### 第二阶段：全面响应（30分钟-2小时）\n"
            "\n"
            "| 序号 | 行动内容 | 责任单位 | 协同单位 | 时间要求 | 预案/工具依据 |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| 8 | 事故现场勘察取证，查明事故原因 | 合浦县公安局 | 合浦县交通运输局 | 1小时内 | 《广西壮族自治区交通运输综合应急预案》4.5节 |\n"
            "| 9 | 交通疏导与路线优化，实施交通分流，缓解拥堵 | 合浦县公安局交通管理大队 | 合浦县交通运输局、消防救援大队 | 持续进行 | 《广西壮族自治区交通运输综合应急预案》4.5节 |\n"
            "| 10 | 舆情监测与回应，监控网络舆情并准备发布信息 | 合浦县委宣传部 | 合浦县交通运输局、公安局 | 每30分钟汇总 | 《广西壮族自治区交通运输综合应急预案》4.5节 |\n"
            "| 11 | 清障恢复，调用拖车等车辆装备清理事故现场 | 合浦县公路养护中心 | 合浦县公安局、交通运输局 | 2小时内 | 《广西壮族自治区交通运输综合应急预案》4.5节 |\n"
            "| 12 | 应急资源调度协调，应由人工联系北海应急仓库获取支援 | 合浦县交通运输局 | 各救援单位 | 持续进行 | 《广西壮族自治区交通运输综合应急预案》4.5节 |\n"
            "| 13 | 其他伤员排查，再次确认现场及周边无遗漏受伤人员 | 合浦县卫生健康局 | 合浦县公安局、消防救援大队 | 持续进行 | 《广西壮族自治区交通运输综合应急预案》4.5节 |\n"
            "\n"
            "#### 第三阶段：持续处置与恢复（2小时以后）\n"
            "\n"
            "| 序号 | 行动内容 | 责任单位 | 协同单位 | 时间要求 | 预案/工具依据 |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| 14 | 恢复交通通行，逐步解除交通管制 | 合浦县公路养护中心 | 合浦县公安局、交通运输局 | 持续进行 | 《广西壮族自治区交通运输综合应急预案》4.5节 |\n"
            "| 15 | 事故原因调查分析，配合相关部门完成调查 | 合浦县公安局 | 合浦县交通运输局、公路养护中心 | 按需进行 | 《广西壮族自治区交通运输综合应急预案》4.5节 |\n"
            "| 16 | 总结评估，形成事故处置报告 | 合浦县交通运输局 | 合浦县人民政府 | 事故处理完毕后24小时内 | 《广西壮族自治区交通运输综合应急预案》4.5节 |\n"
        ),
    ),
    SectionSpec(
        key="resource_dispatch",
        title="六、资源调度方案",
        filename="06_resource_dispatch.md",
        min_chars=1000,
        required_terms=(
            "物资装备与调度", "所需物资", "推荐调度来源", "距离", "预计到达时间", "地点、联系人信息", "资源缺口",
            "第一梯队", "第二梯队", "外部资源", "专家技术支持", "资源覆盖", "联系人", "电话",
            "调度路径", "可调配物资", "用途", "缺口", "补充建议",
        ),
        instructions=(
            "这是最关键章节之一。必须先输出“物资装备与调度”固定字段表，列必须包含：“所需物资”“推荐调度来源”“距离”“预计到达时间”“地点、联系人信息”“资源缺口”。"
            "随后必须基于实际资源、专家和路线数据写。按 #### 第一梯队、#### 第二梯队、"
            "#### 外部资源补充、#### 专家技术支持、#### 资源覆盖与缺口分析组织。"
            "每个资源单独成行，写清资源名称、类型、所属单位/出发地、可调配物资/队伍能力（含用途说明）、距离、"
            "预计到达、调度路径、联系人、电话。物资列要写成'物资名（用途）'格式，直接融入梯队表格，不要单独拆成关键物资用途说明小节。"
            "资源覆盖与缺口分析按能力需求（如现场警戒、清障、人员搜救、医疗急救等）而非物资类别来分析。"
        ),
        example=(
            "### 六、资源调度方案\n"
            "\n"
            "#### 物资装备与调度\n"
            "\n"
            "| 所需物资 | 推荐调度来源 | 距离 | 预计到达时间 | 地点、联系人信息 | 资源缺口 |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| 路锥、标志牌、爆闪灯等警示防护物资 | 北海应急仓库 | 1.76km | 5分钟 | 广西新发展交通集团有限公司南宁高速公路运营分公司；黄世鹏 / 13978923335 | 无 |\n"
            "| 拖车、清障人员等清障救援能力 | 北海运营分公司应急抢险队伍 | 1.76km | 5分钟 | 广西壮族自治区北海市合浦县廉州镇G7212柳北高速；吴承远 / 13607892598 | 无 |\n"
            "| 液压破拆、专业搜救、救护车等专业救援能力 | 消防救援部门、卫生健康部门 | 暂未获取 | 待人工确认 | 待人工联系确认 | 内部资源暂未覆盖，需外部协同 |\n"
            "\n"
            "#### 第一梯队（15km内，预计15分钟内到达）\n"
            "\n"
            "| 资源名称 | 类型 | 所属单位/出发地 | 可调配物资/队伍能力 | 距离 | 预计到达 | 调度路径 | 联系人 | 电话 |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
            "| 北海应急仓库 | 仓库 | 广西新发展交通集团有限公司南宁高速公路运营分公司 | 路锥（用于上游警戒区渠化）、单柱式标志牌x2套（用于交通管制指示）、移动式应急发电机（用于应急照明）、5吨平板拖车（用于物资运输）、高空作业车（用于高处作业） | 1.76km | 5分钟 | 路线暂未规划，需由人工调度平台确认 | 黄世鹏 | 13978923335 |\n"
            "| 北海运营分公司应急抢险队伍 | 队伍 | 广西壮族自治区北海市合浦县廉州镇G7212柳北高速 | 拖车（用于清障救援、移除事故车辆）、21人应急抢险力量 | 1.76km | 5分钟 | 路线暂未规划，需由人工调度平台确认 | 吴承远 | 13607892598 |\n"
            "| 广西北投交通养护科技集团有限公司沿海项目部合浦养护应急队 | 队伍 | 广西北投交通养护科技集团有限公司沿海项目部 | 养护抢险车辆装备（用于道路抢通与现场清理） | 2.71km | 8分钟 | 路线暂未规划，需由人工调度平台确认 | 李照强 | 13978912640 |\n"
            "| 广西北投交通养护科技集团有限公司沿海项目部白沙养护应急队 | 队伍 | 广西北投交通养护科技集团有限公司沿海项目部 | 养护抢险车辆装备（用于协同清障与路面修复） | 2.71km | 8分钟 | 路线暂未规划，需由人工调度平台确认 | 周日栋 | 18277901101 |\n"
            "\n"
            "#### 第二梯队（15-35km，预计30分钟内到达）\n"
            "\n"
            "| 资源名称 | 类型 | 所属单位/出发地 | 可调配物资/队伍能力 | 距离 | 预计到达 | 调度路径 | 联系人 | 电话 |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
            "| 应急服务分中心公馆排障队 | 队伍 | 暂未获取具体地址 | 排障车辆装备（用于大型事故车辆清障） | 24.99km | 20分钟 | 路线暂未规划，需由人工调度平台确认 | 黄桂南 | 13737530705 |\n"
            "\n"
            "#### 外部资源补充\n"
            "\n"
            "| 资源名称 | 类型 | 所属单位/出发地 | 可调配物资/队伍能力 | 距离 | 预计到达 | 调度路径 | 联系人 | 电话 |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
            "| 公馆工区应急仓库 | 仓库 | 广西壮族自治区北海市合浦县公馆镇公馆收费站(G59呼北高速入口) | 反光背心（用于人员防护）、交通锥（用于警戒线设置）、爆闪灯（用于低能见度警示）、照明灯（用于现场照明）、消防器材、通信照明设备 | 37.34km | 25分钟 | 路线暂未规划，需由人工调度平台确认 | 范先学 | 13607890157 |\n"
            "| 博白分公司公馆应急仓库 | 仓库 | 广西交通投资集团玉林高速公路运营有限公司 | 其他物资（待现场确认具体需求后调配） | 37.34km | 25分钟 | 路线暂未规划，需由人工调度平台确认 | 冯传经 | 13481757158 |\n"
            "| 玉林高速公路运营有限公司公馆排障队 | 队伍 | 广西壮族自治区北海市合浦县公馆镇公馆收费站(G59呼北高速入口) | 暂未获取具体物资清单 | 37.34km | 25分钟 | 路线暂未规划，需由人工调度平台确认 | 冯传经 | 13507753519 |\n"
            "\n"
            "#### 专家技术支持\n"
            "\n"
            "| 专家姓名 | 所属单位 | 专业方向 | 建议支持方式 | 联系人 | 电话 |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| 廖俊锋 | 广西交通安全研究中心 | 应急管理、安全管理 | 应由人工联系专家参与远程会商或现场技术支持 | 廖俊锋 | 15994331520 |\n"
            "| 郑屈 | 广西交通安全研究中心 | 安全应急管理 | 应由人工联系专家参与远程会商或现场技术支持 | 郑屈 | 15078186886 |\n"
            "| 林静 | 南宁轨道交通集团有限责任公司 | 轨道交通安全质量监管 | 应由人工联系专家参与远程会商或现场技术支持 | 林静 | 18077796977 |\n"
            "| 梁进钦 | 广西壮族自治区钦北公路养护中心 | 养护工程安全生产和应急管理 | 应由人工联系专家参与远程会商或现场技术支持 | 梁进钦 | 13207772808 |\n"
            "| 谭光成 | 广西安生安全技术有限公司 | 安全生产与应急管理政策法规 | 应由人工联系专家参与远程会商或现场技术支持 | 谭光成 | 18172087288 |\n"
            "\n"
            "#### 资源覆盖与缺口分析\n"
            "\n"
            "| 能力需求 | 覆盖状态 | 现有来源 | 缺口 | 补充建议 | 人工确认事项 |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| 现场警戒与交通管制 | 已覆盖 | 北海应急仓库（路锥、标志牌、爆闪灯） | 无 | — | 出发前电话确认库存可用性 |\n"
            "| 清障与道路抢通 | 已覆盖 | 北海应急仓库（拖车）、3支抢险队伍 | 无 | — | 确认拖车和清障设备可用状态 |\n"
            "| 现场照明与电力保障 | 已覆盖 | 北海应急仓库（发电机）、公馆工区（照明灯） | 无 | — | 需评估夜间作业时长，确认燃油储备 |\n"
            "| 人员搜救与被困救援 | 未覆盖 | 无专业救生装备 | 缺少液压剪切器等破拆工具 | 建议协调合浦县消防救援大队携带专业破拆设备 | 需到场后评估被困人员救援条件 |\n"
            "| 医疗急救与伤员转运 | 未覆盖 | 无内部医疗资源 | 缺少急救设备和救护车 | 建议协调合浦县卫生健康局派出救护车和急救人员 | 需确认最近医院接诊能力 |\n"
            "| 现场人员安全防护 | 部分覆盖 | 公馆工区应急仓库（反光背心，37km） | 第一梯队无防护用品 | 建议第一梯队出发前自备基本防护装备 | 需现场评估实际需求量 |\n"
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
        example=(
            "### 七、信息报送与新闻发布\n"
            "\n"
            "#### 信息报送\n"
            "\n"
            "| 报送类型 | 报送对象 | 时限 | 方式 | 责任单位 |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| 初报 | 合浦县人民政府、北海市交通运输局 | 15分钟内 | 电话、短信 | 合浦县交通运输局 |\n"
            "| 续报 | 合浦县人民政府、北海市交通运输局 | 30分钟内 | 书面材料 | 合浦县交通运输局 |\n"
            "| 终报 | 合浦县人民政府、北海市交通运输局 | 事故处理完毕后24小时内 | 完整报告 | 合浦县交通运输局 |\n"
            "\n"
            "#### 新闻发布\n"
            "\n"
            "| 发布类型 | 发布内容 | 发布渠道 | 责任单位 |\n"
            "| --- | --- | --- | --- |\n"
            "| 新闻发布 | 事故基本情况、救援进展、交通管制措施、安全提示 | 政府网站、交通广播、新媒体平台 | 合浦县委宣传部 |\n"
            "| 舆情监测 | 网络舆情 | 每30分钟 | 舆情报告 |\n"
            "| 回应口径 | 事故基本情况、救援进展、交通管制措施、安全提示 | 政府网站、社交媒体 | 合浦县委宣传部 |\n"
            "| 家属沟通边界 | 应由人工联系家属，通报事故情况、伤亡信息及善后安排，避免透露未经核实细节 | 政府网站、社交媒体 | 合浦县民政局 |\n"
            "\n"
            "**说明**：\n"
            "\n"
            "- 初报、续报、终报内容应基于现场确认信息，暂未获取的伤亡人数、事故原因等需注明'待现场确认'。\n"
            "- 新闻发布主体为合浦县委宣传部，发布内容应确保准确、统一。\n"
            "- 舆情监测需持续进行，发现不实信息应及时澄清。\n"
            "- 家属沟通应由责任单位人工进行，确保信息准确、安抚及时。\n"
        ),
    ),
    SectionSpec(
        key="risks",
        title="八、风险提示与注意事项",
        filename="08_risks.md",
        min_chars=1000,
        required_terms=("次生风险", "安全风险", "处置风险", "衍生风险", "风险描述", "触发条件", "影响后果", "应对措施", "责任单位", "监测指标", "升级条件"),
        instructions=(
            "必须分为 #### 安全风险、#### 处置风险、#### 衍生风险。每类至少 3 条，优先写 10-12 条。"
            "每条风险必须用表格写清风险描述、触发条件、影响后果、应对措施、责任单位、监测指标、升级条件；"
            "其中触发条件、风险描述、影响后果、应对措施、责任单位会被 API 结构化提取，列名不要改写。"
            "并结合本次事故的天气、路况、伤亡、资源缺口、舆情和家属安抚实际情况。"
        ),
        example=(
            "### 八、风险提示与注意事项\n"
            "\n"
            "#### 安全风险\n"
            "\n"
            "| 风险描述 | 触发条件 | 影响后果 | 应对措施 | 责任单位 | 监测指标 | 升级条件 |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
            "| 雾天能见度低，增加二次事故风险 | 能见度低于500米，车辆未及时减速 | 可能造成更多人员伤亡和财产损失 | 在事故上游设置渐变式警戒区，使用交通锥进行渠化，并部署爆闪灯增强警示 | 合浦县公安交管部门 | 能见度变化、车流量 | 能见度持续低于200米超过30分钟或车流量增加50%以上 |\n"
            "| 现场作业人员未佩戴防护装备，存在安全隐患 | 未正确穿戴反光背心、安全帽等个人防护用品 | 救援人员受伤，影响救援效率 | 检查所有作业人员防护装备佩戴情况，确保反光背心、安全帽等正确使用 | 合浦县公安交管部门 | 现场人员防护装备佩戴率、受伤情况 | 发生救援人员受伤事件或防护装备缺失率超过20% |\n"
            "| 清障作业过程中车辆侧翻或碰撞风险 | 操作不当或现场环境复杂 | 造成设备损坏或人员伤亡 | 严格执行操作规程，加强现场监护，使用防撞缓冲车提供保护 | 合浦县交通运输主管部门 | 作业安全事故发生率、设备损坏情况 | 发生作业安全事故或设备严重损坏 |\n"
            "| 雾天持续，能见度进一步恶化 | 湿度95%，持续有雾 | 增加救援难度和安全风险 | 加强现场照明，使用照明灯提供充足光线，必要时调整作业时间 | 合浦县应急管理部门 | 能见度变化趋势、湿度水平 | 能见度低于100米或出现浓雾持续1小时以上 |\n"
            "\n"
            "#### 处置风险\n"
            "\n"
            "| 风险描述 | 触发条件 | 影响后果 | 应对措施 | 责任单位 | 监测指标 | 升级条件 |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
            "| 救生救援装备不足，影响伤员救治 | 需要紧急医疗救援但装备缺失 | 延误救治，加重伤亡 | 立即联系附近医院建立医疗转运通道，协调医疗资源快速响应 | 合浦县卫生健康部门 | 医疗资源响应时间、装备可用性 | 医疗资源响应超过30分钟或装备缺口超过50% |\n"
            "| 现场交通疏导不当，可能引发周边道路拥堵 | 交通管制措施不合理或执行不到位 | 影响区域交通秩序，延长救援时间 | 实时监测周边路况，优化交通组织，使用交通锥进行有效渠化 | 合浦县公安交管部门 | 周边道路拥堵程度、车流速度 | 拥堵蔓延至主干道或持续时间超过1小时 |\n"
            "| 信息报送不及时或不准确，影响决策 | 报送流程不清晰或责任不明 | 可能导致指挥决策失误 | 明确信息报送流程和责任人，建立定时报送机制 | 合浦县交通运输主管部门 | 信息报送延迟时间、信息准确率 | 延迟超过45分钟或出现重大信息遗漏 |\n"
            "| 缺乏专业技术支持，可能影响事故调查和处置效果 | 复杂技术问题需要专业指导 | 影响事故定性和责任认定 | 应由人工联系专家提供技术支持，如廖俊锋、郑屈等 | 合浦县交通运输主管部门 | 技术问题复杂程度、专家响应时间 | 涉及专业技术难题或重大争议，专家无法及时提供支持 |\n"
            "\n"
            "#### 衍生风险\n"
            "\n"
            "| 风险描述 | 触发条件 | 影响后果 | 应对措施 | 责任单位 | 监测指标 | 升级条件 |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
            "| 家属情绪激动，可能引发群体性事件 | 信息沟通不畅，安抚措施不到位 | 可能影响社会稳定和舆情 | 建立家属安抚机制，及时沟通事故信息，提供心理支持 | 合浦县应急管理部门 | 家属情绪状态、聚集人数 | 聚集人数超过20人或出现激烈冲突 |\n"
            "| 事故信息不透明，可能引发网络谣言扩散 | 官方信息发布不及时 | 造成社会恐慌，影响政府公信力 | 由舆情组每30分钟汇总网络舆情，准备新闻发布材料 | 合浦县应急管理部门 | 网络舆情热度、谣言数量 | 舆情热度超过阈值或出现重大负面舆情 |\n"
            "| 资源调度延迟，影响应急响应效率 | 应急仓库物资未及时调配 | 延误现场处置，扩大事故影响 | 立即调度公馆工区应急仓库资源，如交通锥、照明灯等，确保快速到达 | 合浦县交通运输主管部门 | 资源到达时间、调度响应率 | 资源到达时间超过45分钟或调度失败率超过30% |\n"
            "| 天气变化导致救援条件恶化 | 雾天持续，温度24℃，湿度95% | 增加现场作业难度和风险 | 加强气象监测，提前准备备用救援方案，必要时请求增援 | 合浦县应急管理部门 | 气象预警等级、温湿度变化 | 气象台发布橙色及以上预警或现场指挥判断需暂停作业 |\n"
        ),
    ),
    SectionSpec(
        key="references",
        title="九、依据引用",
        filename="09_references.md",
        min_chars=340,
        required_terms=("引用依据", "预案名称", "引用章节", "引用内容", "支撑", "工具结果", "案例"),
        instructions=(
            "汇总预案、法规/RAG、工具结果、资源调度、路线规划、风险评估和历史案例依据。"
            "用表格写清依据名称、章节/模块、引用内容摘要、支撑哪个处置决策。"
            "表格列名建议保持为：依据类型、依据名称、引用章节/模块、引用内容摘要、支撑决策，便于 API 结构化提取。"
        ),
        example=(
            "### 九、依据引用\n"
            "\n"
            "| 依据类型 | 依据名称 | 引用章节/模块 | 引用内容摘要 | 支撑决策 |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| 应急预案 | 《广西壮族自治区交通运输综合应急预案》 | 附件2-分级标准 | 一般级（IV级）：造成3人以下死亡或危及3人以下生命安全 | 响应定级为IV级 |\n"
            "| 应急预案 | 《广西壮族自治区交通运输综合应急预案》 | 第2节-组织指挥体系 | 县级交通运输主管部门负责一般级响应的启动与指挥 | 指挥架构设置 |\n"
            "| 应急预案 | 《广西壮族自治区交通运输综合应急预案》 | 第3.4节-预警规则 | IV级预警由县级交通运输主管部门发布 | 预警发布主体与流程 |\n"
            "| 应急预案 | 《广西壮族自治区交通运输综合应急预案》 | 第4.5节-应急响应措施 | 先期处置应包含现场警戒、伤员救治、交通管制、信息报送 | 处置行动方案三阶段设计 |\n"
            "| 工具结果 | geocode_address | 地理编码 | 事发位置解析为经度109.2017、纬度21.6616 | 事件概述中的经纬度与资源距离计算 |\n"
            "| 工具结果 | get_weather_by_location | 实时天气 | 多云，25℃，东南风≤3级，湿度88% | 事件概述中的天气状况与风险提示 |\n"
            "| 工具结果 | evaluate_incident_severity | 事件定级 | 判定为一般级（IV级），置信度0.85 | 响应定级依据 |\n"
            "| 工具结果 | search_emergency_resources | 资源搜索 | 搜索到1个仓库、4支队伍，覆盖交通标志标牌、车辆装备等类别 | 资源调度方案梯队编排 |\n"
            "| 工具结果 | optimize_dispatch_plan | 调度优化 | 生成三梯队调度方案，第一梯队4个资源、第二梯队1个资源 | 资源调度方案梯队划分 |\n"
            "| 工具结果 | search_experts | 专家检索 | 匹配5位专家，涵盖应急管理、安全生产等方向 | 指挥架构专家技术支持组 |\n"
            "| 工具结果 | risk_assessment | 风险评估 | 综合评分75分，较高风险，建议加强警戒和医疗保障 | 风险提示与注意事项 |\n"
            "| 历史案例 | 类似道路交通事故处置案例 | 案例库 | 相似事故中采用渐变式警戒区+远端分流的处置模式 | 处置行动方案中警戒区设置方式 |\n"
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
            try:
                text, paths, exhausted = self._generate_section_with_review(
                    spec=spec,
                    evidence=evidence,
                    seed_plan=seed_plan,
                    global_feedback=global_feedback,
                    sections_dir=sections_dir,
                    reviews_dir=reviews_dir,
                )
            except Exception as error:
                logger.exception("章节生成失败，写入错误占位后继续: section=%s, error=%s", spec.title, error)
                text = self._build_section_error_placeholder(spec, error)
                paths = []
                exhausted = True
            section_texts[spec.title] = text
            section_path = sections_dir / spec.filename
            self._write_text(section_path, text)
            section_paths[spec.title] = section_path
            review_paths[spec.title] = paths
            if exhausted:
                exhausted_sections.append(spec.title)

        structured_sections = self.build_structured_sections(task_state, section_texts)
        overview_text = self._build_overview_markdown(structured_sections)
        overview_path = sections_dir / "00_emergency_disposal_overview.md"
        self._write_text(overview_path, overview_text)
        section_texts = {"应急处置总览": overview_text, **section_texts}
        section_paths["应急处置总览"] = overview_path

        final_markdown = self._merge_sections(section_texts)
        self._write_text(run_dir / "final_plan.md", final_markdown)
        self._write_text(
            run_dir / "structured_sections.json",
            json.dumps(structured_sections, ensure_ascii=False, indent=2, default=str),
        )

        return FinalPlanPipelineResult(
            final_markdown=final_markdown,
            run_dir=run_dir,
            evidence_path=evidence_path,
            section_texts=section_texts,
            structured_sections=structured_sections,
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
            try:
                text, paths, exhausted = self._generate_section_with_review(
                    spec=spec,
                    evidence=evidence,
                    seed_plan=previous_draft,
                    global_feedback=section_feedback,
                    sections_dir=sections_dir,
                    reviews_dir=reviews_dir,
                    tag=f"global_retry_{attempt}",
                )
            except Exception as error:
                logger.exception("章节局部重写失败，保留错误占位: section=%s, error=%s", spec.title, error)
                text = self._build_section_error_placeholder(spec, error, previous_draft=previous_draft)
                paths = []
                exhausted = True
            section_texts[spec.title] = text
            section_path = sections_dir / spec.filename
            self._write_text(section_path, text)
            section_paths[spec.title] = section_path
            review_paths.setdefault(spec.title, []).extend(paths)
            if exhausted and spec.title not in exhausted_sections:
                exhausted_sections.append(spec.title)

        structured_sections = self.build_structured_sections(task_state, section_texts)
        overview_text = self._build_overview_markdown(structured_sections)
        overview_path = sections_dir / "00_emergency_disposal_overview.md"
        self._write_text(overview_path, overview_text)
        section_texts["应急处置总览"] = overview_text
        section_paths["应急处置总览"] = overview_path

        final_markdown = self._merge_sections(section_texts)
        self._write_text(pipeline_result.run_dir / f"final_plan_global_retry_{attempt}.md", final_markdown)
        self._write_text(pipeline_result.run_dir / "final_plan.md", final_markdown)
        self._write_text(
            pipeline_result.run_dir / "structured_sections.json",
            json.dumps(structured_sections, ensure_ascii=False, indent=2, default=str),
        )

        return FinalPlanPipelineResult(
            final_markdown=final_markdown,
            run_dir=pipeline_result.run_dir,
            evidence_path=pipeline_result.evidence_path,
            section_texts=section_texts,
            structured_sections=structured_sections,
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
        ]

        if spec.example:
            parts.extend([
                "",
                "【格式示例（请严格参照此格式，内容替换为证据包中的实际数据）】",
                spec.example,
            ])

        parts.extend([
            "",
            "【证据包】",
            evidence,
        ])

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

    def build_structured_sections(
        self,
        task_state: TaskState,
        section_texts: Dict[str, str],
    ) -> Dict[str, Dict[str, Any]]:
        """生成 API 友好的固定字段结构。

        Markdown 仍按完整方案章节生成；这里额外提供面向 API 的稳定字段。
        未能从章节或状态中提取到的字段统一返回空字符串，便于调用方固定解析。
        """
        raw_sections = {
            "emergency_disposal_detail": self._build_emergency_disposal_detail(
                task_state=task_state,
                section_text=section_texts.get("一、事件概述", ""),
            ),
            "plan_warning_response": self._build_plan_warning_response(
                task_state=task_state,
                section_text=section_texts.get("二、响应定级", ""),
            ),
            "emergency_organization": self._build_emergency_organization(
                task_state=task_state,
                section_text=section_texts.get("三、指挥架构", ""),
            ),
            "material_equipment_dispatch": self._build_material_equipment_dispatch(
                task_state=task_state,
                section_text=section_texts.get("六、资源调度方案", ""),
            ),
            "disposal_process_recommendations": self._build_disposal_process_recommendations(
                section_text="\n\n".join(
                    [
                        section_texts.get("五、处置行动方案", ""),
                        section_texts.get("七、信息报送与新闻发布", ""),
                    ]
                ),
            ),
            "secondary_risks": self._build_secondary_risks(
                section_text=section_texts.get("八、风险提示与注意事项", ""),
            ),
            "reference_basis": self._build_reference_basis(
                task_state=task_state,
                section_text=section_texts.get("九、依据引用", ""),
            ),
        }
        normalized_sections = normalize_structured_sections(raw_sections)
        normalized_sections["emergency_disposal_overview"] = self._build_emergency_disposal_overview(
            normalized_sections
        )
        return normalize_structured_sections(normalized_sections)

    def _build_emergency_disposal_overview(self, sections: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """基于已结构化章节生成“应急处置总览”固定字段。"""
        detail = sections.get("emergency_disposal_detail", {})
        plan_response = sections.get("plan_warning_response", {})
        material_dispatch = sections.get("material_equipment_dispatch", {})
        disposal_process = sections.get("disposal_process_recommendations", {})
        secondary_risks = sections.get("secondary_risks", {})

        scene_overview = self._join_brief(
            [
                detail.get("event_location"),
                detail.get("event_summary"),
                detail.get("weather_condition"),
                detail.get("main_impact"),
            ]
        )
        plan_overview = self._join_brief(
            [
                plan_response.get("matched_plan"),
                plan_response.get("event_level"),
                plan_response.get("response_activation"),
                plan_response.get("warning_release"),
            ]
        )
        material_overview = self._summarize_material_dispatch_overview(material_dispatch.get("items", []))
        process_overview = self._summarize_process_overview(disposal_process.get("items", []))
        risk_overview = self._summarize_risk_overview(secondary_risks.get("items", []))

        return {
            "section_name": "应急处置总览",
            "scene_basic_situation_overview": scene_overview,
            "plan_warning_response_overview": plan_overview,
            "material_equipment_dispatch_overview": material_overview,
            "disposal_process_recommendations_overview": process_overview,
            "secondary_risks_overview": risk_overview,
            "fields_zh": {
                "一、事件现场基本情况": scene_overview,
                "二、预案匹配与组织预警和响应": plan_overview,
                "三、物资装备与调度": material_overview,
                "四、处置流程建议": process_overview,
                "五、次生风险": risk_overview,
            },
        }

    def _build_emergency_disposal_detail(
        self,
        task_state: TaskState,
        section_text: str,
    ) -> Dict[str, Any]:
        """构建“应急处置详情”固定字段。"""
        incident = task_state.incident_info
        environment = task_state.environment_info

        event_location = (
            incident.location_text
            or environment.formatted_address
            or self._extract_markdown_field(section_text, ("事件地点", "事发位置", "地点", "位置"))
            or ""
        )
        weather_condition = (
            self._format_weather_condition(environment.weather)
            or self._extract_markdown_field(section_text, ("天气情况", "天气状况"))
            or ""
        )
        event_summary = (
            self._extract_markdown_field(section_text, ("事件简述", "事件描述"))
            or self._compose_event_summary(task_state)
            or ""
        )
        surrounding_environment = (
            self._format_surrounding_environment(environment.nearby_pois)
            or self._extract_markdown_field(section_text, ("周边环境", "周边敏感点", "周边情况"))
            or ""
        )
        main_impact = (
            self._extract_markdown_field(section_text, ("主要影响", "道路影响", "影响范围"))
            or self._compose_main_impact(task_state)
            or ""
        )

        return {
            "section_name": "应急处置详情",
            "event_location": event_location,
            "weather_condition": weather_condition,
            "event_summary": event_summary,
            "surrounding_environment": surrounding_environment,
            "main_impact": main_impact,
            "fields_zh": {
                "事件地点": event_location,
                "天气情况": weather_condition,
                "事件简述": event_summary,
                "周边环境": surrounding_environment,
                "主要影响": main_impact,
            },
        }

    def _build_plan_warning_response(
        self,
        task_state: TaskState,
        section_text: str,
    ) -> Dict[str, Any]:
        """构建“预案匹配与组织预警和响应”固定字段。"""
        incident = task_state.incident_info
        matched_plan = (
            self._extract_markdown_field(section_text, ("匹配预案", "适用预案"))
            or self._find_primary_plan_name(task_state)
            or ""
        )
        event_level = (
            incident.response_level
            or self._extract_markdown_field(section_text, ("事件等级", "响应级别"))
            or ""
        )
        warning_release = (
            self._extract_markdown_field(section_text, ("预警发布", "预警发布建议"))
            or self._compose_warning_release(task_state)
            or ""
        )
        response_activation = (
            self._extract_markdown_field(section_text, ("启动响应", "响应启动", "启动建议"))
            or self._compose_response_activation(event_level)
            or ""
        )
        judgment_basis = (
            incident.response_level_reason
            or self._extract_markdown_field(section_text, ("判断依据", "定级依据", "预案依据"))
            or ""
        )

        return {
            "section_name": "预案匹配与组织预警和响应",
            "matched_plan": matched_plan,
            "event_level": event_level,
            "warning_release": warning_release,
            "response_activation": response_activation,
            "judgment_basis": judgment_basis,
            "fields_zh": {
                "匹配预案": matched_plan,
                "事件等级": event_level,
                "预警发布": warning_release,
                "启动响应": response_activation,
                "判断依据": judgment_basis,
            },
        }

    @staticmethod
    def _join_brief(parts: List[Any], max_chars: int = 160) -> str:
        text = "；".join(str(part).strip() for part in parts if str(part or "").strip())
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 1].rstrip("；，。,. ") + "…"

    def _summarize_material_dispatch_overview(self, items: Any) -> str:
        if not isinstance(items, list):
            return ""
        summaries = []
        for item in items[:3]:
            if not isinstance(item, dict):
                continue
            material = str(item.get("required_material") or "").strip()
            source = str(item.get("recommended_dispatch_source") or "").strip()
            distance = str(item.get("distance") or "").strip()
            eta = str(item.get("estimated_arrival_time") or "").strip()
            if not any((material, source, distance, eta)):
                continue
            summaries.append(self._join_brief([source, material, distance, eta], max_chars=90))
        return self._join_brief(summaries, max_chars=180)

    def _summarize_process_overview(self, items: Any) -> str:
        if not isinstance(items, list):
            return ""
        actions = [
            str(item.get("action") or "").strip()
            for item in items
            if isinstance(item, dict) and str(item.get("action") or "").strip()
        ]
        return self._join_brief(actions[:5], max_chars=180)

    def _summarize_risk_overview(self, items: Any) -> str:
        if not isinstance(items, list):
            return ""
        risks = []
        for item in items[:5]:
            if not isinstance(item, dict):
                continue
            risk = str(item.get("risk_description") or "").strip()
            measure = str(item.get("response_measure") or "").strip()
            if risk and measure:
                risks.append(f"{risk}，应对：{measure}")
            elif risk:
                risks.append(risk)
        return self._join_brief(risks, max_chars=180)

    def _build_overview_markdown(self, structured_sections: Dict[str, Dict[str, Any]]) -> str:
        overview = normalize_structured_sections(structured_sections).get("emergency_disposal_overview", {})
        fields = overview.get("fields_zh", {}) if isinstance(overview.get("fields_zh"), dict) else {}
        return "\n".join(
            [
                "### 应急处置总览",
                "",
                "以下内容用简短描述概括本次应急处置方案的关键点。",
                "",
                f"- **一、事件现场基本情况**：{fields.get('一、事件现场基本情况', '')}",
                f"- **二、预案匹配与组织预警和响应**：{fields.get('二、预案匹配与组织预警和响应', '')}",
                f"- **三、物资装备与调度**：{fields.get('三、物资装备与调度', '')}",
                f"- **四、处置流程建议**：{fields.get('四、处置流程建议', '')}",
                f"- **五、次生风险**：{fields.get('五、次生风险', '')}",
            ]
        )

    @staticmethod
    def _find_primary_plan_name(task_state: TaskState) -> str:
        for ref in task_state.knowledge_refs:
            if getattr(ref, "source_type", "") != "emergency_plan":
                continue
            title = str(getattr(ref, "title", "") or "").strip()
            if title:
                return f"《{title}》" if not title.startswith("《") else title
        return ""

    @staticmethod
    def _compose_warning_release(task_state: TaskState) -> str:
        level = task_state.incident_info.response_level or ""
        if "特别重大" in level or "I" in level:
            return "建议按特别重大级事件要求发布红色预警，具体发布主体和流程以对应预案为准"
        if "重大" in level or "II" in level:
            return "建议按重大级事件要求发布橙色预警，具体发布主体和流程以对应预案为准"
        if "较大" in level or "III" in level:
            return "建议按较大级事件要求发布黄色预警，具体发布主体和流程以对应预案为准"
        if "一般" in level or "IV" in level:
            return "建议按一般级事件要求发布蓝色或一般预警，具体发布主体和流程以对应预案为准"
        return ""

    @staticmethod
    def _compose_response_activation(event_level: str) -> str:
        if not event_level or event_level == "待现场确认":
            return ""
        return f"建议启动{event_level}应急响应"

    def _build_emergency_organization(
        self,
        task_state: TaskState,
        section_text: str,
    ) -> Dict[str, Any]:
        """构建“应急组织机构”固定字段。"""
        groups = self._extract_organization_groups(section_text)
        if not groups:
            groups = self._default_organization_groups(task_state)

        return {
            "section_name": "应急组织机构",
            "groups": groups,
            "fields_zh": {
                "应急组织机构": groups,
            },
        }

    def _build_material_equipment_dispatch(
        self,
        task_state: TaskState,
        section_text: str,
    ) -> Dict[str, Any]:
        """构建“物资装备与调度”固定字段。"""
        items = self._extract_material_dispatch_items(section_text)
        if not items:
            items = [
                item
                for resource in task_state.available_resources[:20]
                if (item := self._resource_to_dispatch_item(resource))
            ]
        if not items:
            items = [self._empty_material_dispatch_item()]
        zh_items = [self._map_item_keys(item, self._material_dispatch_key_map()) for item in items]

        return {
            "section_name": "物资装备与调度",
            "items": items,
            "fields_zh": {
                "物资装备与调度": zh_items,
            },
        }

    def _extract_material_dispatch_items(self, text: str) -> List[Dict[str, str]]:
        """从资源调度 Markdown 表格中抽取固定字段。"""
        rows = self._extract_markdown_table_rows(text)
        items: List[Dict[str, str]] = []

        for row in rows:
            required_material = self._row_value(
                row,
                (
                    "所需物资", "可调配物资", "可调配物资/队伍能力", "物资装备",
                    "能力需求", "资源名称",
                ),
            )
            source = self._row_value(
                row,
                (
                    "推荐调度来源", "调度来源", "资源名称", "现有来源",
                    "所属单位/出发地", "来源",
                ),
            )
            distance = self._row_value(row, ("距离", "距现场距离"))
            eta = self._row_value(row, ("预计到达时间", "预计到达", "到达时间"))
            location = self._row_value(row, ("地点、联系人信息", "所属单位/出发地", "地址", "出发地"))
            contact_name = self._row_value(row, ("联系人", "负责人"))
            phone = self._row_value(row, ("电话", "联系电话", "联系方式"))
            gap = self._row_value(row, ("资源缺口", "缺口", "主要缺口"))

            contact_info = location
            contact_parts = [part for part in (contact_name, phone) if part]
            if contact_parts:
                contact_info = "；".join([part for part in (contact_info, " / ".join(contact_parts)) if part])

            item = {
                "required_material": required_material,
                "recommended_dispatch_source": source,
                "distance": distance,
                "estimated_arrival_time": eta,
                "location_contact_info": contact_info,
                "resource_gap": gap,
            }
            if any(item.values()):
                items.append(item)

        return items

    def _resource_to_dispatch_item(self, resource: Dict[str, Any]) -> Dict[str, str]:
        """把 TaskState 中的资源记录转换为 API 固定字段。"""
        if not isinstance(resource, dict):
            return {}

        source_name = str(
            resource.get("name")
            or resource.get("warehouse_name")
            or resource.get("team_name")
            or ""
        ).strip()
        required_material = self._summarize_resource_materials(resource)
        distance = self._format_distance(resource.get("distance_km") or resource.get("distance"))
        eta = str(
            resource.get("estimated_arrival_time")
            or resource.get("estimated_arrival")
            or resource.get("eta")
            or resource.get("duration_min")
            or ""
        ).strip()
        if eta and eta.replace(".", "", 1).isdigit():
            eta = f"{eta}分钟"

        contact_info = self._resource_contact_info(resource)
        item = {
            "required_material": required_material,
            "recommended_dispatch_source": source_name,
            "distance": distance,
            "estimated_arrival_time": eta,
            "location_contact_info": contact_info,
            "resource_gap": "",
        }
        return item if any(item.values()) else {}

    @staticmethod
    def _empty_material_dispatch_item() -> Dict[str, str]:
        return {
            "required_material": "",
            "recommended_dispatch_source": "",
            "distance": "",
            "estimated_arrival_time": "",
            "location_contact_info": "",
            "resource_gap": "",
        }

    def _build_disposal_process_recommendations(self, section_text: str) -> Dict[str, Any]:
        """构建“处置流程建议”固定字段。"""
        items: List[Dict[str, str]] = []
        rows = self._extract_markdown_table_rows(section_text)

        for row in rows:
            sequence = self._row_value(row, ("序号", "编号"))
            action = (
                self._row_value(row, ("行动", "行动内容", "处置行动", "发布内容"))
                or self._compose_reporting_action(row)
            )
            responsible_unit = self._row_value(row, ("责任单位", "发布主体", "报送单位"))
            coordinating_unit = self._row_value(row, ("协同单位", "协作单位", "报送对象", "发布渠道"))
            reference_basis = self._row_value(row, ("引用依据", "预案/工具依据", "依据", "预案依据"))

            item = {
                "sequence": sequence,
                "action": action,
                "responsible_unit": responsible_unit,
                "coordinating_unit": coordinating_unit,
                "reference_basis": reference_basis,
            }
            if action or responsible_unit or coordinating_unit or reference_basis:
                items.append(item)

        if not items:
            items = [self._empty_disposal_process_item()]
        zh_items = [self._map_item_keys(item, self._disposal_process_key_map()) for item in items]

        return {
            "section_name": "处置流程建议",
            "items": items,
            "fields_zh": {
                "处置流程建议": zh_items,
            },
        }

    def _build_secondary_risks(self, section_text: str) -> Dict[str, Any]:
        """构建“次生风险”固定字段。"""
        items: List[Dict[str, str]] = []
        rows = self._extract_markdown_table_rows(section_text)

        for row in rows:
            item = {
                "trigger_condition": self._row_value(row, ("触发条件", "触发场景")),
                "risk_description": self._row_value(row, ("风险描述", "风险", "次生风险")),
                "impact_consequence": self._row_value(row, ("影响后果", "后果")),
                "response_measure": self._row_value(row, ("应对措施", "处置措施", "管控措施")),
                "responsible_unit": self._row_value(row, ("责任单位", "牵头单位")),
            }
            if any(item.values()):
                items.append(item)

        if not items:
            items = [self._empty_secondary_risk_item()]
        zh_items = [self._map_item_keys(item, self._secondary_risk_key_map()) for item in items]

        return {
            "section_name": "次生风险",
            "items": items,
            "fields_zh": {
                "次生风险": zh_items,
            },
        }

    def _build_reference_basis(
        self,
        task_state: TaskState,
        section_text: str,
    ) -> Dict[str, Any]:
        """构建“引用依据”固定字段。"""
        references: List[Dict[str, str]] = []
        rows = self._extract_markdown_table_rows(section_text)

        for row in rows:
            item = {
                "basis_type": self._row_value(row, ("依据类型", "类型")),
                "basis_name": self._row_value(row, ("依据名称", "预案名称", "工具结果", "案例")),
                "reference_chapter": self._row_value(row, ("引用章节/模块", "引用章节", "章节/模块", "模块")),
                "reference_content": self._row_value(row, ("引用内容摘要", "引用内容", "内容摘要")),
                "supports_decision": self._row_value(row, ("支撑决策", "支撑", "用途")),
            }
            if any(item.values()):
                references.append(item)

        if not references:
            references = [self._knowledge_ref_to_reference_item(ref) for ref in task_state.knowledge_refs[:20]]
            references = [item for item in references if any(item.values())]
        if not references:
            references = [self._empty_reference_item()]
        zh_references = [self._map_item_keys(item, self._reference_key_map()) for item in references]

        return {
            "section_name": "引用依据",
            "references": references,
            "fields_zh": {
                "引用依据": zh_references,
            },
        }

    @staticmethod
    def _map_item_keys(item: Dict[str, str], key_map: Dict[str, str]) -> Dict[str, str]:
        return {zh_key: str(item.get(en_key, "") or "") for en_key, zh_key in key_map.items()}

    @staticmethod
    def _material_dispatch_key_map() -> Dict[str, str]:
        return {
            "required_material": "所需物资",
            "recommended_dispatch_source": "推荐调度来源",
            "distance": "距离",
            "estimated_arrival_time": "预计到达时间",
            "location_contact_info": "地点、联系人信息",
            "resource_gap": "资源缺口",
        }

    @staticmethod
    def _disposal_process_key_map() -> Dict[str, str]:
        return {
            "sequence": "序号",
            "action": "行动",
            "responsible_unit": "责任单位",
            "coordinating_unit": "协同单位",
            "reference_basis": "引用依据",
        }

    @staticmethod
    def _secondary_risk_key_map() -> Dict[str, str]:
        return {
            "trigger_condition": "触发条件",
            "risk_description": "风险描述",
            "impact_consequence": "影响后果",
            "response_measure": "应对措施",
            "responsible_unit": "责任单位",
        }

    @staticmethod
    def _reference_key_map() -> Dict[str, str]:
        return {
            "basis_type": "依据类型",
            "basis_name": "依据名称",
            "reference_chapter": "引用章节/模块",
            "reference_content": "引用内容摘要",
            "supports_decision": "支撑决策",
        }

    @staticmethod
    def _empty_disposal_process_item() -> Dict[str, str]:
        return {
            "sequence": "",
            "action": "",
            "responsible_unit": "",
            "coordinating_unit": "",
            "reference_basis": "",
        }

    @staticmethod
    def _empty_secondary_risk_item() -> Dict[str, str]:
        return {
            "trigger_condition": "",
            "risk_description": "",
            "impact_consequence": "",
            "response_measure": "",
            "responsible_unit": "",
        }

    @staticmethod
    def _empty_reference_item() -> Dict[str, str]:
        return {
            "basis_type": "",
            "basis_name": "",
            "reference_chapter": "",
            "reference_content": "",
            "supports_decision": "",
        }

    def _knowledge_ref_to_reference_item(self, ref: Any) -> Dict[str, str]:
        metadata = getattr(ref, "metadata", {}) or {}
        return {
            "basis_type": str(getattr(ref, "source_type", "") or ""),
            "basis_name": str(getattr(ref, "title", "") or ""),
            "reference_chapter": str(metadata.get("module") or metadata.get("section") or metadata.get("chapter") or ""),
            "reference_content": self._limit_text(str(getattr(ref, "excerpt", "") or ""), 500),
            "supports_decision": "",
        }

    @staticmethod
    def _compose_reporting_action(row: Dict[str, str]) -> str:
        report_type = str(row.get("报送类型") or row.get("发布类型") or "").strip()
        content = str(row.get("发布内容") or row.get("方式") or row.get("时限") or "").strip()
        if report_type and content:
            return f"{report_type}：{content}"
        return report_type

    def _summarize_resource_materials(self, resource: Dict[str, Any]) -> str:
        if resource.get("type") == "expert" or resource.get("resource_type") == "expert":
            specialty = resource.get("specialty_field") or resource.get("specialty") or ""
            return f"专家技术支持（{specialty}）" if specialty else "专家技术支持"

        materials = resource.get("materials_summary_zh") or resource.get("materials_by_category") or {}
        parts: List[str] = []
        if isinstance(materials, dict):
            for category, entries in materials.items():
                if category == "team_size":
                    continue
                if isinstance(entries, list):
                    for entry in entries[:6]:
                        if not isinstance(entry, dict):
                            continue
                        name = str(entry.get("name") or "").strip()
                        quantity = entry.get("quantity")
                        unit = str(entry.get("unit") or "").strip()
                        if not name:
                            continue
                        amount = ""
                        if quantity not in (None, ""):
                            amount = f"×{quantity}{unit}"
                        parts.append(f"{name}{amount}")
                elif entries:
                    parts.append(f"{category}: {entries}")

        specialties = resource.get("specialties")
        if specialties:
            parts.append("队伍能力：" + "、".join(str(item) for item in specialties))
        if resource.get("team_size"):
            parts.append(f"队伍规模：{resource.get('team_size')}人")
        if not parts and resource.get("categories_zh"):
            parts.append("、".join(str(item) for item in resource.get("categories_zh", [])))

        return "；".join(parts[:12])

    @staticmethod
    def _resource_contact_info(resource: Dict[str, Any]) -> str:
        address = str(resource.get("address") or resource.get("source_org") or resource.get("belong_org_name") or "").strip()
        contact = resource.get("contact") if isinstance(resource.get("contact"), dict) else {}
        contact_name = str(
            contact.get("name")
            or resource.get("principal")
            or resource.get("contact_name")
            or ""
        ).strip()
        phone = str(
            contact.get("phone")
            or resource.get("contact_phone")
            or resource.get("phone")
            or ""
        ).strip()
        contact_parts = [part for part in (contact_name, phone) if part]
        return "；".join([part for part in (address, " / ".join(contact_parts)) if part])

    @staticmethod
    def _format_distance(distance: Any) -> str:
        if distance in (None, ""):
            return ""
        if isinstance(distance, (int, float)):
            return f"{distance:.2f}km"
        distance_text = str(distance).strip()
        if not distance_text:
            return ""
        if distance_text.endswith(("km", "公里", "米", "m")):
            return distance_text
        return f"{distance_text}km"

    def _extract_organization_groups(self, text: str) -> List[Dict[str, str]]:
        """从 Markdown 表格中抽取工作组、牵头单位、主要职责。"""
        rows = self._extract_markdown_table_rows(text)
        groups: List[Dict[str, str]] = []

        for row in rows:
            normalized = {key.strip(): value.strip() for key, value in row.items()}
            group_name = (
                normalized.get("工作组")
                or normalized.get("组织机构")
                or normalized.get("小组")
                or normalized.get("组别")
                or ""
            )
            lead_unit = (
                normalized.get("牵头单位")
                or normalized.get("牵头单位/人员")
                or normalized.get("牵头部门")
                or normalized.get("责任单位")
                or ""
            )
            responsibility = (
                normalized.get("主要职责")
                or normalized.get("职责")
                or normalized.get("工作职责")
                or ""
            )

            if not group_name or not responsibility:
                continue
            if group_name in {"总指挥", "副总指挥"}:
                continue

            groups.append(
                {
                    "work_group": group_name,
                    "lead_unit": lead_unit or "待现场确认",
                    "main_responsibilities": responsibility,
                }
            )

        return self._ensure_required_organization_groups(groups)

    def _extract_markdown_table_rows(self, text: str) -> List[Dict[str, str]]:
        """解析简单 Markdown 表格，返回表头到单元格的映射。"""
        rows: List[Dict[str, str]] = []
        lines = [line.strip() for line in (text or "").splitlines()]
        index = 0
        while index < len(lines) - 1:
            header_line = lines[index]
            separator_line = lines[index + 1]
            if not self._is_markdown_table_row(header_line) or not self._is_markdown_separator_row(separator_line):
                index += 1
                continue

            headers = self._split_markdown_table_row(header_line)
            index += 2
            while index < len(lines) and self._is_markdown_table_row(lines[index]):
                cells = self._split_markdown_table_row(lines[index])
                if cells and len(cells) >= len(headers):
                    rows.append({headers[pos]: cells[pos] for pos in range(len(headers))})
                index += 1
        return rows

    @staticmethod
    def _is_markdown_table_row(line: str) -> bool:
        return line.startswith("|") and line.endswith("|") and line.count("|") >= 2

    @staticmethod
    def _is_markdown_separator_row(line: str) -> bool:
        if not line.startswith("|") or not line.endswith("|"):
            return False
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells)

    @staticmethod
    def _split_markdown_table_row(line: str) -> List[str]:
        return [re.sub(r"\s+", " ", cell).strip() for cell in line.strip().strip("|").split("|")]

    @staticmethod
    def _row_value(row: Dict[str, str], labels: tuple[str, ...]) -> str:
        """从一行 Markdown 表格映射中按多个候选列名取值。"""
        normalized = {str(key).strip(): str(value).strip() for key, value in (row or {}).items()}
        for label in labels:
            value = normalized.get(label)
            if value:
                return value
        for key, value in normalized.items():
            if any(label in key for label in labels) and value:
                return value
        return ""

    def _ensure_required_organization_groups(self, groups: List[Dict[str, str]]) -> List[Dict[str, str]]:
        required_defaults = self._default_organization_groups()
        existing_names = {item.get("work_group", "") for item in groups}
        for item in required_defaults:
            if item["work_group"] not in existing_names:
                groups.append(item)
        return groups

    @staticmethod
    def _default_organization_groups(task_state: TaskState | None = None) -> List[Dict[str, str]]:
        return [
            {
                "work_group": "现场指挥组",
                "lead_unit": "属地政府或现场应急指挥部",
                "main_responsibilities": "统一指挥现场处置，研判态势，统筹警戒、救援、清障、医疗、信息发布等工作。",
            },
            {
                "work_group": "综合协调组",
                "lead_unit": "交通运输主管部门或应急管理部门",
                "main_responsibilities": "负责信息汇总、部门协调、资源调度、会商组织和指令流转。",
            },
            {
                "work_group": "抢险处置组",
                "lead_unit": "消防救援部门、交通养护或运营单位",
                "main_responsibilities": "负责人员搜救、现场排险、车辆清障、道路抢通和次生风险控制。",
            },
            {
                "work_group": "医疗救护组",
                "lead_unit": "卫生健康部门或属地医疗机构",
                "main_responsibilities": "负责伤员检伤分类、现场急救、转运衔接和医疗资源协调。",
            },
            {
                "work_group": "后勤保障组",
                "lead_unit": "属地政府、交通运输主管部门",
                "main_responsibilities": "负责物资保障、装备补给、通信照明、人员饮水餐食和临时安置保障。",
            },
            {
                "work_group": "信息发布组",
                "lead_unit": "宣传部门或指挥部授权单位",
                "main_responsibilities": "负责信息报送、新闻发布、舆情监测、公众提示和统一回应口径。",
            },
            {
                "work_group": "专家组",
                "lead_unit": "指挥部办公室或行业主管部门",
                "main_responsibilities": "负责专业研判、技术咨询、风险评估和处置措施优化建议。",
            },
        ]

    @staticmethod
    def _extract_markdown_field(text: str, labels: tuple[str, ...]) -> str:
        """从 Markdown 表格或冒号行里提取指定字段。"""
        if not text:
            return ""

        for label in labels:
            table_pattern = re.compile(
                rf"\|\s*{re.escape(label)}\s*\|\s*(.*?)\s*\|",
                re.IGNORECASE,
            )
            match = table_pattern.search(text)
            if match:
                value = re.sub(r"\s+", " ", match.group(1)).strip()
                if value and not re.fullmatch(r"-+", value):
                    return value

            line_pattern = re.compile(
                rf"(?:^|\n)\s*(?:[-*]\s*)?\*{{0,2}}{re.escape(label)}\*{{0,2}}\s*[：:]\s*(.+)",
                re.IGNORECASE,
            )
            match = line_pattern.search(text)
            if match:
                value = re.sub(r"\s+", " ", match.group(1)).strip().strip("|")
                if value:
                    return value

        return ""

    @staticmethod
    def _format_weather_condition(weather: Dict[str, Any]) -> str:
        if not isinstance(weather, dict) or not weather:
            return ""
        if weather.get("status") == "error":
            return ""

        parts = []
        if weather.get("weather"):
            parts.append(str(weather["weather"]))
        if weather.get("temperature"):
            parts.append(str(weather["temperature"]))
        if weather.get("wind_direction") or weather.get("wind_power"):
            wind = "".join(
                str(item)
                for item in (weather.get("wind_direction"), weather.get("wind_power"))
                if item not in (None, "")
            )
            if wind:
                parts.append(f"{wind}风")
        if weather.get("humidity"):
            parts.append(f"湿度{weather['humidity']}")

        if not parts and weather.get("message"):
            return str(weather["message"])
        return "，".join(parts)

    @staticmethod
    def _format_surrounding_environment(pois: List[Dict[str, Any]]) -> str:
        if not pois:
            return ""

        names = []
        sensitive_keywords = ("医院", "学校", "居民", "小区", "幼儿园", "加油站", "商场", "市场", "车站", "收费站")
        for poi in pois:
            name = str(poi.get("name") or "").strip()
            poi_type = str(poi.get("type") or poi.get("typecode") or "").strip()
            if not name:
                continue
            if any(keyword in name or keyword in poi_type for keyword in sensitive_keywords):
                names.append(name)
            if len(names) >= 5:
                break

        if not names:
            names = [str(poi.get("name") or "").strip() for poi in pois[:5] if poi.get("name")]

        return "周边包含：" + "、".join(names) if names else ""

    @staticmethod
    def _compose_event_summary(task_state: TaskState) -> str:
        incident = task_state.incident_info
        parts = []
        if incident.incident_type:
            parts.append(f"现场发生{incident.incident_type}")
        if incident.vehicles_involved:
            parts.append(f"涉及{incident.vehicles_involved}")
        if incident.casualty_status:
            parts.append(f"伤亡情况为{incident.casualty_status}")
        elif incident.casualties:
            parts.append(f"伤亡情况为{incident.casualties}")
        if incident.scene_status:
            parts.append(f"现场状态为{incident.scene_status}")
        return "，".join(parts)

    @staticmethod
    def _compose_main_impact(task_state: TaskState) -> str:
        incident = task_state.incident_info
        environment = task_state.environment_info
        impacts = []

        if incident.scene_status:
            impacts.append(incident.scene_status)
        if incident.road_info:
            impacts.append(incident.road_info)
        traffic = environment.traffic if isinstance(environment.traffic, dict) else {}
        traffic_desc = (
            traffic.get("description")
            or (traffic.get("evaluation") or {}).get("status_desc")
            or traffic.get("message")
        )
        if traffic_desc:
            impacts.append(str(traffic_desc))
        if incident.casualty_status or incident.casualties:
            impacts.append("可能引发人员聚集、交通拥堵和次生事故风险")

        return "；".join(str(item) for item in impacts if item)

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
        overview_text = section_texts.get("应急处置总览", "").strip()
        if overview_text:
            lines.append(overview_text)
            lines.append("")
        for spec in SECTION_SPECS:
            text = section_texts.get(spec.title, "").strip()
            if not text:
                text = f"### {spec.title}\n\n[待补充]"
            lines.append(text)
            lines.append("")
        return "\n".join(lines).strip()

    def _build_section_error_placeholder(
        self,
        spec: SectionSpec,
        error: Exception,
        previous_draft: str = "",
    ) -> str:
        """章节生成失败时写入可展示、可审核的错误占位，避免整稿完全中断。"""
        lines = [
            f"### {spec.title}",
            "",
            "[本章节生成失败，需重新生成或人工补充]",
            "",
            f"- 失败原因：{type(error).__name__}: {error}",
            f"- 本章节最低字数要求：{spec.min_chars}",
            f"- 本章节必含信息：{'、'.join(spec.required_terms)}",
            "- 处理建议：检查模型调用、上下文长度、网关返回和章节审核日志后重试。",
        ]
        if previous_draft:
            lines.extend(
                [
                    "",
                    "#### 上一版草稿摘要",
                    "",
                    self._limit_text(previous_draft, 3000),
                ]
            )
        return "\n".join(lines)

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
