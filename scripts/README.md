# scripts/ — 本地数据查询 & 录入工具

主项目根目录下的 6 个独立 CLI 脚本，方便人工或外部系统**查询**本地知识库、**录入**新数据。所有脚本统一输出 UTF-8 JSON 到 stdout，错误信息到 stderr，便于程序消费。

> 这些脚本是面向运维/数据维护人员的，与 Agent 自身使用的工具（`src/tools/`）解耦。

## 目录

```
scripts/
├── README.md                      ← 本文件
├── _schemas.py                    ← 4 类数据的录入 schema + validate() 复用
├── query_plans.py                 ← 查预案
├── query_experts.py               ← 查专家
├── query_warehouses.py            ← 查仓库
├── query_teams.py                 ← 查救援队
├── admin.py                       ← 录入（add-plan / add-expert / add-warehouse / add-team）
└── examples/
    ├── add_plan_example.json      ← 预案录入样例
    ├── add_expert_example.json    ← 专家录入样例
    ├── add_warehouse_example.json ← 仓库录入样例
    └── add_team_example.json      ← 救援队录入样例
```

## 通用约定

- 所有脚本都**输出 UTF-8 JSON 到 stdout**；可以直接 `| jq` 或 `> result.json` 重定向
- 报错信息**输出到 stderr**，参数错误退出码 2，业务错误退出码 1，成功退出码 0
- 必须从**主项目根目录**运行（否则相对路径找不到数据）

## 1. 查询脚本

### 1.1 query_plans.py — 预案查询

```bash
python3 scripts/query_plans.py list                          # 列出全部预案
python3 scripts/query_plans.py scenes                        # 列出全部 scene 路由
python3 scripts/query_plans.py get --scene EXPRESSWAY        # 按 scene 取预案
python3 scripts/query_plans.py toc --scene EXPRESSWAY --depth 2
python3 scripts/query_plans.py show --scene EXPRESSWAY --module grading_criteria
python3 scripts/query_plans.py show --scene CONSTRUCTION --section "组织体系.自治区应急指挥机构.应急工作组"
python3 scripts/query_plans.py show --scene CONSTRUCTION --search "抚恤"
```

### 1.2 query_experts.py — 专家查询

```bash
python3 scripts/query_experts.py list --limit 5
python3 scripts/query_experts.py get --id <uuid>
python3 scripts/query_experts.py search --keyword "高速公路"
python3 scripts/query_experts.py filter --specialty "应急管理" --title "高级"
```

数据源优先级：`data/专家数据/expert_info.json`（若已通过 admin.py 迁移生成）> `expert_info.xls`。

### 1.3 query_warehouses.py — 仓库查询

```bash
python3 scripts/query_warehouses.py list --limit 5 --with-coords-only
python3 scripts/query_warehouses.py get --id <warehouse_id>
python3 scripts/query_warehouses.py search --keyword "南宁"
python3 scripts/query_warehouses.py filter --category WARNING
python3 scripts/query_warehouses.py nearby --lng 108.32 --lat 22.84 --radius 30
```

### 1.4 query_teams.py — 救援队查询

```bash
python3 scripts/query_teams.py list --limit 5 --with-coords-only
python3 scripts/query_teams.py get --id <team_id>
python3 scripts/query_teams.py search --keyword "抢修"
python3 scripts/query_teams.py filter --specialty "清障"
python3 scripts/query_teams.py nearby --lng 108.32 --lat 22.84 --radius 50
```

## 2. 录入脚本 — admin.py

```bash
python3 scripts/admin.py add-plan       --file <X.json> [--overwrite] [--reload]
python3 scripts/admin.py add-expert     --file <X.json> [--reload]
python3 scripts/admin.py add-warehouse  --file <X.json> [--reload]
python3 scripts/admin.py add-team       --file <X.json> [--reload]
```

- **`--file`**：录入数据的 JSON 文件路径；格式严格按 `scripts/examples/` 下的样例
- **`--overwrite`**（仅 `add-plan`）：同标题预案已存在时是否覆盖；不传则报错
- **`--reload`**：录入成功后尝试 POST `http://localhost:8000/api/v1/plans/reload` 让运行中的 API 服务立即看到新数据；服务没启则仅警告不报错

校验失败时 stderr 会输出**所有错误清单**（多条），退出码 1。

### 录入字段速查

| 数据 | 必填字段 | 自动生成 | 唯一性键 |
|---|---|---|---|
| **预案** | `封面.标题` | 文件名按标题保存 | `封面.标题` |
| **专家** | `name` + (`phone` 或 `email`) | `id` (uuid) + 审计字段 | `id` |
| **仓库** | `warehouse_name`、`latitude/longitude`、`categories`（非空）、`contact_phone` | `warehouse_id` (uuid) + `material_*_count` | `warehouse_id` |
| **救援队** | `team_name`、`latitude/longitude`、(`leader_phone` 或 `jurisdiction_phone`) | `team_id` (uuid) + 默认审计字段 | `team_id` |

仓库 `categories` 合法枚举：`SIGN / WARNING / PPE / FIRE / TOOL / VEHICLE / MATERIAL / RESCUE / COMMS / DEICE / OTHER`

### 录入示例

```bash
# 1. 拷贝样例 + 改字段
cp scripts/examples/add_expert_example.json /tmp/new_expert.json
vim /tmp/new_expert.json     # 改成你要录入的真实数据

# 2. 录入（如服务正在跑，加 --reload 立即生效）
python3 scripts/admin.py add-expert --file /tmp/new_expert.json --reload

# 输出示例:
# {
#   "status": "success",
#   "action": "add-expert",
#   "expert_id": "a3b8c9...",
#   "name": "张三",
#   "total_experts_after": 574,
#   "saved_file": "/Users/.../data/专家数据/expert_info.json"
# }
```

### 校验失败示例

```bash
$ python3 scripts/admin.py add-expert --file /tmp/bad_expert.json
❌ 专家 录入失败：2 个错误
  1. 缺少必填字段 'name'（必须非空字符串）
  2. 'phone' 与 'email' 至少需要一个（非空字符串）
$ echo $?
1
```

## 数据存储位置

- 预案：`data/预案/parsered_data/*.json`
- 预案路由索引：`data/预案/plan_index.json`
- 专家：`data/专家数据/expert_info.json`（首次 add-expert 时从 `expert_info.xls` 迁移）
- 仓库：`data/仓库和队伍的物资数据/warehouse_dispatch_resources.jsonl`
- 救援队：`data/仓库和队伍的物资数据/rescue_team_dispatch_resources.jsonl`

## 与主项目其他组件的关系

- **查询脚本**：直接读数据文件，不依赖正在跑的服务。`query_plans.py` 复用 `src.emergency_plans.EmergencyPlanService`，与 Agent/HTTP API 共享同一份路由逻辑
- **录入脚本**：写文件 + 可选 `--reload` 触发主项目 HTTP API 的预案热加载（专家/仓库/队伍由 Agent 每个新任务时重载，无需服务端热加载）
- **不影响 test_skill**：test_skill 是独立的 Claude Code Skill 副本，本目录脚本只服务主项目
