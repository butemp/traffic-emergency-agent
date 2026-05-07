# 交通应急指挥大模型 HTTP API 接口文档

> 版本：v1.0（草案）
> 基础路径：`/api/v1`

---

## 一、总体设计

### 交互模式

采用 **异步任务 + 轮询** 模式：

```
调用方                           服务端
  │                               │
  │  POST /tasks                  │
  │  (提交灾情描述)          ──────►│  创建任务，后台执行
  │◄──────────────────────────────│  返回 task_id
  │                               │
  │  GET /tasks/{task_id}         │
  │  (轮询状态)              ──────►│
  │◄──────────────────────────────│  返回当前状态/进度
  │        ...                    │
  │  GET /tasks/{task_id}         │
  │  (轮询状态)              ──────►│
  │◄──────────────────────────────│  返回完整结果
  │                               │
```

### 任务生命周期

```
pending → running → completed
                  ↘ failed
```

| 状态 | 说明 |
|------|------|
| `pending` | 任务已创建，排队中 |
| `running` | Agent 正在执行（工具调用 / 方案生成 / 审核中） |
| `completed` | 最终方案已生成并通过审核 |
| `failed` | 执行失败（模型异常/超时等） |

---

## 二、接口列表

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/tasks` | 创建应急处置方案生成任务 |
| GET | `/api/v1/tasks/{task_id}` | 查询任务状态与结果 |
| GET | `/api/v1/tasks` | 查询任务列表 |
| DELETE | `/api/v1/tasks/{task_id}` | 取消/删除任务 |
| GET | `/api/v1/health` | 服务健康检查 |

---

## 三、接口详细定义

### 3.1 创建任务

```
POST /api/v1/tasks
Content-Type: application/json
```

#### 请求体

```json
{
  "incident_description": "G72高速K85公里处发生三车追尾事故，造成2人受伤3人被困，双向交通中断，现场有燃油泄漏",

  "incident_info": {
    "incident_type": "交通事故",
    "location_text": "G72高速K85公里处",
    "location_coords": {
      "longitude": 108.320,
      "latitude": 22.845
    },
    "time_text": "2026-05-08 14:30",
    "casualty_status": "2人受伤、3人被困",
    "scene_status": "双向交通中断，现场有燃油泄漏",
    "hazmat_involved": true,
    "hazmat_type": "燃油",
    "vehicles_involved": "三辆车",
    "road_info": "G72泉南高速"
  },

  "media_urls": [
    "https://example.com/scene_photo_1.jpg"
  ],

  "config": {
    "model": "deepseek-v3.2",
    "max_iterations": 24,
    "skip_expert_search": false,
    "skip_route_planning": false
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `incident_description` | string | **是** | 灾情自然语言描述，Agent 会自动提取结构化信息 |
| `incident_info` | object | 否 | 预结构化灾情信息，提供后可跳过部分 INTAKE 推断 |
| `incident_info.incident_type` | string | 否 | 事故类型：交通事故/危化品泄漏/火灾/地质灾害/洪涝 |
| `incident_info.location_text` | string | 否 | 位置文本描述 |
| `incident_info.location_coords` | object | 否 | 经纬度坐标 `{longitude, latitude}` |
| `incident_info.time_text` | string | 否 | 事发时间 |
| `incident_info.casualty_status` | string | 否 | 伤亡情况描述 |
| `incident_info.scene_status` | string | 否 | 现场状态 |
| `incident_info.hazmat_involved` | boolean | 否 | 是否涉及危化品 |
| `incident_info.hazmat_type` | string | 否 | 危化品类型 |
| `incident_info.vehicles_involved` | string | 否 | 涉及车辆 |
| `incident_info.road_info` | string | 否 | 路段信息 |
| `media_urls` | string[] | 否 | 现场图片/视频 URL 列表，支持 jpg/png/mp4 |
| `config` | object | 否 | 运行时配置 |
| `config.model` | string | 否 | 指定模型，默认使用服务端配置 |
| `config.max_iterations` | integer | 否 | 最大工具调用迭代次数，默认 24 |
| `config.skip_expert_search` | boolean | 否 | 是否跳过专家搜索，默认 false |
| `config.skip_route_planning` | boolean | 否 | 是否跳过路径规划，默认 false |

#### 响应 — 201 Created

```json
{
  "task_id": "task_20260508_143022_12345",
  "status": "pending",
  "created_at": "2026-05-08T14:30:22Z",
  "message": "任务已创建，请通过 GET /api/v1/tasks/{task_id} 查询进度"
}
```

---

### 3.2 查询任务状态与结果

```
GET /api/v1/tasks/{task_id}
```

#### 响应 — 运行中 (200 OK)

```json
{
  "task_id": "task_20260508_143022_12345",
  "status": "running",
  "created_at": "2026-05-08T14:30:22Z",

  "progress": {
    "phase": "PLAN_GENERATION",
    "iteration": 8,
    "max_iterations": 24,
    "tools_called": [
      "geocode_address",
      "get_weather_by_location",
      "check_traffic_status",
      "evaluate_incident_severity",
      "get_emergency_plan",
      "search_emergency_resources",
      "optimize_dispatch_plan",
      "search_experts"
    ],
    "current_action": "正在执行资源调度路径规划",
    "pipeline_status": null
  }
}
```

#### 响应 — 方案生成中 (200 OK)

```json
{
  "task_id": "task_20260508_143022_12345",
  "status": "running",
  "created_at": "2026-05-08T14:30:22Z",

  "progress": {
    "phase": "OUTPUT",
    "iteration": 12,
    "max_iterations": 24,
    "tools_called": ["..."],
    "current_action": "正在生成最终方案（章节化流水线）",
    "pipeline_status": {
      "completed_sections": [
        "一、事件概述",
        "二、响应定级",
        "三、指挥架构"
      ],
      "current_section": "四、预警发布",
      "total_sections": 9,
      "review_round": 1,
      "max_review_rounds": 5
    }
  }
}
```

#### 响应 — 完成 (200 OK)

```json
{
  "task_id": "task_20260508_143022_12345",
  "status": "completed",
  "created_at": "2026-05-08T14:30:22Z",
  "completed_at": "2026-05-08T14:35:47Z",
  "duration_seconds": 325,

  "result": {
    "plan_markdown": "# 标准化应急指挥方案\n\n> 生成时间：...\n\n### 一、事件概述\n\n...",

    "sections": {
      "一、事件概述": "### 一、事件概述\n\n| 字段 | 内容 |\n|...",
      "二、响应定级": "### 二、响应定级\n\n...",
      "三、指挥架构": "...",
      "四、预警发布": "...",
      "五、处置行动方案": "...",
      "六、资源调度方案": "...",
      "七、信息报送与新闻发布": "...",
      "八、风险提示与注意事项": "...",
      "九、依据引用": "..."
    },

    "review": {
      "passed": true,
      "score": 88,
      "review_rounds": 2,
      "summary": "方案满足标准化格式，内容充实"
    }
  },

  "process_data": {
    "incident_info": {
      "incident_type": "交通事故",
      "severity": "high",
      "incident_category": "高速公路事故",
      "disaster_type": "车辆事故",
      "scene_type": "高速公路多车追尾",
      "response_level": "III级",
      "response_level_reason": "造成2人受伤3人被困，双向交通中断",
      "location_text": "G72高速K85公里处",
      "location_coords": {"longitude": 108.320, "latitude": 22.845},
      "casualty_status": "2人受伤、3人被困",
      "scene_status": "双向交通中断，现场有燃油泄漏"
    },

    "environment": {
      "formatted_address": "广西壮族自治区来宾市...",
      "weather": {"temperature": "28℃", "weather": "多云", "wind": "东南风3级"},
      "traffic": {"status": "拥堵", "description": "..."}
    },

    "resources": [
      {
        "type": "warehouse",
        "name": "来宾应急仓库",
        "distance_km": 12.5,
        "materials_summary_zh": {
          "警示防护设备": [{"name": "锥桶", "quantity": 50, "unit": "个"}]
        },
        "contact": {"name": "张三", "phone": "139xxxx1234"}
      }
    ],

    "experts": [
      {
        "name": "李教授",
        "work_unit": "广西交通科学研究院",
        "specialty_field": "公路安全",
        "phone": "138xxxx5678"
      }
    ],

    "tool_calls": [
      {
        "tool_name": "geocode_address",
        "success": true,
        "arguments": {"address": "G72高速K85公里处"},
        "result_preview": "{\"longitude\": 108.320, \"latitude\": 22.845}"
      },
      {
        "tool_name": "get_weather_by_location",
        "success": true,
        "arguments": {"longitude": 108.320, "latitude": 22.845},
        "result_preview": "{\"temperature\": \"28℃\", \"weather\": \"多云\"}"
      }
    ],

    "risk_assessment": {
      "overall_score": 75,
      "risk_level": "较高风险",
      "suggestions": ["加强现场警戒防范二次事故", "关注燃油泄漏风险"]
    },

    "knowledge_refs": [
      {
        "source_type": "emergency_plan",
        "title": "广西壮族自治区交通运输综合应急预案",
        "module": "response_measures",
        "excerpt": "..."
      }
    ]
  }
}
```

#### 响应 — 失败 (200 OK)

```json
{
  "task_id": "task_20260508_143022_12345",
  "status": "failed",
  "created_at": "2026-05-08T14:30:22Z",
  "failed_at": "2026-05-08T14:33:12Z",

  "error": {
    "code": "MODEL_TIMEOUT",
    "message": "模型调用超时，请稍后重试",
    "phase": "PLAN_GENERATION",
    "iteration": 5
  }
}
```

#### 响应 — 任务不存在 (404)

```json
{
  "error": {
    "code": "TASK_NOT_FOUND",
    "message": "任务不存在: task_xxx"
  }
}
```

---

### 3.3 查询任务列表

```
GET /api/v1/tasks?status=running&limit=20&offset=0
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 按状态过滤：pending/running/completed/failed |
| `limit` | integer | 每页数量，默认 20，最大 100 |
| `offset` | integer | 偏移量，默认 0 |

#### 响应 — 200 OK

```json
{
  "total": 42,
  "limit": 20,
  "offset": 0,
  "tasks": [
    {
      "task_id": "task_20260508_143022_12345",
      "status": "completed",
      "created_at": "2026-05-08T14:30:22Z",
      "completed_at": "2026-05-08T14:35:47Z",
      "incident_summary": "G72高速K85公里处三车追尾，2人受伤3人被困"
    }
  ]
}
```

---

### 3.4 取消/删除任务

```
DELETE /api/v1/tasks/{task_id}
```

#### 响应 — 200 OK

```json
{
  "task_id": "task_20260508_143022_12345",
  "status": "cancelled",
  "message": "任务已取消"
}
```

---

### 3.5 健康检查

```
GET /api/v1/health
```

#### 响应 — 200 OK

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "model": "deepseek-v3.2",
  "uptime_seconds": 86400,
  "active_tasks": 3,
  "capabilities": {
    "gaode_api": true,
    "rag_enabled": true,
    "expert_search": true,
    "route_planning": true,
    "media_caption": true
  }
}
```

---

## 四、错误码

| HTTP 状态码 | error.code | 说明 |
|------------|------------|------|
| 400 | `INVALID_REQUEST` | 请求参数不合法 |
| 400 | `MISSING_DESCRIPTION` | 缺少 incident_description |
| 404 | `TASK_NOT_FOUND` | 任务不存在 |
| 409 | `TASK_ALREADY_RUNNING` | 任务正在执行，不可重复提交 |
| 429 | `RATE_LIMITED` | 请求过于频繁 |
| 500 | `INTERNAL_ERROR` | 服务端内部错误 |
| 500 | `MODEL_TIMEOUT` | 模型调用超时 |
| 500 | `MODEL_ERROR` | 模型返回异常 |
| 503 | `SERVICE_UNAVAILABLE` | 服务不可用（模型加载中/维护中） |

---

## 五、调用示例

### Python

```python
import requests
import time

BASE_URL = "http://localhost:8080/api/v1"

# 1. 创建任务
resp = requests.post(f"{BASE_URL}/tasks", json={
    "incident_description": (
        "G72高速K85公里处发生三车追尾事故，"
        "造成2人受伤3人被困，双向交通中断，现场有燃油泄漏"
    ),
})
task_id = resp.json()["task_id"]
print(f"任务已创建: {task_id}")

# 2. 轮询等待完成
while True:
    resp = requests.get(f"{BASE_URL}/tasks/{task_id}")
    data = resp.json()
    status = data["status"]

    if status == "running":
        progress = data.get("progress", {})
        print(f"  进度: {progress.get('phase')} | 迭代 {progress.get('iteration')}")
        time.sleep(5)  # 建议 3-5 秒轮询一次
        continue

    if status == "completed":
        result = data["result"]
        print("方案生成完成!")
        print(f"审核评分: {result['review']['score']}")

        # 获取 Markdown 全文
        with open("plan.md", "w") as f:
            f.write(result["plan_markdown"])

        # 获取中间过程数据
        process = data["process_data"]
        print(f"调用工具: {len(process['tool_calls'])} 次")
        print(f"可用资源: {len(process['resources'])} 个")
        break

    if status == "failed":
        print(f"任务失败: {data['error']['message']}")
        break
```

### cURL

```bash
# 创建任务
curl -X POST http://localhost:8080/api/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{"incident_description": "G72高速K85公里处发生三车追尾"}'

# 查询状态
curl http://localhost:8080/api/v1/tasks/task_20260508_143022_12345
```

---

## 六、轮询建议

| 阶段 | 建议间隔 | 说明 |
|------|---------|------|
| `pending` | 1-2 秒 | 排队阶段较短 |
| `running` (工具调用中) | 3-5 秒 | 工具调用阶段最耗时 |
| `running` (方案生成中) | 5-10 秒 | Pipeline 逐章生成中 |

典型任务耗时参考：
- 简单事故（III级）：2-4 分钟
- 复杂事故（I/II级，危化品等）：4-8 分钟

---

## 七、技术实现建议

### 推荐技术栈

```
FastAPI (异步 HTTP)  +  Celery/asyncio.Queue (任务队列)  +  Redis (状态存储)
```

### 核心改造点

1. **抽取 Agent 执行逻辑**：将 `web_app.py` 中 `@cl.on_message` 内的 Agent 主循环抽成独立的 `async def run_task(task_id, params)` 函数
2. **任务状态存储**：用 Redis 存储每个 task 的 `status`、`progress`、`result`，支持轮询读取
3. **进度上报**：在工具调用、阶段推进、Pipeline 章节生成完成时更新 Redis 中的 `progress`
4. **结果组装**：任务完成后从 `TaskState`、`FinalPlanPipelineResult` 中提取所有字段组装响应
5. **并发控制**：限制同时运行的任务数（受模型 API 并发和 GPU 资源限制）
