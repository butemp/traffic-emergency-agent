# 交接文档 — 交通应急 Agent 项目

> **接手日期**：2026-05-24
> **上次主要改动**：API 侧工具兜底、预案管理 API、最终方案 7 章节重构
> **接手人请先通读本文档，然后按"待办事项"章节执行**

---

## 0. 5 分钟速览

这是个**交通应急指挥智能体**项目。把"事件描述"丢进去，跑完 LLM + 工具链，吐出一份 **7 章节标准化应急指挥方案**。

```
事件描述 → Agent (LLM + 16+ 个工具)
            ├─ 定级 (evaluate_incident_severity)
            ├─ 取预案 (get_emergency_plan)         ← 数据源：data/预案/parsered_data/
            ├─ 找资源 (search_emergency_resources)  ← 数据源：data/仓库和队伍的物资数据/
            ├─ 找专家 (search_experts)              ← 数据源：data/专家数据/expert_info.xls
            ├─ 高德 API (geocode/天气/路径)
            └─ ...
          ↓
       FinalPlanPipeline (逐章生成+审核)
          ↓
       【应急处置总览】 + 【应急处置详情】(7 章节)
```

**3 个入口**：
- `web_app.py` — Chainlit Web 交互（兜底机制完整）
- `src/api/` — HTTP API（FastAPI，本次重点改造对象）
- `main.py` — CLI（基本未改）

---

## 1. 上一阶段已完成的事情

### 1.1 test_skill/ 独立简化版（独立项目，**不要再改**）

`/Users/jiawen/mywork/traffic-emergency-agent/test_skill/` — 完全自包含的 Claude Code Skill 版。用户已明确说独立于主项目。

### 1.2 数据源切换：plan_X.json → parsered_data

| 文件 | 改动 |
|---|---|
| `src/emergency_plans/service.py` | 完全重写。读 `data/预案/parsered_data/*.json` + `data/预案/plan_index.json`。支持 module 别名 / 中文 section_path / 关键词搜索 3 种模式。**新增 `reload()` 方法** |
| `src/emergency_plans/severity_evaluator.py` | 适配新 `get_grading_bundle` 返回结构 |
| `src/tools/get_emergency_plan.py` | 参数扩展为 `module` / `section_path` / `search_keyword` 三选一 |
| `src/agent/agent.py:_update_task_state_from_tool_result` | 新返回字段（`content_text` / `hit_path` / `fallback_chain`） |
| `data/regulations/data/plan_*.json` | **保留但代码不再读** |
| `data/预案/plan_index.json` | **新建**。scene→plan_name 路由、44 个 section 别名、灾害补充预案、level→响应措施子节映射 |

### 1.3 最终方案：9 章节 → 5 总览 + 7 详情

按用户精确规范重构。**章节标题字面必须完全一致**：

```
### 【应急处置总览】（5 项概述）

### 【应急处置详情】（7 章节固定表）
### 一、事件现场基本情况              字段|内容 (5 行)
### 二、预案匹配与组织预警和响应      字段|内容 (5 行)
### 三、应急组织机构                  工作组|牵头单位|主要职责 (≥7 行)
### 四、物资装备与调度                所需物资|推荐调度来源|距离|预计到达时间|地点、联系人信息|资源缺口 (≥3 行)
### 五、处置流程建议(包括后期处置、新闻发布)   序号|行动|责任单位|协同单位|引用依据 (≥10 行)
### 六、次生风险                      触发条件|风险描述|影响后果|应对措施|责任单位 (≥5 条)
### 七、引用依据                      依据类型|依据名称|引用章节/模块|引用内容摘要|支撑决策
```

涉及文件：
- `src/agent/final_plan_pipeline.py` — `SECTION_SPECS`、`_merge_sections`、`_build_overview_markdown`、`build_structured_sections`、`_map_feedback_to_sections`、`repair_from_review`
- `src/agent/final_plan_reviewer.py` — SYSTEM_PROMPT 重写
- `src/skills/master_flow/prompt.md` — 章节列表 + 各章节固定表头描述
- `src/skills/output_detail_review/prompt.md` — 详细度规范完全重写
- `src/utils/structured_sections.py` — API 字段 schema（早就对齐了）
- `web_app.py` — `STANDARD_PLAN_SECTIONS`、`SECTION_MIN_LENGTHS`、`SECTION_DETAIL_REQUIREMENTS`、各检查器、所有"9 章节"prompt → 7 章节
- `src/api/task_runner.py` — `API_MODE_SYSTEM_PROMPT` 等所有"9 章节"→"7 章节"

