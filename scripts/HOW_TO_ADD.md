# 添加新资源使用指南

本指南介绍如何往本地数据库里添加 4 类资源：**预案 / 专家 / 物资仓库 / 救援队伍**。

> 给数据维护人员看的。不需要懂代码，会复制改字段、会执行命令就行。

---

## 整体三步走

```
①  复制对应的样例文件 →  ②  改成你的真实数据 →  ③  执行录入命令
```

所有命令都在**项目根目录**执行（`/Users/jiawen/mywork/traffic-emergency-agent/`）。

样例文件就在 `scripts/` 目录下，4 类各一份：
- `scripts/add_plan_example.json` — 预案样例
- `scripts/add_expert_example.json` — 专家样例
- `scripts/add_warehouse_example.json` — 物资仓库样例
- `scripts/add_team_example.json` — 救援队伍样例

---

## 一、添加预案

```bash
# 1. 复制样例
cp scripts/add_plan_example.json /tmp/my_plan.json

# 2. 用编辑器改成你的真实预案内容
vim /tmp/my_plan.json

# 3. 录入
python3 scripts/admin.py add-plan --file /tmp/my_plan.json
```

**必填字段**：JSON 顶层的 `封面.标题`（不能为空，且不能跟已有预案重名）

**关于预案 JSON 格式**：必须是已经按章节结构整理好的"parsered_data"风格 —— 中文 key、镜像原 PDF 章节。如果你只有 PDF 原文，需要先用解析工具处理成 JSON 才能录入（不在本工具职责内）。

**绑定到某个场景**（可选）：录入后如果希望"高速事故"等场景自动匹配到这份新预案，需要手动编辑 `data/预案/plan_index.json`，在 `scene_plans` 加一行：

```json
"YOUR_SCENE": {
  "preferred_plan_name": "你新加的预案标题（要和封面.标题完全一致）",
  "fallback_to": "GENERAL"
}
```

---

## 二、添加专家

```bash
# 1. 复制样例
cp scripts/add_expert_example.json /tmp/my_expert.json

# 2. 改字段：name 必填，phone 和 email 至少填一个
vim /tmp/my_expert.json

# 3. 录入
python3 scripts/admin.py add-expert --file /tmp/my_expert.json
```

**必填字段**：
- `name`（专家姓名）
- `phone` 或 `email`（至少填一个）

其他字段（专业方向、单位、坐标等）都是可选，但越全越好。

**首次添加专家时**：系统会自动把原始的 `expert_info.xls` 转成 `expert_info.json`（原 xls 保留作为备份），之后录入和查询都基于 JSON。这个过程是自动的，无需你做什么。

---

## 三、添加物资仓库

```bash
# 1. 复制样例
cp scripts/add_warehouse_example.json /tmp/my_warehouse.json

# 2. 改字段（重点填仓库名、地址、坐标、物资类别、联系电话）
vim /tmp/my_warehouse.json

# 3. 录入
python3 scripts/admin.py add-warehouse --file /tmp/my_warehouse.json
```

**必填字段**：
- `warehouse_name`：仓库名称
- `latitude` / `longitude`：经纬度（用于按距离搜索）
- `contact_phone`：联系电话
- `categories`：物资类别列表（不能为空），只能从下面这 11 类里选：

| 编码 | 含义 |
|---|---|
| `WARNING` | 警示防护设备（路锥、爆闪灯等） |
| `PPE` | 个人防护用品（反光背心、安全帽） |
| `SIGN` | 交通标志标牌 |
| `FIRE` | 消防器材 |
| `TOOL` | 工具与工程机械（切割机、发电机） |
| `VEHICLE` | 车辆装备 |
| `MATERIAL` | 抢险材料 |
| `RESCUE` | 救生救援装备 |
| `COMMS` | 通信照明设备 |
| `DEICE` | 除冰除雪物资 |
| `OTHER` | 其他物资 |

**`materials_by_category` 字段**：可选，但建议填上具体物资清单（按类别分组的列表），方便后续调度时模型能直接说"调多少个路锥多少件反光背心"。

---

## 四、添加救援队伍

```bash
# 1. 复制样例
cp scripts/add_team_example.json /tmp/my_team.json

# 2. 改字段
vim /tmp/my_team.json

# 3. 录入
python3 scripts/admin.py add-team --file /tmp/my_team.json
```

**必填字段**：
- `team_name`：队伍名称
- `latitude` / `longitude`：经纬度
- `leader_phone` 或 `jurisdiction_phone`：至少填一个（负责人电话或管辖单位电话）

其他字段建议尽量填：`team_size`（人数）、`specialties`（专长描述）、`address` 等。

---

## 录入成功是什么样子

成功时会输出一段 JSON，含新数据的 id：

```json
{
  "status": "success",
  "action": "add-warehouse",
  "warehouse_id": "12992d69df1a4336b72a843fc1f4d5e3",
  "warehouse_name": "示例应急物资仓库",
  "total_warehouses_after": 303,
  "saved_file": "/Users/jiawen/.../warehouse_dispatch_resources.jsonl"
}
```

`warehouse_id` 是系统自动生成的，下次想查这条数据可以用：

```bash
python3 scripts/query_warehouses.py get --id 12992d69df1a4336b72a843fc1f4d5e3
```

---

## 录入失败是什么样子

如果字段不合规，系统会**一次列出所有问题**，不通过 stderr 输出：

```
❌ 仓库 录入失败：3 个错误
  1. 'latitude' 缺失或不合法: None（必须 -90~90 数字）
  2. 'categories' 含非法值: ['INVALID_CAT']；合法值: ['COMMS', 'DEICE', 'FIRE', ...]
  3. 'contact_phone' 格式不合法: 'abc'
```

按提示改完文件再重新跑命令即可。**不会写半截脏数据进去**，所以不用担心录入失败弄乱数据库。

---

## 让正在跑的服务立即看到新数据（可选）

如果你的 API 服务正在跑（`chainlit run web_app.py`），并且希望新数据**立刻**对新任务生效（不重启服务），加 `--reload` 标志：

```bash
python3 scripts/admin.py add-plan --file /tmp/my_plan.json --reload
```

不加 `--reload` 也没关系 —— 数据已经写到文件了，下次重启服务自然就加载到了。

---

## 常见疑问

**Q：录入之后想检查是否真的进去了？**
用对应的查询脚本搜一下就行：

```bash
python3 scripts/query_experts.py search --keyword "你新加的专家姓名"
python3 scripts/query_warehouses.py search --keyword "你新加的仓库名"
python3 scripts/query_teams.py search --keyword "你新加的队伍名"
python3 scripts/query_plans.py list
```

**Q：录错了想删掉怎么办？**
目前 admin.py 只支持新增，不支持删除/修改。如果录错了：
- 专家：编辑 `data/专家数据/expert_info.json`，找到对应记录改 `del_flag: 1` 或直接删行
- 仓库/救援队：编辑对应的 `.jsonl` 文件，删掉那一行
- 预案：直接删 `data/预案/parsered_data/<标题>.json` 文件

**Q：可以批量导入吗？**
当前 admin.py 一次只录一条。批量的话写个 shell 循环：

```bash
for f in batch/*.json; do
  python3 scripts/admin.py add-expert --file "$f"
done
```
