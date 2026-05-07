# 交通应急指挥助手 HTTP API 接口文档

Base URL: `http://<host>:8000/api/v1`

服务随 Chainlit 一起启动，共用同一进程和端口：

```bash
chainlit run web_app.py --host 0.0.0.0 --port 8000
```

---

## 1. 健康检查

### `GET /api/v1/health`

检查服务是否正常运行。

#### 请求参数

无。

#### 响应字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | 固定为 `"healthy"` |
| `timestamp` | string | 当前服务器时间（ISO 8601） |
| `python_version` | string | Python 版本号 |
| `tasks_total` | int | 任务总数 |
| `tasks_running` | int | 正在运行的任务数 |

#### 响应示例

```json
{
  "status": "healthy",
  "timestamp": "2025-07-01T10:00:00.123456",
  "python_version": "3.11.9",
  "tasks_total": 3,
  "tasks_running": 1
}
```

---

## 2. 创建任务

### `POST /api/v1/tasks`

提交一个异步方案生成任务。接口立即返回 `task_id`，后台开始执行 Agent 流程。

#### 请求字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `incident_description` | string | **是** | 事件描述文本，例如 `"G72高速K85处三车追尾，2人受伤"` |
| `incident_info` | object | 否 | 预填充的结构化灾情信息，直接写入 Agent 的 TaskState |
| `media_urls` | string[] | 否 | 现场图片/视频 URL 列表 |
| `config` | object | 否 | 模型配置覆盖 |

##### `incident_info` 可选字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `incident_type` | string | 事件类型，如 `"交通事故"` `"危化品泄漏"` `"火灾"` `"地质灾害"` |
| `severity` | string | 严重程度：`low` / `medium` / `high` / `critical` |
| `location_text` | string | 位置描述，如 `"G72高速K85"` |
| `location_coords` | object | 坐标 `{"longitude": 108.3, "latitude": 22.8}` |
| `time_text` | string | 事发时间描述 |
| `casualty_status` | string | 伤亡概述，如 `"2人受伤"` |
| `casualties` | object | 伤亡详情 `{"injured": 2, "dead": 0, "trapped": 1}` |
| `scene_status` | string | 现场状态，如 `"双向阻断"` `"单向阻断"` |
| `hazmat_involved` | bool | 是否涉及危化品 |
| `hazmat_type` | string | 危化品类型，如 `"液化天然气"` |
| `incident_category` | string | 事件分类 |
| `disaster_type` | string | 灾害类别 |
| `scene_type` | string | 分场景类型 |
| `road_info` | string | 道路信息 |
| `vehicles_involved` | string | 涉事车辆信息 |
| `additional_context` | string | 补充信息 |

##### `config` 可选字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `OPENAI_API_KEY` | string | API Key（不传则用服务默认值） |
| `OPENAI_MODEL` | string | 模型名称（不传则用服务默认值） |
| `OPENAI_BASE_URL` | string | API Base URL |
| `OPENAI_MAX_TOKENS` | string | 单次最大生成 token 数 |

#### 响应字段（HTTP 201）

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_id` | string | 任务唯一 ID（12 位十六进制） |
| `status` | string | 固定为 `"pending"` |
| `created_at` | string | 创建时间（ISO 8601） |

#### 请求示例

```json
{
  "incident_description": "G72高速K85处三车追尾，2人受伤",
  "incident_info": {
    "incident_type": "交通事故",
    "severity": "high",
    "location_text": "G72高速K85",
    "casualty_status": "2人受伤"
  }
}
```

#### 响应示例

```json
{
  "task_id": "a1b2c3d4e5f6",
  "status": "pending",
  "created_at": "2025-07-01T10:00:00.000000"
}
```

---

## 3. 查询任务状态

### `GET /api/v1/tasks/{task_id}`

查询指定任务的当前状态、进度、结果或错误信息。客户端应轮询此接口直到 `status` 变为终态。

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `task_id` | string | 任务 ID |

#### 响应字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_id` | string | 任务 ID |
| `status` | string | 任务状态（见下方状态说明） |
| `progress` | object | 实时进度信息 |
| `result` | object \| null | 任务完成时的最终结果（仅 `completed` 状态有值） |
| `process_data` | object \| null | 任务过程中收集的中间数据（仅 `completed` 状态有值） |
| `error` | object \| null | 错误信息（仅 `failed` 状态有值） |
| `created_at` | string | 创建时间 |
| `completed_at` | string \| null | 完成时间 |