### 1.4 API 端工具自动兜底（修复"暂未获取"）

**问题**：Web 端有 `_auto_call_missing_critical_tools` 兜底，API 端没有 → LLM 跳过工具时 task_state 空 → 方案输"暂未获取"。

**修复**：`src/api/task_runner.py` 新增 `_ensure_critical_tools_called(agent)`，在 `_run_final_pipeline` 入口必调。覆盖：

| 工具 | 兜底策略 |
|---|---|
| `geocode_address` | 缺坐标且有 location_text 时自动地理编码 |
| `search_emergency_resources` | 按事件类型选 categories；**半径自适应 50→100→200→500km**，直到搜出非零 |
| `optimize_dispatch_plan` | 资源搜过了就自动出梯队方案 |
| `search_experts` | 按事件类型搜；**命中 0 时 fallback 通用关键词**（交通安全/应急管理/安全管理/公路/应急） |

### 1.5 3 个新预案管理 API

| 接口 | 用途 |
|---|---|
| `GET /api/v1/plans` | 列出已加载预案（标题/文件/发布单位/被哪些 scene 路由到） |
| `POST /api/v1/plans` | 上传新预案 JSON（multipart），自动校验+保存+加路由+热加载 |
| `POST /api/v1/plans/reload` | 手动重新扫盘 |

涉及文件：`src/api/routes.py`、`src/emergency_plans/service.py:reload()`。**端到端 7 项测试已过**。

---

## 2. 待办事项（按优先级）

### 🔴 P0 紧急 — 修复 4 份预案的封面字段

**症状**：4 份预案路由失败、`list_plans` 显示标题异常（变成"3.广西..."这种带前缀编号的形式）。

**根因**：service 加载预案时，`封面.标题` 缺失会 fallback 到文件名 stem 作为标题，**和 `plan_index.json` 里 `preferred_plan_name` 匹配不上**，导致路由失败。

| 文件 | 当前封面状态 | 期望标题（必须和 plan_index.json 完全一致） | 影响的 scene |
|---|---|---|---|
| `3.广西壮族自治区高速公路突发事件应急预案.json` | 有封面但 `标题` 是"……印发……通知" | `广西壮族自治区高速公路突发事件应急预案` | **EXPRESSWAY**（高速主预案，最常用） |
| `7.广西壮族自治区西江黄金水道通航突发事件应急预案.json` | `封面: null` | `广西壮族自治区西江黄金水道通航突发事件应急预案` | WATERWAY_XIJIANG |
| `10.广西城市轨道交通运 营突发事件应急预案.json` | `封面: null` | `广西城市轨道交通运营突发事件应急预案`（plan_index 里**无空格**，文件名"运 营"有空格） | URBAN_RAIL |
| `16.广西壮族自治区交通运输厅网络安全事件应急预案.json` | `封面: null` | `广西壮族自治区交通运输厅网络安全事件应急预案` | CYBER（灾害补充预案） |

#### 修复步骤

**每份文件做一次**：

1. 打开对应 JSON 文件
2. 在最顶层添加（或修正）`封面` 字段。**`标题` 必须和上表"期望标题"完全一致**：

```json
{
  "封面": {
    "标题": "广西壮族自治区高速公路突发事件应急预案",
    "发布单位": "广西壮族自治区人民政府办公厅",
    "发布时间": "2018年2月13日"
  },
  ...原有其他字段保留不动
}
```

3. 对于 `3.json` 已经有 `封面` 但标题是"……通知"的情况，**只需要把 `标题` 字段的值改成 `广西壮族自治区高速公路突发事件应急预案`**，其他字段保留。

4. 跑下面命令自动检查 4 份是否都修好了：

```bash
cd /Users/jiawen/mywork/traffic-emergency-agent
PYTHONPATH=. /Users/jiawen/miniconda3/bin/python3 -c "
from src.emergency_plans import EmergencyPlanService
svc = EmergencyPlanService()
plans = {p['title']: p for p in svc.list_plans()}
expected = [
    '广西壮族自治区高速公路突发事件应急预案',
    '广西壮族自治区西江黄金水道通航突发事件应急预案',
    '广西城市轨道交通运营突发事件应急预案',
    '广西壮族自治区交通运输厅网络安全事件应急预案',
]
for t in expected:
    print(f'  {\"✓\" if t in plans else \"✗\"} {t}')
"
```

