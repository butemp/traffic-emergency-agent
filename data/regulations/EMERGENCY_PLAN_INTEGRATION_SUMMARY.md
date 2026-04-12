# 应急预案接入改造总结

## 1. 本次改造的定位

本轮改造的目标，是把人工结构化后的官方应急预案接入到现有应急指挥 Agent 中，形成一层独立的“预案规范约束能力”。

这批预案的使用定位不是资源调度，而是：

- 在 `INTAKE` 阶段参与事件定级
- 在 `PLAN_GENERATION` 阶段约束指挥架构、标准响应动作、分场景处置和预警发布
- 作为方案生成时的正式依据引用

一句话概括：

- 预案负责“该怎么指挥、谁负责、哪些动作必须出现”
- 资源调度负责“具体派哪些仓库、哪些队伍、怎么分梯队”

---

## 2. 已完成的核心改造

### 2.1 新增预案服务层

新增目录：

- `src/emergency_plans/`

新增文件：

- `src/emergency_plans/service.py`
- `src/emergency_plans/severity_evaluator.py`
- `src/emergency_plans/__init__.py`

职责划分如下：

#### `EmergencyPlanService`

负责：

- 加载 `data/regulations/data` 下的结构化预案 JSON
- 加载和解析 `plan_registry.json`
- 将中文类别映射为统一编码
- 按 `incident_category / disaster_type / module / level / scene_type` 精确取用预案模块
- 将模块内容整理成适合模型阅读的文本

当前支持的模块：

- `grading_criteria`
- `command_structure`
- `response_measures`
- `scene_disposal`
- `warning_rules`

#### `SeverityEvaluator`

这是一个独立的“定级子模块”，职责是：

- 使用一个新的模型对话完成定级
- 避免主对话上下文过长
- 输出结构化定级结果

输出内容包括：

- `incident_category`
- `disaster_type`
- `response_level`
- `confidence`
- `reasoning`
- `missing_fields`
- `scene_type`

它的作用相当于一个轻量子 Agent，只是当前先做成了内部模块和工具封装，没有再引入额外复杂的 Agent 编排框架。

---

### 2.2 新增两个预案相关工具

新增文件：

- `src/tools/get_emergency_plan.py`
- `src/tools/evaluate_incident_severity.py`

#### `get_emergency_plan`

定位：

- 精确取用预案模块
- 不走 RAG
- 不做语义检索

适用场景：

- `INTAKE` 阶段需要显式查看 `grading_criteria`
- `PLAN_GENERATION` 阶段需要获取：
  - `command_structure`
  - `response_measures`
  - `scene_disposal`
  - `warning_rules`

#### `evaluate_incident_severity`

定位：

- 基于预案分级标准完成独立定级
- 通过新的模型对话缓解主模型上下文压力

适用场景：

- `INTAKE` 阶段在关键信息基本齐全后，完成正式定级

---

### 2.3 新增预案注册表

新增文件：

- `data/regulations/data/plan_registry.json`

作用：

- 把业务层统一类别编码映射到实际预案文件
- 明确哪些类别有专项预案，哪些暂时回退到综合预案

当前专项覆盖：

- `EXPRESSWAY` -> `plan_2.json`
- `HIGHWAY` -> `plan_4.json`
- `PORT` -> `plan_5.json`

当前先回退综合预案的类别：

- `ROAD_TRANSPORT`
- `WATERWAY`
- `WATERWAY_XIJIANG`
- `WATER_TRANSPORT`
- `CITY_BUS`
- `URBAN_RAIL`
- `CONSTRUCTION`

回退预案：

- `plan_1.json`（交通运输综合应急预案）

---

### 2.4 TaskState 扩展

修改文件：

- `src/agent/task_state.py`

在 `IncidentInfo` 中新增字段：

- `incident_category`
- `disaster_type`
- `scene_type`
- `response_level`
- `response_level_reason`
- `response_level_confidence`

新增方法：

- `intake_ready_to_advance()`

新的推进条件为：

- `INTAKE` 只有在“4 项关键灾情信息齐全”且“`response_level` 已完成判定”后，才允许进入下一阶段

这一步是本次改造里很关键的结构性修正。否则模型很容易在信息刚齐全时直接跳过预案定级。

---

### 2.5 Agent 主流程接入

修改文件：

- `src/agent/agent.py`

已完成的接入包括：

#### 轻量结构化推断

主流程在收到用户输入后，会先做轻量推断：

- `incident_category`
- `disaster_type`
- `scene_type`

这个推断只是给后续工具一个起点，不替代正式定级。

#### 工具结果回写 TaskState

Agent 现在会把以下结果回写到状态中：

- `evaluate_incident_severity`
  - 写入 `incident_category`
  - `disaster_type`
  - `scene_type`
  - `response_level`
  - `response_level_reason`
  - `response_level_confidence`
- `get_emergency_plan`
  - 作为 `knowledge_refs` 记录预案引用

#### System Prompt 更新

主系统提示已调整为：

- 事件定级优先用 `evaluate_incident_severity`
- 预案模块精确取用优先用 `get_emergency_plan`
- `query_rag` 用于补充法规和技术细节，而不是替代预案定级

---

### 2.6 Skill 与 Prompt 改造

修改文件：

- `src/skills/knowledge_retrieval/SKILL.yaml`
- `src/skills/knowledge_retrieval/prompt.md`
- `src/skills/master_flow/prompt.md`
- `src/skills/human_collaboration/prompt.md`

#### `knowledge_retrieval`

现在已经在以下阶段激活：

- `INTAKE`
- `PLAN_GENERATION`

新增工具：

- `evaluate_incident_severity`
- `get_emergency_plan`

#### `master_flow`

现在已经明确约束：

