# 交通应急指挥大模型 HTTP API 接口文档

> 版本：v1.0 | 基础路径：`/api/v1`

## 交互模式

采用 **异步任务 + 轮询** 模式：

```
POST /tasks          → 拿到 task_id
GET  /tasks/{id}     → 轮询（建议 3-5 秒）
  ├── running        → 继续轮询
  ├── completed      → 从 result.plan_markdown 取方案
  └── failed         → 从 error 查看原因
DELETE /tasks/{id}   → 随时可取消
```

---

## 接口列表

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/tasks` | 创建方案生成任务 |
| GET | `/api/v1/tasks/{task_id}` | 查询任务状态与结果 |
| GET | `/api/v1/tasks` | 查询任务列表 |
| DELETE | `/api/v1/tasks/{task_id}` | 取消任务 |
| GET | `/api/v1/health` | 健康检查 |

---

## 1. 创建任务

```
POST /api/v1/tasks
```

只有 `incident_description` 是必填项，其余都可省略：

```json
{
  "incident_description": "G72高速K85处三车追尾，2人受伤3人被困，双向中断，有燃油泄漏",
  "incident_info": {
    "incident_type": "交通事故",
    "location_text": "G72高速K85公里处",
    "casualty_status": "2人受伤、3人被困",
    "scene_status": "双向交通中断",
    "hazmat_involved": true,
    "hazmat_type": "燃油"
  },
  "config": {
    "OPENAI_API_KEY": "sk-xxx",
    "OPENAI_MODEL": "deepseek-ai/DeepSeek-V3.2",
    "OPENAI_BASE_URL": "https://ai.gxtri.cn/llm/v1"
  }
}
```

响应（201）：

```json
{
  "task_id": "a1b2c3d4e5f6",
  "status": "pending",
  "created_at": "2026-05-08T14:30:22Z"
}
```

---

## 2. 查询任务状态

```
GET /api/v1/tasks/{task_id}
```

**运行中**返回实时进度：

```json
{
  "task_id": "a1b2c3d4e5f6",
  "status": "running",
  "progress": {
    "phase": "PLAN_GENERATION",
    "iteration": 8,
    "tools_called": ["geocode_address", "get_weather_by_location", "evaluate_incident_severity", "..."],
    "current_action": "正在调用 search_emergency_resources",
    "pipeline_status": ""
  }
}
```

**完成时**返回最终方案 + 过程数据：

```json
{
  "task_id": "a1b2c3d4e5f6",
  "status": "completed",
  "result": {
    "plan_markdown": "# 标准化应急指挥方案\n\n### 一、事件概述\n...",
    "sections": {
      "一、事件概述": "...",
      "二、响应定级": "...",
      "三、指挥架构": "...",
      "四、预警发布": "...",
      "五、处置行动方案": "...",
      "六、资源调度方案": "...",
      "七、信息报送与新闻发布": "...",
      "八、风险提示与注意事项": "...",
      "九、依据引用": "..."
    },
    "review": { "passed": true, "score": 88, "summary": "方案整体结构完整" }
  },
  "process_data": {
    "incident_info": { "incident_type": "交通事故", "severity": "high", "response_level": "III级", "..." : "..." },
    "environment":   { "formatted_address": "广西壮族自治区...", "weather": {}, "traffic": {} },
    "resources":     [{ "type": "warehouse", "name": "来宾应急仓库", "distance_km": 12.5 }],
    "experts":       [{ "name": "李教授", "specialty_field": "公路安全" }],
    "tool_calls":    [{ "tool_name": "geocode_address", "success": true }],
    "risk_assessment": [{ "overall_score": 75, "risk_level": "较高风险" }],
    "knowledge_refs":  [{ "source_type": "emergency_plan", "title": "广西交通运输综合应急预案" }]
  }
}
```

**失败时**：

```json
{
  "status": "failed",
  "error": { "code": "LLM_ERROR", "message": "模型调用超时", "phase": "PLAN_GENERATION", "iteration": 5 }
}
```

---

## 3. 任务列表

```
GET /api/v1/tasks?status=running&limit=20&offset=0
```

---

## 4. 取消任务

```
DELETE /api/v1/tasks/{task_id}
```

---

## 5. 健康检查

```
GET /api/v1/health
```

---

## 错误码

| error.code | 说明 |
|------------|------|
| `CANCELLED` | 任务被取消 |
| `MAX_ITERATIONS` | Agent 迭代超上限（24 轮） |
| `LLM_ERROR` | 模型调用失败 |
| `PIPELINE_ERROR` | 章节化 Pipeline 生成失败 |
| `INTERNAL_ERROR` | 其他内部异常 |

---

## 调用示例

### Python

```python
import requests, time

BASE = "http://localhost:8000/api/v1"

# 创建任务
task_id = requests.post(f"{BASE}/tasks", json={
    "incident_description": "G72高速K85处三车追尾，2人受伤",
}).json()["task_id"]

# 轮询
while True:
    data = requests.get(f"{BASE}/tasks/{task_id}").json()
    if data["status"] == "completed":
        print(data["result"]["plan_markdown"][:500])
        break
    if data["status"] == "failed":
        print(data["error"]["message"])
        break
    print(f"[{data['status']}] {data['progress']['current_action']}")
    time.sleep(5)
```

### cURL

```bash
# 创建任务
curl -X POST http://localhost:8000/api/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{"incident_description": "G72高速K85处三车追尾，2人受伤"}'

# 查询状态
curl http://localhost:8000/api/v1/tasks/{task_id}

# 取消任务
curl -X DELETE http://localhost:8000/api/v1/tasks/{task_id}
```