全部 ✓ 即成功。

5. 验证 `list_plans` API 现在所有 scene 都能命中：

```bash
curl -s http://localhost:8000/api/v1/plans | jq '.plans[] | select(.routed_scenes | length > 0) | {title, routed_scenes}'
```

### 🟡 P1 — 端到端 API 集成测试

修完 P0 后，跑一次完整 API 任务，确认：

1. **每个 scene 都能正确路由到自己的预案**（不再走 fallback）
2. **资源调度章节有真实数据**（不再"暂未获取"）
3. **专家章节有 3-5 位真实专家**

**测试脚本现成的**：`docs/api_examples/03_poll_task_status.py`

```bash
# 启动 API 服务（同 §4.2，必须用 chainlit 启动）
cd /Users/jiawen/mywork/traffic-emergency-agent
chainlit run web_app.py --host 0.0.0.0 --port 8000

# 另开终端跑测试
PYTHONPATH=. /Users/jiawen/miniconda3/bin/python3 docs/api_examples/03_poll_task_status.py
```

测试完会在 `docs/api_examples/` 下产出：
- `task_response_<id>_<时间戳>.json` — 本次任务完整响应存档
- `latest_task_response.json` — 始终指向最新一次

**验证清单**（打开 JSON 看以下字段）：
- [ ] `result.structured_sections.material_equipment_dispatch.items` 有 ≥3 行真实数据
- [ ] `result.structured_sections.emergency_organization.groups` 有 ≥7 个工作组
- [ ] `process_data.experts` 有 ≥3 位专家
- [ ] `result.structured_sections.reference_basis.references` 引用了实际预案章节路径

**用不同 scene 各跑一次**（修改 `incident_description` 触发不同事件类型）：
- 高速事故 → EXPRESSWAY
- 港口事故 → PORT
- 公路水运工程事故 → CONSTRUCTION
- 危化品泄漏 → 灾害补充预案 FLOOD

也可以批量跑 `data/test_Cases/all_cases.jsonl` 里的全部案例做回归测试。

### 🟡 P1 — `03_poll_task_status.py` 鲁棒性优化（可选但建议）

当前脚本有几个已知坑：

1. **`wait_task_done` 没有最大超时** — 服务卡死会无限挂
2. **轮询任何 HTTP 错误就崩** — 网络抖动会让脚本退出，但服务端任务还在跑
3. **Ctrl+C 不取消服务端任务** — 应在 KeyboardInterrupt 里 `DELETE /tasks/{id}`
4. **`pick_item` 只显示首条** — 调试时看不全

建议加：`max_wait_seconds=600` / 连续 ≥5 次 HTTP 失败再退出 / KeyboardInterrupt 处理 / `--show-all` 标志。

### 🟢 P2 — 加文件监听自动 reload（可选）

当前预案上传/修改后用 `POST /api/v1/plans/reload` 手动触发。要全自动可装 watchdog：

```bash
pip install watchdog
```

在 `src/api/routes.py` 或新文件加一个 `PlansChangeHandler`，监听 `data/预案/parsered_data/` 变化时调 `get_shared_plan_service().reload()`。

### 🟢 P2 — 专家库扩充（可选）

当前 `data/专家数据/expert_info.xls` 584 条，但某些领域专家可能不够：
- **CYBER（网络安全）** — 关键词匹配较少
- **PUBLIC_HEALTH（公共卫生）** — 同上

可以联系数据方扩充。或者在 `src/tools/expert_tools.py` 的 `INCIDENT_EXPERT_KEYWORDS` 加更多近义词扩展。

### 🟢 P2 — URBAN_RAIL 文件名空格问题（待观察）

`10.广西城市轨道交通运 营突发事件应急预案.json` 文件名带空格"运 营"。但 service 是按`封面.标题` 字段路由而不是按文件名，所以**文件名空格不影响匹配**。但建议把文件重命名去掉空格（同时保证标题正确），避免视觉混淆。

---

## 3. 关键架构指针

### 3.1 数据流（一次任务的生命周期）