##### 任务状态 `status` 取值

| 值 | 说明 |
|----|------|
| `pending` | 已创建，等待启动 |
| `running` | Agent 正在执行中 |
| `completed` | 方案生成完成 |
| `failed` | 执行失败 |
| `cancelled` | 已被取消 |

##### `progress` 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `phase` | string | 当前 Agent 阶段：`INTAKE` / `SITUATIONAL_AWARENESS` / `PLAN_GENERATION` / `PLAN_EVALUATION` / `OUTPUT` / `OUTPUT_COMPLETE` |
| `iteration` | int | 当前迭代轮次（最大 24） |
| `tools_called` | string[] | 已调用的工具名称列表 |
| `current_action` | string | 当前正在做的事情（人类可读描述） |
| `pipeline_status` | string | Pipeline 阶段：`generating_sections` / `reviewing` / `review_round_N` / `repair_round_N` |

##### `result` 字段（任务完成时）

| 字段 | 类型 | 说明 |
|------|------|------|
| `plan_markdown` | string | 完整的最终方案 Markdown 文本（9 章节结构） |
| `sections` | object | 各章节文本字典，key 为章节标题，value 为该章节 Markdown |
| `review` | object \| null | 最终审核结果的原始 JSON |

`sections` 的 key 列表：

| Key | 章节标题 |
|-----|---------|
| `一、事件概述` | 事件基本信息表格 |
| `二、响应定级` | 响应级别与定级依据 |
| `三、指挥架构` | 指挥体系与工作组 |
| `四、预警发布` | 预警级别与发布流程 |
| `五、处置行动方案` | 三阶段处置行动表 |
| `六、资源调度方案` | 分梯队资源调度详情 |
| `七、信息报送与新闻发布` | 报送流程与舆情管控 |
| `八、风险提示与注意事项` | 安全/处置/衍生风险 |
| `九、依据引用` | 预案法规与案例依据 |

##### `process_data` 字段（任务完成时）

| 字段 | 类型 | 说明 |
|------|------|------|
| `incident_info` | object | Agent 最终收集到的结构化灾情信息 |
| `environment` | object | 环境态势信息（地址、天气、路况、周边 POI、路线） |
| `resources` | object[] | 可用资源列表（仓库、队伍） |
| `experts` | object[] | 检索到的专家列表 |
| `tool_calls` | object[] | 工具调用记录 |
| `risk_assessment` | object[] | 风险评估结果 |
| `knowledge_refs` | object[] | 知识引用（预案、法规、案例） |

##### `error` 字段（任务失败时）

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | string | 错误码 |
| `message` | string | 错误描述 |
| `phase` | string | 失败时所处的 Agent 阶段 |
| `iteration` | int | 失败时的迭代轮次 |

错误码说明：

| 错误码 | 说明 |
|--------|------|
| `CANCELLED` | 任务被用户主动取消 |
| `MAX_ITERATIONS` | Agent 迭代超过上限（24 轮） |
| `LLM_ERROR` | LLM 调用失败 |
| `PIPELINE_ERROR` | 章节化 Pipeline 生成失败 |
| `INTERNAL_ERROR` | 其他内部异常 |

#### 响应示例（运行中）

```json
{
  "task_id": "a1b2c3d4e5f6",
  "status": "running",
  "progress": {
    "phase": "PLAN_GENERATION",
    "iteration": 8,
    "tools_called": [
      "geocode_address",
      "get_weather_by_location",
      "check_traffic_status",
      "evaluate_incident_severity",
      "get_emergency_plan",
      "search_emergency_resources"
    ],
    "current_action": "已调用 search_emergency_resources，分析结果中",
    "pipeline_status": ""
  },
  "result": null,
  "process_data": null,
  "error": null,
  "created_at": "2025-07-01T10:00:00.000000",
  "completed_at": null
}
```

