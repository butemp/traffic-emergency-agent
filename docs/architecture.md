# 交通应急指挥 Agent 项目整体架构说明

> 面向对象：项目开发人员、集成人员、后续维护人员  
> 目标：帮助技术人员快速理解 Web 端应急指挥 Agent 的核心模块、数据流和扩展点。

## 1. 项目定位

本项目是一个面向交通突发事件的应急指挥 Agent。它不是单轮问答机器人，而是一个带状态机的任务型智能体：

1. 从用户输入中提取灾情信息。
2. 判断关键信息是否完整。
3. 自动调用工具补齐位置、天气、路况、预案、资源、专家、路线等信息。
4. 生成并评估处置方案。
5. 输出标准化应急指挥方案。

Web 端基于 Chainlit 实现，核心逻辑由 Agent、Skill、Tool 和 TaskState 共同完成。

## 2. 顶层架构

```text
用户 / 指挥人员
    |
    v
Chainlit Web 入口
web_app.py
    |
    v
Agent 主控
src/agent/agent.py
    |
    +--> TaskState 状态机
    |    src/agent/task_state.py
    |
    +--> SkillRouter 能力路由
    |    src/agent/skill_router.py
    |
    +--> OpenAI-compatible 模型 Provider
    |    src/providers/openai_provider.py
    |
    +--> Tools 工具层
         src/tools/
              |
              +--> 高德：地理编码、天气、路况、POI、路线规划
              +--> 预案：事件定级、预案模块读取
              +--> 资源：仓库、队伍、物资调度
              +--> 专家：专家库检索
              +--> RAG：法规、案例、技术资料检索
              +--> 风险评估：方案风险评估
```

## 3. Web 入口层

主要文件：

- `web_app.py`

职责：

- 初始化模型 Provider。
- 初始化工具列表。
- 初始化 Agent。
- 接收用户消息。
- 展示工具调用过程。
- 展示补问信息、方案选择卡片和最终方案。
- 在最终方案展示前执行格式和内容审核。

Web 层本身不负责业务推理，业务推理由 Agent 和工具完成。Web 层更像是“会话编排器 + 前端展示适配层”。

## 4. Agent 主控层

主要文件：

- `src/agent/agent.py`
- `src/agent/task_state.py`
- `src/agent/message.py`
- `src/agent/skill_router.py`
- `src/agent/final_plan_reviewer.py`

### 4.1 Agent

`Agent` 是主控对象，负责：

- 维护对话历史。
- 构造运行时 system prompt。
- 根据当前阶段暴露可用工具。
- 解析模型返回的 `agent_control` 控制块。
- 执行阶段流转。
- 将工具结果同步到 `TaskState`。

### 4.2 TaskState

`TaskState` 是整个任务的结构化状态容器，保存：

- 当前阶段。
- 结构化灾情信息 `IncidentInfo`。
- 环境信息 `EnvironmentInfo`。
- 可用资源。
- 知识引用。
- 候选方案。
- 风险评估结果。
- 待用户补问问题。
- 工具调用日志。

模型上下文并不只依赖聊天历史，`TaskState` 会被摘要后注入 system prompt，使模型能看到当前任务的结构化进展。

### 4.3 FinalPlanReviewer

`FinalPlanReviewer` 是最终方案审核 Agent，用独立模型对主模型输出做检查。

重点检查：

- 是否满足固定章节结构。
- 是否虚构“已通知、已派遣、已下达指令”等现实执行动作。
- 是否包含指挥架构、预警发布、处置行动、资源调度、风险提示、依据引用。
- 是否包含专家技术支持。
- 是否包含资源来源、路径、预计到达、联系人。
- 是否把内部资源编码直接输出给用户。

审核不通过时，会把问题返回主模型要求重写，最多多轮修正。

## 5. 任务阶段状态机

当前核心阶段如下：

```text
INTAKE
    灾情接收、结构化提取、关键信息完备性检查、预案定级

SITUATIONAL_AWARENESS
    态势感知，补齐坐标、天气、路况、媒体摘要等环境信息

PLAN_GENERATION
    获取预案依据、检索资源、检索专家、规划路线、生成调度方案

PLAN_EVALUATION
    对候选方案做风险评估

OUTPUT
    生成最终标准化应急指挥方案

OUTPUT_COMPLETE
    任务完成

WAITING_USER
    等待用户补充信息、选择方案或确认继续
```

典型流转：

```text
用户输入灾情
  -> INTAKE 提取事故类型、位置、伤亡、现场状态
  -> 信息不足则 WAITING_USER 补问
  -> 信息齐全后 evaluate_incident_severity 定级
  -> SITUATIONAL_AWARENESS 调用高德和环境工具
  -> PLAN_GENERATION 调用预案、资源、专家、路线工具
  -> PLAN_EVALUATION 调用风险评估
  -> OUTPUT 输出最终方案
  -> FinalPlanReviewer 审核
  -> 前端展示
```