```
HTTP POST /api/v1/tasks (incident_description)
  ↓ src/api/routes.py:create_task
  ↓ asyncio.create_task → src/api/task_runner.py:run_task
  ↓
  ├─ create_agent_for_api()  → src/agent/agent.py:Agent
  ├─ _inject_api_mode_prompt() → 注入"无人值守模式"指令
  └─ _run_agent_loop()  ← Agent 主循环
      ├─ INTAKE / SITUATIONAL_AWARENESS / PLAN_GENERATION 各阶段
      │   → 模型自由调工具（evaluate / get_plan / search_resources / search_experts / ...）
      ├─ 检测 final_output 或连续停住 → _run_final_pipeline()
      └─ _run_final_pipeline()
          ├─ ★ _ensure_critical_tools_called(agent) ← 兜底（本次新加的）
          ├─ FinalPlanPipeline.generate()  ← 7 章节逐章生成+审核
          └─ TaskResult 写入 task_store
  ↓
HTTP GET /api/v1/tasks/{task_id}
  ↓ src/api/routes.py:_build_status_response
  ↓ normalize_structured_sections() → 8 个 schema 字段保证齐全
  ↓
返回 plan_markdown + sections + structured_sections + process_data
```

### 3.2 关键文件清单

```
src/
├── agent/
│   ├── agent.py                  # Agent 主类，状态机 + 工具结果消费
│   ├── task_state.py             # TaskState 数据模型
│   ├── final_plan_pipeline.py    # ★ 7 章节生成+审核流水线
│   ├── final_plan_reviewer.py    # 全局方案审核
│   ├── skill_router.py           # 按阶段路由 skill prompt
│   └── ...
├── api/
│   ├── routes.py                 # ★ HTTP 路由 (含新加的 /plans 系列)
│   ├── task_runner.py            # ★ 异步任务执行 + 工具兜底
│   ├── models.py                 # Pydantic 模型
│   └── task_store.py             # 任务存储
├── emergency_plans/
│   ├── service.py                # ★ 预案服务（新版按 parsered_data）+ reload()
│   └── severity_evaluator.py     # 独立 LLM 定级器
├── tools/                        # 16+ 个工具，function-calling 暴露给 LLM
│   ├── get_emergency_plan.py
│   ├── evaluate_incident_severity.py
│   ├── resource_dispatch_tools.py
│   ├── expert_tools.py
│   ├── gaode_tools.py
│   └── ...
├── skills/                       # 阶段化 prompt + 工具白名单
│   ├── master_flow/prompt.md     # ★ 主流程编排（包含 7 章节规范）
│   ├── output_detail_review/prompt.md
│   ├── knowledge_retrieval/prompt.md
│   ├── resource_dispatch/prompt.md
│   └── ...
├── utils/
│   └── structured_sections.py    # API 返回字段 schema 规范化
└── providers/                    # LLM provider 抽象

data/
├── 预案/
│   ├── parsered_data/            # ★ 当前数据源（16 份预案 JSON）
│   └── plan_index.json           # ★ scene 路由 + section 别名
├── regulations/data/             # 老 plan_X.json，保留但不读
├── 仓库和队伍的物资数据/         # 资源调度数据源
├── 专家数据/expert_info.xls      # 专家库
├── test_Cases/all_cases.jsonl    # 测试案例（接手人可用作回归测试）
└── ...

docs/
├── HANDOVER.md                   # ← 本文档
├── API_DESIGN.md                 # API 响应结构说明
└── api_examples/
    ├── 03_poll_task_status.py    # 测试脚本
    └── API_REFERENCE.md
```

### 3.3 重要约定

1. **章节标题字面完全一致**：所有"七、引用依据" / "一、事件现场基本情况"等标题在 prompt、structured_sections.py、final_plan_pipeline.py 都必须字面一致，错一个字符整个章节匹配就失效
2. **章节固定表的列名不能改**：API 按列名做结构化提取，列名错了下游消费方收不到数据
3. **资源类别中文化**：3. **资源类别中文化**：WARNING / PPE / SIGN / VEHICLE / RESCUE / COMMS / DEICE / MATERIAL / FIRE / TOOL / OTHER 11 个英文 code 在最终方案里禁止出现，必须转中文（仓库工具已自动转换，但 prompt 仍要强调）
4. **建议性表述强制**：禁止"已通知/已派遣/已下达"等虚假执行话术，必须用"建议/拟派/应由人工联系"
5. **依据引用列填 hit_path**：`七、引用依据` 的"引用章节/模块"列必须填 `get_emergency_plan` 返回的 hit_path（如 `应急响应.处置措施.Ⅱ级应急响应处置措施`），不能写笼统的"第X节"

