# HTTP API 接口参考

Base URL: `http://<host>:8000/api/v1` （随 Chainlit 一起启动）

---

## 1. 健康检查

`GET /api/v1/health`

```json
{ "status": "healthy", "tasks_total": 3, "tasks_running": 1 }
```

---

## 2. 创建任务

`POST /api/v1/tasks`

只有 `incident_description` 是必填项。不传 `config` 时使用默认模型（deepseek-ai/DeepSeek-V3.2）。

```json
{
  "incident_description": "G72高速K85处三车追尾，2人受伤"
}
```

响应（201）：

```json
{ "task_id": "a1b2c3d4e5f6", "status": "pending", "created_at": "..." }
```

---

## 3. 查询任务状态

`GET /api/v1/tasks/{task_id}`

任务状态：`pending` → `running` → `completed` / `failed` / `cancelled`

**运行中**：

```json
{
  "status": "running",
  "progress": {
    "phase": "PLAN_GENERATION",
    "iteration": 8,
    "tools_called": ["geocode_address", "get_weather_by_location", "..."],
    "current_action": "正在调用 search_emergency_resources"
  }
}
```

**完成时**：

```json
{
  "status": "completed",
  "result": {
    "plan_markdown": "# 标准化应急指挥方案\n...",
    "sections": { "一、事件概述": "...", "二、响应定级": "...", "...": "..." },
    "structured_sections": {
      "emergency_disposal_overview": {
        "fields_zh": {
          "一、事件现场基本情况": "...",
          "二、预案匹配与组织预警和响应": "...",
          "三、物资装备与调度": "...",
          "四、处置流程建议": "...",
          "五、次生风险": "..."
        }
      },
      "emergency_disposal_detail": {
        "fields_zh": {
          "事件地点": "...",
          "天气情况": "...",
          "事件简述": "...",
          "周边环境": "...",
          "主要影响": "..."
        }
      },
      "material_equipment_dispatch": {
        "items": [
          {
            "required_material": "路锥、标志牌",
            "recommended_dispatch_source": "北海应急仓库",
            "distance": "1.76km",
            "estimated_arrival_time": "5分钟",
            "location_contact_info": "黄世鹏 / 13978923335",
            "resource_gap": ""
          }
        ]
      }
    },
    "review": { "passed": true, "score": 88 }
  },
  "process_data": {
    "incident_info": { "incident_type": "交通事故", "response_level": "III级" },
    "environment": { "weather": {}, "traffic": {} },
    "resources": [], "experts": [], "tool_calls": [],
    "risk_assessment": [], "knowledge_refs": []
  }
}
```

`structured_sections` 当前固定包含：

- `emergency_disposal_overview`：事件现场基本情况概述、预案匹配与组织预警和响应概述、物资装备与调度概述、处置流程建议概述、次生风险概述
- `emergency_disposal_detail`：事件地点、天气情况、事件简述、周边环境、主要影响
- `plan_warning_response`：匹配预案、事件等级、预警发布、启动响应、判断依据
- `emergency_organization`：工作组、牵头单位、主要职责
- `material_equipment_dispatch`：所需物资、推荐调度来源、距离、预计到达时间、地点/联系人信息、资源缺口
- `disposal_process_recommendations`：序号、行动、责任单位、协同单位、引用依据
- `secondary_risks`：触发条件、风险描述、影响后果、应对措施、责任单位
- `reference_basis`：依据类型、依据名称、引用章节/模块、引用内容摘要、支撑决策

**失败时**：

```json
{
  "status": "failed",
  "error": { "code": "LLM_ERROR", "message": "模型调用超时" }
}
```

错误码：`CANCELLED` / `MAX_ITERATIONS` / `LLM_ERROR` / `PIPELINE_ERROR` / `INTERNAL_ERROR`

---

## 4. 任务列表

`GET /api/v1/tasks?status=running&limit=20&offset=0`

---

## 5. 取消任务

`DELETE /api/v1/tasks/{task_id}`

---

## 典型流程

```
POST /tasks          → 拿到 task_id
GET  /tasks/{id}     → 轮询（建议 3-5 秒）直到 completed / failed
DELETE /tasks/{id}   → 随时可取消
```