## 6. Skill 能力层

Skill 目录：

- `src/skills/master_flow`
- `src/skills/situational_awareness`
- `src/skills/knowledge_retrieval`
- `src/skills/resource_dispatch`
- `src/skills/risk_evaluation`
- `src/skills/human_collaboration`

每个 Skill 通常包含：

- `SKILL.yaml`：声明 Skill 名称、激活阶段、可用工具、优先级。
- `prompt.md`：声明该 Skill 的行为规则。
- `tools.py`：工具说明或预留扩展。

### 6.1 master_flow

主流程编排 Skill。

负责：

- 定义阶段推进规则。
- 约束最终方案输出结构。
- 防止模型虚构现实执行动作。
- 要求最终方案按固定 9 章节输出。

### 6.2 situational_awareness

态势感知 Skill。

负责：

- 地址转坐标。
- 天气查询。
- 路况查询。
- 图片或视频摘要。
- 必要时搜索周边公开设施。

### 6.3 knowledge_retrieval

知识检索 Skill。

负责：

- 事件响应级别判定。
- 获取结构化应急预案模块。
- 查询法规、技术指南。
- 查询历史案例。

### 6.4 resource_dispatch

资源调度 Skill。

负责：

- 查询内部仓库和救援队伍。
- 生成分梯队调度方案。
- 检索专家库。
- 搜索外部 POI，例如医院、消防救援站。
- 调用高德做调度路线规划。

### 6.5 risk_evaluation

风险评估 Skill。

负责：

- 对候选方案做风险评估。
- 从可行性、资源覆盖、时效性、合规性等维度给出风险提示。

### 6.6 human_collaboration

人机协作 Skill。

负责：

- 信息不足时补问。
- 多方案时让用户选择。
- 模型停住时让用户选择继续行动或补充 refine 信息。

## 7. 工具层

工具位于 `src/tools/`，统一继承 `BaseTool`。

### 7.1 高德工具

主要文件：

- `src/tools/gaode_tools.py`

包含：

- `geocode_address`：文本地址转经纬度。
- `reverse_geocode`：经纬度转地址。
- `get_weather_by_location`：天气查询。
- `check_traffic_status`：路况查询。
- `search_nearby_pois`：周边 POI 搜索。
- `plan_dispatch_routes`：调度路线规划。

`plan_dispatch_routes` 基于高德驾车路径规划接口，可返回：

- 距离。
- 预计时间。
- 红绿灯数。
- 导航步骤。
- 路线摘要。

### 7.2 资源调度工具

主要文件：

- `src/tools/resource_dispatch_tools.py`
- `src/resource_dispatch/engine.py`

包含：

- `search_emergency_resources`：查询内部仓库和队伍。
- `optimize_dispatch_plan`：按资源覆盖、距离和优先级生成分梯队方案。

资源数据来源主要在：

- `data/仓库和队伍的物资数据`

资源类型内部可用英文编码，但最终输出必须转换成中文，例如：

- `WARNING` -> 警示防护设备
- `PPE` -> 个人防护用品
- `SIGN` -> 交通标志标牌
- `VEHICLE` -> 车辆装备

### 7.3 专家检索工具

主要文件：

- `src/tools/expert_tools.py`

数据来源：

- `data/专家数据/expert_info.xls`

工具：

- `search_experts`

返回内容包括：

- 专家姓名。
- 专业方向。
- 职称。
- 单位。
- 联系方式。
- 地址和坐标。
- 建议支持方式。

专家不是自动调度对象，最终方案中应表述为“建议由指挥部办公室或值班人员人工联系专家参与远程会商或现场支持”。

### 7.4 应急预案工具

主要文件：

- `src/tools/get_emergency_plan.py`
- `src/tools/evaluate_incident_severity.py`
- `src/emergency_plans/service.py`
- `src/emergency_plans/severity_evaluator.py`

数据来源：

- `data/regulations/data`

能力：

- 根据事件类别获取预案模块。
- 根据预案分级标准判定响应级别。
- 为指挥架构、响应措施、预警发布、分场景处置提供依据。

### 7.5 RAG 和案例工具

主要文件：

- `src/rag/`
- `src/tools/query_regulations.py`
- `src/tools/query_historical_cases.py`

用途：

- 查询法规或技术资料。
- 查询历史相似案例。
- 补充预案以外的技术细节。

### 7.6 风险评估工具

主要文件：

- `src/tools/risk_assessment.py`