---

## 4. 运行环境

### 4.1 Python 环境

项目用 `/Users/jiawen/miniconda3/bin/python3`（Python 3.13），不是系统 Python。

依赖（已装）：
- `openai` (LLM client)
- `fastapi` + `python-multipart` (API 服务 + 文件上传)
- `chainlit` (Web UI)
- `requests` (HTTP 客户端)
- `xlrd==2.0.2` (读专家 xls)
- `PyYAML` (skill 配置)
- `pydantic` (数据模型)

新接手如发现缺包：
```bash
/Users/jiawen/miniconda3/bin/python3 -m pip install <pkg>
```

### 4.2 启动各服务

```bash
cd /Users/jiawen/mywork/traffic-emergency-agent
export GAODE_API_KEY=b78a07dde4df95ad9b9cb75a97cdf10c   # 已硬编码也可省略

# API 服务 + Web UI（同进程同端口，API 路由挂在 chainlit 的 fastapi_app 上）
chainlit run web_app.py --host 0.0.0.0 --port 8000
# 或直接用项目提供的脚本
./start_web.sh

# 验证 API 是否可用
curl -s http://localhost:8000/api/v1/health | jq

# CLI（不启服务，本地调试用）
PYTHONPATH=. /Users/jiawen/miniconda3/bin/python3 main.py interactive
```

> **不要用 `uvicorn web_app:app` 启动** — `web_app.py` 顶层没有暴露 `app`；
> API 路由是通过 `fastapi_app.include_router(api_router)` 挂到 chainlit 自己的 FastAPI 实例上的，
> 所以必须走 `chainlit run`，由 chainlit 把 fastapi_app 拉起来。

### 4.3 LLM 配置

默认走 DeepSeek（`src/providers/defaults.py` 硬编码）。要换：

```bash
export OPENAI_API_KEY=sk-xxx
export OPENAI_BASE_URL=https://api.deepseek.com/v1
export OPENAI_MODEL=deepseek-chat
```

---

## 5. 联系上下文 / 已知坑

### 5.1 用户偏好（聊天记录里反复强调的）

1. **不让 test_skill 和主项目互相影响** — 它们是独立的
2. **正确性 > 效率** — LLM 调用次数和推理时间都不是瓶颈，可以多调
3. **结果不能空** — 资源/专家必须有真实数据，不能"暂未获取"
4. **章节格式严格**："非必要的内容就不要加了"，简洁清晰优先

### 5.2 已知坑

1. **agent 主循环的 max_iterations=24** — 复杂任务可能不够，可以在 `src/api/task_runner.py:24` 调大
2. **`MAX_CONSECUTIVE_STALLS=3`** — 连续 3 轮无工具调用就强制进入 Pipeline。如果模型话痨爱碎碎念，会被提前打断
3. **资源搜索 50→500km 自适应** — 一定能搜到。但如果搜出来的资源距离 300+km，方案里要明确写"距离远，需评估时效"
4. **DeepSeek 偶尔泄漏 `<｜tool▁calls▁begin｜>` 这类 special token** — task_runner.py 已经有检测和重试机制，但偶有漏网
5. **`data/regulations/data/plan_*.json`** — 已经不读了，但**别误删**，万一新数据源出问题可以临时切回去

---

## 6. 推荐接手优先级

1. **第 1 天**：通读本文档 + 跑一遍 API 端到端验证（看是否复现"暂未获取"问题）
2. **第 2 天**：修 P0（4 份预案封面字段）
3. **第 3 天**：跑 P1 集成测试，对不同 scene 各验证一次
4. **第 4 天起**：按需做 P2 优化

---

## 7. 有问题问谁 / 看哪里

- **架构问题** → 看 `TECHNICAL_ARCHITECTURE.md` + 本文档
- **API 字段** → 看 `docs/API_DESIGN.md` + `src/api/models.py`
- **章节规范** → 看 `src/skills/master_flow/prompt.md` + `src/skills/output_detail_review/prompt.md`
- **预案数据结构** → 看 `data/预案/plan_index.json` 的 usage_notes 字段
- **测试案例** → `data/test_Cases/all_cases.jsonl`（10+ 个真实事件描述，可拿来批量测）

祝接手顺利。
