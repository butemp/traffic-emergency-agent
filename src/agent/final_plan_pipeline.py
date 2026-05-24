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
        key="event_situation",
        title="一、事件现场基本情况",
        filename="01_event_situation.md",
        min_chars=200,
        required_terms=(
            "事件现场基本情况", "事件地点", "天气情况", "事件简述", "周边环境", "主要影响",
        ),
        instructions=(
            "输出固定字段表，表头列必须是：字段、内容。字段行依次必须包含："
            "事件地点、天气情况、事件简述、周边环境、主要影响。"
            "这 5 个字段会被 API 结构化提取，名称不能改写。不要添加其他子表（如'事件基础信息'等）或额外字段。"
            "本章只用这一张表，整章保持精简。"
        ),
        example=(
            "### 一、事件现场基本情况\n"
            "\n"
            "| 字段 | 内容 |\n"
            "| --- | --- |\n"
            "| 事件地点 | G72泉南高速K85公里处（柳州往南宁方向） |\n"
            "| 天气情况 | 中雨，气温22℃，能见度约500米，可能影响现场通行和救援效率 |\n"
            "| 事件简述 | 现场发生多车追尾事故，涉及1辆重型半挂车和2辆小型客车，3人被困、2人受伤 |\n"
            "| 周边环境 | 附近有收费站、服务区、居民点和高速主线车流等敏感点 |\n"
            "| 主要影响 | 可能造成交通拥堵、人员聚集、燃油泄漏、二次碰撞等次生风险 |\n"
        ),
    ),
    SectionSpec(
        key="plan_response",
        title="二、预案匹配与组织预警和响应",
        filename="02_plan_warning_response.md",
        min_chars=200,
        required_terms=(
            "预案匹配与组织预警和响应", "匹配预案", "事件等级", "预警发布", "启动响应", "判断依据",
        ),
        instructions=(
            "输出固定字段表，表头列必须是：字段、内容。字段行依次必须包含："
            "匹配预案、事件等级、预警发布、启动响应、判断依据。"
            "这 5 个字段会被 API 结构化提取，名称不能改写。"
            "本章是原'响应定级'和'预警发布'两章的合并，整章只用这一张表，不要添加'补充说明'/'预警渠道'/'对外发布文本'等额外子表。"
        ),
        example=(
            "### 二、预案匹配与组织预警和响应\n"
            "\n"
            "| 字段 | 内容 |\n"
            "| --- | --- |\n"
            "| 匹配预案 | 《广西壮族自治区公路水运工程生产安全事故应急预案》 |\n"
            "| 事件等级 | 重大级（Ⅱ级） |\n"
            "| 预警发布 | 建议由自治区交通运输厅领导小组按Ⅱ级预警要求发布预警信息，通过电视、广播、政府网站、新媒体提示相关单位做好防御 |\n"
            "| 启动响应 | 建议启动重大级（Ⅱ级）应急响应，由领导小组研判同意后启动并报自治区人民政府和交通运输部 |\n"
            "| 判断依据 | 依据《广西壮族自治区公路水运工程生产安全事故应急预案》附件2分级标准：事件造成10人以上死亡，符合Ⅱ级响应条件 |\n"
        ),
    ),
    SectionSpec(
        key="emergency_organization",
        title="三、应急组织机构",
        filename="03_emergency_organization.md",
        min_chars=350,
        required_terms=(
            "应急组织机构", "工作组", "牵头单位", "主要职责",
            "现场指挥组", "综合协调组", "抢险处置组", "医疗救护组",
            "后勤保障组", "信息发布组", "专家组",
        ),
        instructions=(
            "输出固定表格，表头列必须是：工作组、牵头单位、主要职责。"
            "工作组至少包含 7 个：现场指挥组、综合协调组、抢险处置组、医疗救护组、后勤保障组、信息发布组、专家组。"
            "字段名称不能改写。"
            "如证据包中有专家信息，在表格后追加一段 **专家库支持**（注意：本段标题就是'**专家库支持**'四个字，**禁止加任何来源说明**，如'依据 search_experts 候选名单'/'根据专家检索结果'等措辞都不要写），"
            "逐人列出 姓名（单位）：专业方向 · 联系电话 — 建议支持方式。**联系电话必须填写**（来自证据包中专家记录的 phone 字段），不能省略或留空。"
            "本章只保留组织机构表 + 可选专家名单，不要其他子表。"
        ),
        example=(
            "### 三、应急组织机构\n"
            "\n"
            "| 工作组 | 牵头单位 | 主要职责 |\n"
            "| --- | --- | --- |\n"
            "| 现场指挥组 | 属地政府或现场应急指挥部 | 统一指挥现场处置，研判态势，统筹警戒、救援、清障、医疗、信息发布等工作 |\n"
            "| 综合协调组 | 交通运输主管部门或应急管理部门 | 信息汇总、部门协调、资源调度、会商组织和指令流转 |\n"
            "| 抢险处置组 | 消防救援部门、交通养护或运营单位 | 人员搜救、现场排险、车辆清障、道路抢通和次生风险控制 |\n"
            "| 医疗救护组 | 卫生健康部门或属地医疗机构 | 伤员检伤分类、现场急救、转运衔接和医疗资源协调 |\n"
            "| 后勤保障组 | 属地政府、交通运输主管部门 | 物资保障、装备补给、通信照明、人员饮水餐食和临时安置 |\n"
            "| 信息发布组 | 宣传部门或指挥部授权单位 | 信息报送、新闻发布、舆情监测、公众提示和统一回应口径 |\n"
            "| 专家组 | 指挥部办公室或行业主管部门 | 专业研判、技术咨询、风险评估和处置措施优化建议 |\n"
            "\n"
            "**专家库支持**：\n"
            "\n"
            "- 廖俊锋（广西交通安全研究中心）：应急管理、安全管理 · 联系电话 13900100001 — 建议由指挥部办公室或值班人员人工联系参与远程会商或现场技术支持\n"
            "- 郑屈（广西交通安全研究中心）：安全应急管理 · 联系电话 13900100002 — 建议人工联系参与技术支持\n"
            "- 林静（南宁轨道交通集团有限责任公司）：轨道交通安全质量监管 · 联系电话 13900100003 — 建议人工联系参与技术支持\n"
        ),
    ),
    SectionSpec(
        key="material_dispatch",
        title="四、物资装备与调度",
        filename="04_material_dispatch.md",
        min_chars=250,
        required_terms=(
            "物资装备与调度", "所需物资", "推荐调度来源", "距离", "预计到达时间", "地点、联系人信息", "资源缺口",
        ),
        instructions=(
            "输出固定表格，表头列必须是：所需物资、推荐调度来源、距离、预计到达时间、地点、联系人信息、资源缺口。"
            "这 6 个字段会被 API 结构化提取，列名不能改写（'地点、联系人信息' 是一列，中间的'、'是列名的一部分）。"
            "每行一类资源/能力，**必须基于 search_emergency_resources / optimize_dispatch_plan 实际返回的仓库或队伍数据填充**："
            "  - '推荐调度来源' 填仓库/队伍名称；'地点、联系人信息' 填地址+负责人+电话；'距离'填实际距离；'预计到达时间'按距离估算（30km/h 约等于每 2 分钟 1km）；"
            "  - 资源缺口列：搜到对应类别就写'无'，没搜到才写具体缺口（如'缺消防破拆装备'）。"
            "**禁止整行全是'暂未获取'/'待现场确认'/'待人工确认'**。如果 evidence 里 search_emergency_resources 真的没返回任何资源，整张表只输出表头加一行说明'evidence 中无内部资源数据，需人工现场调度'即可，不要凑占位行。"
            "不能编造仓库名、电话、物资。"
            "本章是原'六、资源调度方案'的简化版，不要分梯队子表、不要'关键物资用途说明'、不要'资源覆盖与缺口分析'，整章只用这一张表。"
        ),
        example=(
            "### 四、物资装备与调度\n"
            "\n"
            "| 所需物资 | 推荐调度来源 | 距离 | 预计到达时间 | 地点、联系人信息 | 资源缺口 |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| 路锥、标志牌、爆闪灯等警示防护物资 | 北海应急仓库 | 1.76km | 5分钟 | 广西新发展交通集团有限公司南宁高速公路运营分公司；黄世鹏 / 13978923335 | 无 |\n"
            "| 拖车、清障人员等清障救援能力 | 北海运营分公司应急抢险队伍 | 1.76km | 5分钟 | 广西北海市合浦县廉州镇G7212柳北高速；吴承远 / 13607892598 | 无 |\n"
            "| 养护抢险车辆装备等道路抢通能力 | 广西北投交通养护科技集团合浦养护应急队 | 2.71km | 8分钟 | 广西北投交通养护科技集团沿海项目部；李照强 / 13978912640 | 无 |\n"
            "| 反光背心、爆闪灯、照明灯等夜间作业物资 | 公馆工区应急仓库 | 37.34km | 25分钟 | 广西北海市合浦县公馆镇公馆收费站；范先学 / 13607890157 | 无 |\n"
            "| 液压破拆、专业搜救、救护车等专业救援能力 | 消防救援部门、卫生健康部门 | 待协调 | 待协调 | 由属地指挥部联系当地消防/120 | 内部资源暂未覆盖，需外部协同 |\n"
        ),
    ),
    SectionSpec(
        key="disposal_process",
        title="五、处置流程建议（包括后期处置、新闻发布）",
        filename="05_disposal_process.md",
        min_chars=350,
        required_terms=(
            "处置流程建议", "序号", "行动", "责任单位", "协同单位", "引用依据",
            "现场警戒", "二次排查", "新闻发布",
        ),
        instructions=(
            "输出固定表格，表头列必须是：序号、行动、责任单位、协同单位、引用依据。"
            "这 5 个字段会被 API 结构化提取，列名不能改写。"
            "至少 10 行，覆盖：现场警戒与交通管制、伤员排查与救治、涉险人员二次排查、家属联络与安抚、"
            "二次事故防范、清障与道路恢复、信息报送（初报/续报/终报）、新闻发布、舆情监测与回应、总结评估。"
            "引用依据列必须填 get_emergency_plan 返回的 hit_path（如 '应急响应.处置措施.Ⅱ级应急响应处置措施' "
            "或 '后期处置.善后处置.抚恤和补助'），精确到原文档章节路径。"
            "本章是原'处置行动方案'和'信息报送与新闻发布'两章的合并，不要拆成三阶段子表、不要单独的报送/发布子表，整章只用这一张表。"
        ),
        example=(
            "### 五、处置流程建议（包括后期处置、新闻发布）\n"
            "\n"
            "| 序号 | 行动 | 责任单位 | 协同单位 | 引用依据 |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| 1 | 现场警戒与交通管制，设置警示防护设备，防止二次事故 | 合浦县公安局交通管理大队 | 合浦县交通运输局、消防救援大队 | 应急响应.处置措施.Ⅱ级应急响应处置措施 |\n"
            "| 2 | 伤员排查与急救，对现场受伤人员进行检伤分类和初步救治 | 合浦县卫生健康局 | 合浦县公安局、消防救援大队 | 应急响应.处置措施.Ⅱ级应急响应处置措施 |\n"
            "| 3 | 涉险人员二次排查，扩大搜索范围确认无遗漏伤亡 | 合浦县消防救援大队 | 合浦县公安局、医疗救援机构 | 应急响应.处置措施.Ⅱ级应急响应处置措施 |\n"
            "| 4 | 家属联络与安抚，及时通报伤亡情况，提供心理支持 | 合浦县民政局 | 合浦县公安局、卫生健康局 | 后期处置.善后处置.抚恤和补助 |\n"
            "| 5 | 二次事故防范，使用锥桶等警示防护设备设置警戒区 | 合浦县公安局交通管理大队 | 合浦县交通运输局 | 应急响应.处置措施.Ⅱ级应急响应处置措施 |\n"
            "| 6 | 清障与道路恢复，调用拖车清理事故现场，逐步解除交通管制 | 合浦县公路养护中心 | 合浦县公安局、交通运输局 | 应急响应.处置措施.Ⅱ级应急响应处置措施 |\n"
            "| 7 | 信息初报，15分钟内电话/短信向县政府和市交通运输局报告事故基本情况 | 合浦县交通运输局 | 合浦县人民政府办公室 | 应急响应.信息报送 |\n"
            "| 8 | 信息续报，50分钟内以书面材料报送事件处置新进展 | 合浦县交通运输局 | 合浦县人民政府办公室 | 应急响应.信息报送 |\n"
            "| 9 | 新闻发布，对外发布事故基本情况、救援进展和交通绕行提示 | 合浦县委宣传部 | 合浦县交通运输局、公安局 | 应急响应.新闻发布 |\n"
            "| 10 | 舆情监测与回应，每30分钟汇总网络舆情，澄清不实信息 | 合浦县委宣传部 | 合浦县交通运输局 | 应急响应.新闻发布 |\n"
            "| 11 | 信息终报，事故处置完毕后24小时内形成完整报告 | 合浦县交通运输局 | 合浦县人民政府办公室 | 应急响应.信息报送 |\n"
            "| 12 | 总结评估，开展事故处置情况评估并报上一级应急指挥机构 | 合浦县交通运输局 | 合浦县人民政府 | 后期处置.总结评估 |\n"
        ),
    ),
    SectionSpec(
        key="secondary_risks",
        title="六、次生风险",
        filename="06_secondary_risks.md",
        min_chars=250,
        required_terms=(
            "次生风险", "触发条件", "风险描述", "影响后果", "应对措施", "责任单位",
        ),
        instructions=(
            "输出固定表格，表头列必须是：触发条件、风险描述、影响后果、应对措施、责任单位。"
            "这 5 个字段会被 API 结构化提取，列名不能改写。"
            "至少 5 条，建议 6-8 条，覆盖：二次事故、现场作业安全、伤员漏查、拥堵外溢、家属安抚、舆情扩散、资源不足等方向。"
            "应对措施要具体到动作（如'在事故上游设置渐变式警戒区+锥桶渠化+爆闪灯'），不要写空泛的'加强管理'。"
            "本章是原'风险提示与注意事项'的简化版，不要分'安全/处置/衍生风险'三类子表，整章只用这一张表，"
            "也不要'监测指标''升级条件'这两列，只保留 5 列。"
        ),
        example=(
            "### 六、次生风险\n"
            "\n"
            "| 触发条件 | 风险描述 | 影响后果 | 应对措施 | 责任单位 |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| 能见度低于500米且车辆未及时减速 | 雾天能见度低，增加二次事故风险 | 可能造成更多人员伤亡和财产损失 | 在事故上游设置渐变式警戒区，使用交通锥进行渠化，并部署爆闪灯增强警示 | 合浦县公安交管部门 |\n"
            "| 救援人员未正确穿戴反光背心、安全帽等个人防护用品 | 现场作业人员未佩戴防护装备，存在安全隐患 | 救援人员受伤，影响救援效率 | 检查所有作业人员防护装备佩戴情况，确保反光背心、安全帽等正确使用 | 合浦县公安交管部门 |\n"
            "| 救援人员未对周边进行二次排查 | 现场遗漏受伤人员，未能及时救治 | 延误救治，加重伤亡 | 由医疗组组织对周边人员二次检伤登记，扩大搜索范围 | 合浦县卫生健康部门 |\n"
            "| 交通管制措施不合理或执行不到位 | 现场交通疏导不当，引发周边道路拥堵 | 影响区域交通秩序，延长救援时间 | 实时监测周边路况，优化交通组织，使用交通锥进行有效渠化 | 合浦县公安交管部门 |\n"
            "| 信息沟通不畅，安抚措施不到位 | 家属情绪激动，可能引发群体性事件 | 可能影响社会稳定和舆情 | 建立家属安抚机制，及时沟通事故信息，提供心理支持 | 合浦县应急管理部门 |\n"
            "| 官方信息发布不及时 | 事故信息不透明，引发网络谣言扩散 | 造成社会恐慌，影响政府公信力 | 由舆情组每30分钟汇总网络舆情，准备新闻发布材料 | 合浦县委宣传部 |\n"
            "| 应急仓库物资未及时调配 | 资源调度延迟，影响应急响应效率 | 延误现场处置，扩大事故影响 | 立即调度公馆工区应急仓库资源，如交通锥、照明灯等，确保快速到达 | 合浦县交通运输主管部门 |\n"
        ),
    ),
    SectionSpec(
        key="references",
        title="七、引用依据",
        filename="07_references.md",
        min_chars=200,
        required_terms=("引用依据", "依据类型", "依据名称", "引用章节", "引用内容", "支撑决策"),
        instructions=(
            "输出固定表格，表头列必须是：依据类型、依据名称、引用章节/模块、引用内容摘要、支撑决策。"
            "这 5 个字段会被 API 结构化提取，列名不能改写。"
            "引用章节/模块列必须填精确的中文章节路径（如 "
            "'应急响应.处置措施.Ⅱ级应急响应处置措施' 或 '附件.附件2 公路水运工程生产安全事故响应分级和启动条件'），"
            "精确到原文档章节，不要写成笼统的'第X节'或'附件X'。"
            "汇总预案、法规/RAG、工具结果、案例等所有依据。"
            "**依据名称列只能写中文人话**，不要出现任何英文工具名或内部代号"
            "（禁用示例：evaluate_incident_severity / search_emergency_resources / search_experts / geocode / get_emergency_plan / gaode 等），"
            "应翻译成中文功能名（参见示例中的'事件等级评估'/'应急资源调度搜索'/'应急专家匹配'/'地理编码与气象信息'）。"
        ),
        example=(
            "### 七、引用依据\n"
            "\n"
            "| 依据类型 | 依据名称 | 引用章节/模块 | 引用内容摘要 | 支撑决策 |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| 应急预案 | 《广西壮族自治区公路水运工程生产安全事故应急预案》 | 附件.附件2 公路水运工程生产安全事故响应分级和启动条件 | Ⅱ级（重大）：造成10-30人死亡或5000万-1亿元损失 | 事件等级判定为Ⅱ级 |\n"
            "| 应急预案 | 《广西壮族自治区公路水运工程生产安全事故应急预案》 | 组织体系.自治区应急指挥机构.领导小组 | 领导小组统一领导Ⅱ级事故应急处置 | 应急组织机构-总指挥设置 |\n"
            "| 应急预案 | 《广西壮族自治区公路水运工程生产安全事故应急预案》 | 组织体系.自治区应急指挥机构.应急工作组 | 综合协调组、应急指挥组、新闻宣传组、通信保障组、后勤保障组共5个工作组 | 应急组织机构-工作组配置 |\n"
            "| 应急预案 | 《广西壮族自治区公路水运工程生产安全事故应急预案》 | 应急响应.处置措施.Ⅱ级应急响应处置措施 | 24小时值班+派现场工作组+协调专业救援队伍 | 处置流程建议主体动作 |\n"
            "| 应急预案 | 《广西壮族自治区公路水运工程生产安全事故应急预案》 | 预防与预警.预警启动 | Ⅱ级预警由领导小组研判后启动并报自治区人民政府 | 预警发布主体与流程 |\n"
            "| 应急预案 | 《广西壮族自治区公路水运工程生产安全事故应急预案》 | 应急响应.信息报送 | 项目负责人15分钟内电话上报、50分钟内书面 | 处置流程建议-信息报送 |\n"
            "| 应急预案 | 《广西壮族自治区公路水运工程生产安全事故应急预案》 | 后期处置.善后处置.抚恤和补助 | 应急处置人员致病致残死亡按国家规定补助抚恤 | 次生风险-人员保障措施 |\n"
            "| 工具结果 | 事件等级评估 | 事件定级 | 判定为重大级（Ⅱ级），置信度0.85 | 事件等级判定 |\n"
            "| 工具结果 | 应急资源调度搜索 | 资源搜索 | 搜索到5个仓库/队伍，覆盖警示防护、清障救援、夜间作业等能力 | 物资装备与调度填充 |\n"
            "| 工具结果 | 应急专家匹配 | 专家检索 | 匹配5位专家，涵盖应急管理、安全生产、轨道交通等方向 | 应急组织机构-专家库支持 |\n"
            "| 工具结果 | 地理编码与气象信息 | 地理与气象 | 经纬度108.32, 22.84；中雨22℃能见度500米 | 事件现场基本情况字段 |\n"
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
            failed_titles = {"三、应急组织机构", "四、物资装备与调度", "五、处置流程建议（包括后期处置、新闻发布）", "六、次生风险"}

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
                section_text=section_texts.get("一、事件现场基本情况", ""),
            ),
            "plan_warning_response": self._build_plan_warning_response(
                task_state=task_state,
                section_text=section_texts.get("二、预案匹配与组织预警和响应", ""),
            ),
            "emergency_organization": self._build_emergency_organization(
                task_state=task_state,
                section_text=section_texts.get("三、应急组织机构", ""),
            ),
            "material_equipment_dispatch": self._build_material_equipment_dispatch(
                task_state=task_state,
                section_text=section_texts.get("四、物资装备与调度", ""),
            ),
            "disposal_process_recommendations": self._build_disposal_process_recommendations(
                section_text=section_texts.get("五、处置流程建议（包括后期处置、新闻发布）", ""),
            ),
            "secondary_risks": self._build_secondary_risks(
                section_text=section_texts.get("六、次生风险", ""),
            ),
            "reference_basis": self._build_reference_basis(
                task_state=task_state,
                section_text=section_texts.get("七、引用依据", ""),
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
                "### 【应急处置总览】",
                "",
                "以下内容用每个小点用简短的描述进行概括。",
                "",
                "**一、事件现场基本情况**",
                "",
                fields.get("一、事件现场基本情况", "") or "_暂未提取_",
                "",
                "**二、预案匹配与组织预警和响应**",
                "",
                fields.get("二、预案匹配与组织预警和响应", "") or "_暂未提取_",
                "",
                "**三、物资装备与调度**",
                "",
                fields.get("三、物资装备与调度", "") or "_暂未提取_",
                "",
                "**四、处置流程建议**",
                "",
                fields.get("四、处置流程建议", "") or "_暂未提取_",
                "",
                "**五、次生风险**",
                "",
                fields.get("五、次生风险", "") or "_暂未提取_",
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

        # 兜底：无论 LLM 在三章节里有没有写"专家库支持"段，都从 task_state 强制注入
        # 实际搜索到的专家，保证 API 输出里总有 3-5 位专家详情。
        expert_support = self._build_expert_support(task_state)

        return {
            "section_name": "应急组织机构",
            "groups": groups,
            "expert_support": expert_support,
            "fields_zh": {
                "应急组织机构": groups,
                "专家库支持": expert_support,
            },
        }

    def _build_expert_support(self, task_state: TaskState) -> List[Dict[str, str]]:
        """从 task_state.available_resources 提取专家信息，转为 API 固定字段。

        每位专家产出 {name, work_unit, specialty_field, professional_title, phone, dispatch_note}。
        """
        experts: List[Dict[str, str]] = []
        for resource in task_state.available_resources:
            if not isinstance(resource, dict):
                continue
            if resource.get("type") != "expert" and resource.get("resource_type") != "expert":
                continue

            contact = resource.get("contact") if isinstance(resource.get("contact"), dict) else {}
            phone = str(contact.get("phone") or resource.get("phone") or "").strip()
            name = str(resource.get("name") or contact.get("name") or "").strip()
            if not name:
                continue

            experts.append({
                "name": name,
                "work_unit": str(resource.get("source_org") or resource.get("work_unit") or "").strip(),
                "specialty_field": str(resource.get("specialty_field") or "").strip(),
                "professional_title": str(resource.get("professional_title") or "").strip(),
                "phone": phone,
                "dispatch_note": str(
                    resource.get("dispatch_note")
                    or "建议由指挥部办公室或值班人员人工联系专家参与远程会商或现场技术支持"
                ).strip(),
            })

        return experts[:5]

    def _build_material_equipment_dispatch(
        self,
        task_state: TaskState,
        section_text: str,
    ) -> Dict[str, Any]:
        """构建“物资装备与调度”固定字段。

        策略：始终以 task_state.available_resources 为主出表（保证只要工具搜到了资源，
        API 输出就不会全是“暂未获取”）；章节 Markdown 里 LLM 写出的额外行（不在
        task_state 里的，例如外部协同来源）合并进来作为补充；最后过滤掉整行均为
        占位词的行。
        """
        ts_items = [
            item
            for resource in task_state.available_resources[:30]
            if (item := self._resource_to_dispatch_item(resource))
        ]
        section_items = self._extract_material_dispatch_items(section_text)

        merged = self._merge_material_dispatch_items(ts_items, section_items)
        items = [item for item in merged if not self._is_placeholder_dispatch_item(item)]

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

    # 占位词（用于过滤 LLM 写的"暂未获取"行）
    _DISPATCH_PLACEHOLDER_TOKENS = (
        "暂未获取", "待现场确认", "待人工确认", "待人工联系确认", "待确认",
        "暂无", "未知", "无法获取", "未获取", "未提供",
    )

    @classmethod
    def _is_placeholder_value(cls, value: Any) -> bool:
        """判断一个字段值是否为占位/无意义内容。"""
        if value in (None, "", "无", "-"):
            return True
        text = str(value).strip()
        if not text or text in ("无", "-", "—"):
            return True
        return any(token in text for token in cls._DISPATCH_PLACEHOLDER_TOKENS)

    @classmethod
    def _is_placeholder_dispatch_item(cls, item: Dict[str, str]) -> bool:
        """判断一个 dispatch item 是否整行都是占位/空 — 这种行不应进 API 输出。"""
        if not isinstance(item, dict) or not item:
            return True
        # 关键识别列：来源 + 联系信息至少一个真实存在才认有效
        key_fields = ("recommended_dispatch_source", "location_contact_info")
        if all(cls._is_placeholder_value(item.get(field)) for field in key_fields):
            return True
        return False

    def _merge_material_dispatch_items(
        self,
        primary_items: List[Dict[str, str]],
        secondary_items: List[Dict[str, str]],
    ) -> List[Dict[str, str]]:
        """合并 task_state 出的 items 和章节 Markdown 出的 items，按"来源"去重，primary 优先。"""
        merged: List[Dict[str, str]] = list(primary_items)
        seen_sources = {
            str(item.get("recommended_dispatch_source") or "").strip()
            for item in primary_items
            if item.get("recommended_dispatch_source")
        }
        for item in secondary_items:
            source = str(item.get("recommended_dispatch_source") or "").strip()
            if source and source in seen_sources:
                continue
            merged.append(item)
            if source:
                seen_sources.add(source)
        return merged

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

        # 专家不出现在物资调度表里；专家走 emergency_organization.expert_support
        if resource.get("type") == "expert" or resource.get("resource_type") == "expert":
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

    # source_type → 中文依据类型映射，避免最终方案里出现英文代号
    _SOURCE_TYPE_ZH = {
        "emergency_plan": "应急预案",
        "regulation": "法规",
        "rag": "技术规范",
        "case": "案例",
        "historical_case": "案例",
        "expert": "专家意见",
        "tool_result": "工具结果",
    }

    def _knowledge_ref_to_reference_item(self, ref: Any) -> Dict[str, str]:
        metadata = getattr(ref, "metadata", {}) or {}
        raw_type = str(getattr(ref, "source_type", "") or "").strip()
        return {
            "basis_type": self._SOURCE_TYPE_ZH.get(raw_type, raw_type or "其他"),
            "basis_name": str(getattr(ref, "title", "") or ""),
            "reference_chapter": str(
                metadata.get("hit_path")
                or metadata.get("module")
                or metadata.get("section")
                or metadata.get("chapter")
                or ""
            ),
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
            metadata = getattr(ref, "metadata", {}) or {}
            hit_path = metadata.get("hit_path") or ""
            module = metadata.get("module") or ""
            plan_file = metadata.get("plan_file") or ""
            fallback_chain = metadata.get("fallback_chain") or []
            lines.append(
                "\n".join(
                    [
                        f"### 依据 {index}: {getattr(ref, 'title', '') or '未命名依据'}",
                        f"- 类型：{getattr(ref, 'source_type', '') or '未知'}",
                        f"- 来源（source_path）：{getattr(ref, 'source_path', '') or '未注明'}",
                        f"- 章节路径（hit_path）：{hit_path or '未指定'}  ← 写入七、引用依据的引用章节列时优先用此字段",
                        f"- 模块：{module or '未指定'}",
                        f"- 预案文件：{plan_file or '未指定'}",
                        f"- 回退链：{fallback_chain if fallback_chain else '无'}",
                        f"- 分数：{getattr(ref, 'score', None)}",
                        f"- 元数据：{self._safe_json(metadata)}",
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
        lines.append("### 【应急处置详情】")
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
            "一、事件现场基本情况": ("事件现场基本情况", "事件概述", "事件地点", "天气", "事件简述", "周边环境", "主要影响", "时间", "位置", "坐标", "路况", "伤亡"),
            "二、预案匹配与组织预警和响应": ("预案匹配", "预案匹配与组织预警和响应", "响应定级", "事件等级", "匹配预案", "预警发布", "启动响应", "判断依据", "响应级别", "启动主体"),
            "三、应急组织机构": ("应急组织机构", "指挥架构", "应急管理", "消防", "专家", "工作组", "总指挥", "牵头单位", "主要职责"),
            "四、物资装备与调度": ("物资装备与调度", "资源调度", "所需物资", "推荐调度来源", "距离", "预计到达时间", "联系人信息", "资源缺口", "梯队"),
            "五、处置流程建议（包括后期处置、新闻发布）": ("处置流程建议", "处置行动", "信息报送", "新闻发布", "舆情", "初报", "续报", "终报", "二次排查", "家属", "检伤", "现场警戒", "行动", "总结评估"),
            "六、次生风险": ("次生风险", "风险", "注意事项", "触发条件", "影响后果", "应对措施", "安全风险", "处置风险", "衍生风险"),
            "七、引用依据": ("引用依据", "依据引用", "依据", "引用", "预案", "法规", "案例", "工具结果", "hit_path", "引用章节"),
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