用途：

- 对方案进行多维度风险评估。
- 给出风险等级、主要风险点和优化建议。

## 8. 模型 Provider 层

主要文件：

- `src/providers/openai_provider.py`
- `src/providers/defaults.py`

项目统一使用 OpenAI-compatible Chat Completions 风格调用文本模型。

当前默认配置：

```text
api_key: sk-TBi6zDfq2SkTvyZQCusU7g
base_url: https://ai.gxtri.cn/llm/v1
model: deepseek-ai/DeepSeek-V3.2
```

说明：

- 主对话模型、风险评估模型、定级子模型等都可以复用 OpenAI-compatible Provider。
- Web 端支持通过设置面板覆盖 `OPENAI_API_KEY`、`OPENAI_MODEL`、`OPENAI_BASE_URL`。
- 多模态图片理解可以使用单独的 caption provider。

## 9. 数据目录

常用数据目录：

```text
data/
  regulations/
    data/                  结构化应急预案数据
    chunked_json/           RAG 切片数据

  仓库和队伍的物资数据/       仓库、队伍、物资清洗数据

  专家数据/
    expert_info.xls         专家库

  historical_cases/         历史案例

  graph/                    地图或资源图谱数据
```

## 10. 最终输出方案

最终方案应按照 `输出模版.md` 约束输出固定 9 章节：

```text
一、事件概述
二、响应定级
三、指挥架构
四、预警发布
五、处置行动方案
六、资源调度方案
七、信息报送与新闻发布
八、风险提示与注意事项
九、依据引用
```

关键要求：

- 不能省略章节。
- 不能把建议动作写成已经执行。
- 不能声称系统已经通知队伍、下达指令、派遣资源。
- 资源类别必须使用中文。
- 指挥架构必须包含应急管理、公安交管、消防救援、医疗救援、道路运营管理、专家技术支持。
- 资源调度必须说明来源、联系人、电话、距离、预计到达和调度路径。
- 处置行动必须包含涉险人员二次排查、其他伤员排查、家属安抚、现场警戒和二次事故防范。

## 11. 一次完整请求的数据流

```text
1. 用户输入：
   “G72 高速 K85 处两车追尾，有人被困，道路拥堵。”

2. INTAKE：
   提取事故类型、位置、伤亡、现场状态。
   如缺信息，则进入 WAITING_USER 补问。

3. 定级：
   调用 evaluate_incident_severity。
   必要时调用 get_emergency_plan 获取分级标准。

4. 态势感知：
   调用 geocode_address 获取坐标。
   调用 get_weather_by_location 获取天气。
   调用 check_traffic_status 获取路况。

5. 方案生成：
   调用 get_emergency_plan 获取指挥架构、响应措施、场景处置、预警规则。
   调用 search_emergency_resources 搜索仓库和队伍。
   调用 optimize_dispatch_plan 生成梯队方案。
   调用 search_experts 查询专家。
   调用 search_nearby_pois 补充医院、消防等外部设施。
   调用 plan_dispatch_routes 获取高德路线。

6. 风险评估：
   调用 risk_assessment。

7. 输出：
   主模型生成 9 章节最终方案。
   FinalPlanReviewer 审核。
   审核通过后展示到前端。
```

## 12. 主要扩展点

### 新增工具

1. 在 `src/tools/` 新增工具类并继承 `BaseTool`。
2. 在 `src/tools/__init__.py` 导出。
3. 在 `web_app.py` 初始化工具。
4. 在对应 Skill 的 `SKILL.yaml` 中声明工具名。
5. 在对应 Skill 的 `prompt.md` 中说明调用时机和输出要求。

### 新增 Skill

1. 在 `src/skills/` 下新建目录。
2. 编写 `SKILL.yaml`。
3. 编写 `prompt.md`。
4. 根据阶段配置 `active_phases`。
5. 如需工具，配置 `tools` 列表。

### 新增数据源

1. 将数据放入 `data/` 下独立目录。
2. 编写读取或清洗脚本。
3. 封装为 Tool 或 Service。
4. 将结果同步到 `TaskState`，让最终方案可引用。

## 13. 维护注意事项

- Prompt 约束不能替代代码校验，关键要求应尽量做成流程门禁或审核规则。
- 最终输出必须区分“建议执行”和“已经执行”，系统不能虚构现实动作。
- 工具结果应同步到 `TaskState`，否则主模型容易遗忘。
- 资源、专家、路线等信息应尽量结构化，避免只放在自然语言历史里。
- 英文内部编码只允许在工具参数和内部计算中使用，面向用户必须转换成中文。
- 外部 API 调用结果只代表辅助决策依据，实际调度仍需人工确认。