#### 响应示例（已完成）

```json
{
  "task_id": "a1b2c3d4e5f6",
  "status": "completed",
  "progress": {
    "phase": "OUTPUT_COMPLETE",
    "iteration": 12,
    "tools_called": ["geocode_address", "..."],
    "current_action": "全局审核第 2/5 轮",
    "pipeline_status": "review_round_2"
  },
  "result": {
    "plan_markdown": "# 标准化应急指挥方案\n\n> 生成时间：...\n\n### 一、事件概述\n...",
    "sections": {
      "一、事件概述": "### 一、事件概述\n...",
      "二、响应定级": "### 二、响应定级\n..."
    },
    "review": {
      "passed": true,
      "score": 88,
      "summary": "方案整体结构完整，内容详实"
    }
  },
  "process_data": {
    "incident_info": {
      "incident_type": "交通事故",
      "severity": "high",
      "response_level": "III级"
    },
    "environment": {
      "formatted_address": "广西壮族自治区...",
      "weather": {"temperature": "28°C"}
    },
    "resources": [],
    "experts": [],
    "tool_calls": [
      {"tool_name": "geocode_address", "success": true}
    ],
    "risk_assessment": [],
    "knowledge_refs": []
  },
  "error": null,
  "created_at": "2025-07-01T10:00:00.000000",
  "completed_at": "2025-07-01T10:05:30.000000"
}
```

---

## 4. 任务列表

### `GET /api/v1/tasks`

分页列出任务，支持按状态过滤。

#### 查询参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `status` | string | 否 | 无 | 按状态过滤：`pending` / `running` / `completed` / `failed` / `cancelled` |
| `limit` | int | 否 | 20 | 每页数量（1–100） |
| `offset` | int | 否 | 0 | 偏移量 |

#### 响应字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `total` | int | 符合条件的任务总数 |
| `tasks` | object[] | 任务摘要列表（按创建时间倒序） |

##### `tasks[]` 中每项的字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_id` | string | 任务 ID |
| `status` | string | 任务状态 |
| `created_at` | string | 创建时间 |
| `completed_at` | string \| null | 完成时间 |
| `incident_description` | string | 事件描述 |

#### 响应示例

```json
{
  "total": 2,
  "tasks": [
    {
      "task_id": "b2c3d4e5f6a7",
      "status": "running",
      "created_at": "2025-07-01T10:05:00.000000",
      "completed_at": null,
      "incident_description": "S31高速K120处危化品罐车泄漏"
    },
    {
      "task_id": "a1b2c3d4e5f6",
      "status": "completed",
      "created_at": "2025-07-01T10:00:00.000000",
      "completed_at": "2025-07-01T10:05:30.000000",
      "incident_description": "G72高速K85处三车追尾，2人受伤"
    }
  ]
}
```

---

## 5. 取消任务

### `DELETE /api/v1/tasks/{task_id}`

取消一个正在执行的任务。Agent 会在下一个检查点停止。

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `task_id` | string | 任务 ID |

#### 响应字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_id` | string | 任务 ID |
| `status` | string | 固定为 `"cancelled"` |

#### 响应示例

```json
{
  "task_id": "a1b2c3d4e5f6",
  "status": "cancelled"
}
```

#### 错误响应（HTTP 404）

```json
{
  "detail": "任务不存在: a1b2c3d4e5f6"
}
```

---

## 典型调用流程

```
1. POST /api/v1/tasks       → 拿到 task_id
2. GET  /api/v1/tasks/{id}   → 轮询（建议间隔 3-5 秒）
   ├── status=running        → 继续轮询
   ├── status=completed      → 从 result.plan_markdown 取最终方案
   └── status=failed         → 从 error 查看失败原因
3. DELETE /api/v1/tasks/{id} → 随时可取消
```