- `INTAKE` 阶段先做信息收集和预案定级
- 即使 4 项必填信息齐了，只要 `response_level` 没判定，就不能离开 `INTAKE`
- `PLAN_GENERATION` 阶段生成方案前，应优先拉取：
  - `command_structure`
  - `response_measures`
  - `scene_disposal`
  - `warning_rules`

#### `human_collaboration`

补问逻辑增加了“定级优先”原则：

- 如果某个信息缺口会直接影响预案定级，应优先补问这类信息

---

### 2.7 Web 端接线

修改文件：

- `web_app.py`

已完成的内容：

- 创建 Agent 时初始化 `EmergencyPlanService`
- 注册 `GetEmergencyPlan`
- 注册 `EvaluateIncidentSeverity`
- 前端工具执行 Step 增加这两个工具的可视化展示

另外加了两层关键保护：

#### 保护 1：信息齐了但还没定级，不允许直接往下走

如果当前：

- 仍在 `INTAKE`
- 4 项关键信息已齐全
- 但 `response_level` 仍为空

则 Web 会插入系统纠正消息，强制模型优先调用 `evaluate_incident_severity`。

#### 保护 2：定级完成但模型不切阶段，也不允许停住

如果当前：

- `INTAKE` 已经完整
- `response_level` 已有结果
- 模型却没有切换阶段，也没有补问

则 Web 会再次插入系统纠正消息，要求模型：

- 要么继续补问真正缺失的信息
- 要么明确进入 `SITUATIONAL_AWARENESS`

---

## 3. 当前主流程中的使用方式

### 3.1 INTAKE 阶段

当前推荐流程：

1. 提取灾情结构化信息
2. 检查 4 项必要字段：
   - 事故类型
   - 事故位置
   - 伤亡情况
   - 现场状态
3. 如果缺失，走补问
4. 如果齐全，调用 `evaluate_incident_severity`
5. 得到：
   - `incident_category`
   - `disaster_type`
   - `response_level`
   - `scene_type`
6. 完成后再进入 `SITUATIONAL_AWARENESS`

### 3.2 PLAN_GENERATION 阶段

当前推荐流程：

1. 获取 `command_structure`
2. 获取 `response_measures`
3. 如有明确场景，获取 `scene_disposal`
4. 如涉及预警，获取 `warning_rules`
5. 再结合资源调度和其他知识生成方案

这意味着：

- 预案负责规范方案框架
- 资源调度负责填充具体执行资源

---

## 4. 已验证内容

本轮已经做过以下验证：

### 4.1 语法校验

已通过：

- `python -m py_compile`

涉及文件包括：

- `src/emergency_plans/*`
- `src/tools/get_emergency_plan.py`
- `src/tools/evaluate_incident_severity.py`
- `src/agent/task_state.py`
- `src/agent/agent.py`
- `web_app.py`

### 4.2 本地烟测

已验证：

- `EXPRESSWAY + FLOOD + scene_disposal` 能正确命中“洪水与地质灾害事件”
- 定级工具能够返回结构化的 `response_level`
- `INTAKE` 在信息齐全但未定级时不会提前跳阶段
- 无专项预案的类别会回退到综合预案

---

## 5. 当前边界与已知限制

### 5.1 预案覆盖还不是全量专项覆盖

当前数据里只有部分专项预案完成接入：

- 高速公路
- 公路交通
- 港口
- 综合总纲

其余场景暂时仍走综合预案回退。

### 5.2 `response_level` 与 `severity` 仍是两套概念

当前系统已经明确区分：

- `severity`: 模型对紧急程度的工作性判断
- `response_level`: 预案意义上的正式响应级别

后续业务侧如果更强调正式预案流程，应优先使用 `response_level`。

### 5.3 现在是“独立定级子模块”，还不是多 Agent 编排框架

目前已经实现了“新的模型对话做定级”的效果，但还没有再往上叠一层统一的子 Agent 调度框架。

这一步是刻意控制复杂度，先保证可读性和稳定性。

---

## 6. 下一步建议

建议按以下顺序继续推进：

### 优先级 P1

- 继续补齐剩余专项预案文件
- 扩展 `plan_registry.json`
- 让当前回退到综合预案的场景逐步切换成专项预案

### 优先级 P1

- 收紧 `PLAN_GENERATION` 阶段 prompt
- 明确要求模型在出方案前按顺序调用预案模块工具

### 优先级 P2

- 在最终方案里强制输出“依据引用”
- 例如每个关键动作后标注：
  - 来自哪份预案
  - 来自哪个模块

### 优先级 P2

- 后续如果复杂步骤继续增多，可以把以下能力继续独立化：
  - 场景匹配
  - 风险评估
  - 方案合规复核

---

## 7. 本次改造涉及的主要文件

### 新增文件

- `src/emergency_plans/__init__.py`
- `src/emergency_plans/service.py`
- `src/emergency_plans/severity_evaluator.py`
- `src/tools/get_emergency_plan.py`
- `src/tools/evaluate_incident_severity.py`
- `data/regulations/data/plan_registry.json`

### 修改文件

- `src/tools/__init__.py`
- `src/agent/task_state.py`
- `src/agent/agent.py`
- `src/skills/knowledge_retrieval/SKILL.yaml`
- `src/skills/knowledge_retrieval/prompt.md`
- `src/skills/master_flow/prompt.md`
- `src/skills/human_collaboration/prompt.md`
- `web_app.py`

---

## 8. 结论

当前应急预案已经以“规范约束层”的形式接入主流程，主要成果是：

- 可以基于预案完成正式定级
- 可以按模块精确取用预案内容
- 可以把预案作为方案生成的约束和依据
- 不会再把预案和资源调度混在一起

这一步已经把预案从“静态材料”变成了“可被主流程按阶段调用的结构化能力”。
