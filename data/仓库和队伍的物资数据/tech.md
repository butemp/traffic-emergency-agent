# 资源调度模块技术方案

> 模块定位：资源调度 Skill 的核心引擎，负责在应急指挥流程中精准匹配和推荐可用资源
> 版本：v1.0 | 日期：2026年4月

---

## 1. 设计目标与核心理念

### 1.1 核心问题

给定一个事故（类型、位置、严重程度），如何快速、准确地找到"应该派谁去、从哪取什么物资"。

### 1.2 设计理念：模型负责语义理解，算法负责精确计算

资源调度不应该把所有数据丢给模型让它自己挑，也不应该用纯规则引擎完全绕过模型。合理的分工是：

- **模型擅长的事**：理解灾情语义、推断资源需求、评估方案合理性、与用户沟通
- **算法擅长的事**：地理距离计算、多条件筛选排序、覆盖度量化分析

因此，整个调度链路设计为"**模型 → 原子算法 → 模型 → 用户**"四段协作：

```
模型（需求推断）
  ↓ 结构化查询条件
原子算法（检索 + 排序 + 评分）
  ↓ 候选资源列表 + 覆盖度分析
模型（方案编排 + 理由生成）
  ↓ 结构化调度方案 + 说明
用户（确认 / 调整 / 补充）
  ↓ 反馈
模型（根据反馈修正）→ 再次调用原子算法 ...
```

### 1.3 关键设计原则

- **算法返回候选集，模型做最终决策**：算法不做"最终选择"，而是返回排好序的候选列表和评分依据，由模型结合全局上下文做最终编排
- **结果对用户透明**：每个推荐资源都附带推荐理由（距离、能力匹配度、覆盖类别），用户可以理解为什么推荐这个而不是那个
- **支持人工干预后的重算**：用户说"不要这个仓库"或"加上某支队伍"后，算法能快速响应约束条件变化

---

## 2. 数据层设计

### 2.1 索引数据结构

基于前序离线预处理步骤，调度模块使用两个索引文件：

**warehouse_index.jsonl**（仓库索引）：
```json
{
  "warehouse_id": "6c1cba88...",
  "warehouse_name": "灵川西收费站物资储备库",
  "belong_org_name": "桂林某高速公路运营公司",
  "latitude": 25.xxx,
  "longitude": 110.xxx,
  "road_code": "G72",
  "stake": 120.0,
  "principal": "张三",
  "contact_phone": "138xxxx",
  "categories": ["WARNING", "PPE", "COMMS", "TOOL"],
  "materials_by_category": {
    "WARNING": [
      {"name": "锥桶", "quantity": 50, "unit": "个"},
      {"name": "爆闪灯", "quantity": 20, "unit": "个"}
    ],
    ...
  }
}
```

**team_index.jsonl**（救援队伍索引）：
```json
{
  "team_id": "...",
  "team_name": "XX救援队",
  "team_size": 15,
  "leader_name": "李四",
  "leader_phone": "139xxxx",
  "latitude": 25.xxx,
  "longitude": 110.xxx,
  "road_code": "G72",
  "stake": 135.0,
  "specialties": ["rescue", "clearance"],
  "categories": ["TOOL", "RESCUE"],
  "materials_by_category": { ... }
}
```

### 2.2 启动时加载

服务启动时将两个索引文件加载到内存，构建以下辅助索引：

- **地理索引**：按 road_code 分组，同一路段内按 stake 排序（用于桩号距离快速查询）
- **类别索引**：category → warehouse_id / team_id 的反向映射（用于快速找"哪些仓库有某类物资"）

数据量（263仓库 + 221队伍）完全可以全量加载内存，无需数据库。

---

## 3. 原子算法设计

### 3.1 算法总览

设计 3 个原子算法，各自职责单一、可独立调用、可组合使用：

| 算法 | 输入 | 输出 | 职责 |
|------|------|------|------|
| NearbySearch | 坐标/桩号 + 半径 + 过滤条件 | 排序后的资源列表 | 地理范围搜索 + 多条件筛选 |
| CoverageAnalysis | 所需类别列表 + 候选资源列表 | 覆盖度报告 | 分析候选资源对需求的满足程度 |
| DispatchOptimizer | 需求列表 + 候选资源列表 + 约束条件 | 调度方案 | 从候选集中选出最优资源组合 |

调用链路：

```
NearbySearch（找出附近有什么）
    ↓
CoverageAnalysis（够不够用）
    ↓
DispatchOptimizer（怎么组合最优）
```

### 3.2 算法一：NearbySearch（就近搜索）

#### 3.2.1 功能

给定事故位置，搜索半径内的仓库和救援队伍，按相关性排序返回。

#### 3.2.2 输入参数

```python
class NearbySearchParams:
    # 事故位置（二选一，都有时优先桩号）
    longitude: float              # 事故经度
    latitude: float               # 事故纬度
    road_code: str = None         # 事故所在路段编号（如 "G72"）
    stake: float = None           # 事故桩号（如 120.5）

    # 搜索范围
    radius_km: float = 50.0       # 搜索半径（公里）

    # 过滤条件
    resource_type: str = "all"    # "warehouse" / "team" / "all"
    required_categories: list[str] = None   # 所需物资类别（如 ["WARNING", "RESCUE"]）
    required_specialties: list[str] = None  # 所需队伍专长（如 ["rescue", "clearance"]）

    # 排除条件（用于用户反馈后的重新搜索）
    exclude_ids: list[str] = None  # 排除指定的仓库或队伍 ID

    # 返回控制
    max_results: int = 10         # 最大返回数量
```

#### 3.2.3 距离计算策略

采用**双距离模型**——同时计算两种距离，取更合理的那个作为排序依据：

**直线距离（Haversine）**：
- 适用于所有资源点
- 计算简单，作为基础距离度量

**桩号距离**：
- 仅当事故和资源点在同一 road_code 时可用
- 桩号差值的绝对值即为沿路实际距离的近似
- 高速场景下比直线距离更准确

距离计算逻辑：

```python
def compute_distance(incident, resource):
    """计算事故点到资源点的有效距离"""
    # 1. 始终计算直线距离
    geo_dist = haversine(
        incident.latitude, incident.longitude,
        resource.latitude, resource.longitude
    )

    # 2. 如果同一路段，计算桩号距离
    if (incident.road_code
        and incident.road_code == resource.road_code
        and incident.stake is not None
        and resource.stake is not None):
        stake_dist = abs(incident.stake - resource.stake)
        # 桩号距离更可信，但也要和直线距离交叉验证
        # 如果桩号距离远小于直线距离，可能数据有误，取较大值
        return max(stake_dist, geo_dist * 0.8)

    # 3. 不同路段，直线距离乘以绕行系数
    #    高速公路实际行驶距离通常是直线距离的 1.3-1.8 倍
    return geo_dist * 1.5
```

#### 3.2.4 排序评分算法

搜索结果不是单纯按距离排，而是综合多个因素计算一个相关性得分：

```python
def compute_relevance_score(resource, params, distance_km):
    """
    计算资源的综合相关性得分（0-100 分）。
    得分越高越应该优先推荐。
    """
    score = 0.0

    # --- 距离分（满分 40 分）---
    # 10km 以内满分，50km 以外 0 分，线性衰减
    if distance_km <= 10:
        score += 40.0
    elif distance_km <= 50:
        score += 40.0 * (50 - distance_km) / 40.0
    # 超出 50km 距离分为 0

    # --- 类别匹配分（满分 35 分）---
    if params.required_categories:
        matched = set(resource.categories) & set(params.required_categories)
        match_ratio = len(matched) / len(params.required_categories)
        score += 35.0 * match_ratio

    # --- 同路段加分（满分 15 分）---
    # 同一条高速上的资源调度效率更高
    if (params.road_code
        and params.road_code == resource.road_code):
        score += 15.0

    # --- 资源丰富度加分（满分 10 分）---
    # 覆盖的物资类别越多，综合保障能力越强
    category_count = len(resource.categories)
    score += min(10.0, category_count * 2.0)

    return round(score, 1)
```

#### 3.2.5 输出结构

```python
class NearbySearchResult:
    resource_id: str
    resource_type: str            # "warehouse" / "team"
    name: str
    distance_km: float            # 有效距离
    distance_type: str            # "stake" / "haversine" 标明用的哪种距离
    relevance_score: float        # 综合相关性得分（0-100）
    road_code: str
    stake: float
    same_road: bool               # 是否与事故同路段
    contact: dict                 # {"name": "张三", "phone": "138xxxx"}

    # 仓库特有
    matched_categories: list[str] # 命中了哪些所需类别
    unmatched_categories: list[str] # 缺少哪些所需类别
    materials_summary: dict       # 按命中类别分组的物资摘要

    # 队伍特有
    team_size: int
    specialties: list[str]
    matched_specialties: list[str]

    # 推荐理由（供模型和用户参考）
    recommend_reasons: list[str]
    # 示例：["距事故点 5.2km，同路段 G72",
    #        "覆盖所需类别：WARNING、RESCUE",
    #        "综合评分 82.5"]
```

### 3.3 算法二：CoverageAnalysis（覆盖度分析）

#### 3.3.1 功能

给定需求列表和候选资源列表，分析候选资源对需求的覆盖情况，找出缺口。

#### 3.3.2 为什么需要这个算法

NearbySearch 返回了一批候选资源，但模型需要知道：这些资源加在一起够不够？哪些需求还没满足？需不需要扩大搜索范围或调用外部资源（高德POI）？

这个判断如果交给模型自己数，容易出错。用算法做精确统计更可靠。

#### 3.3.3 输入参数

```python
class CoverageAnalysisParams:
    # 需求侧
    required_categories: list[str]           # 所需物资类别
    required_specialties: list[str] = None   # 所需队伍专长
    severity: str = "medium"                 # 事故严重程度，影响数量充足性判断

    # 供给侧
    candidate_warehouses: list[NearbySearchResult]
    candidate_teams: list[NearbySearchResult]
```

#### 3.3.4 分析逻辑

```python
def analyze_coverage(params):
    """
    分析候选资源对需求的覆盖情况。
    """
    report = {}

    # 1. 物资类别覆盖分析
    for category in params.required_categories:
        sources = []
        total_items = 0
        for wh in params.candidate_warehouses:
            if category in wh.matched_categories:
                materials = wh.materials_summary.get(category, [])
                sources.append({
                    "name": wh.name,
                    "distance_km": wh.distance_km,
                    "item_count": len(materials),
                    "items": materials[:5]  # 最多展示 5 条明细
                })
                total_items += len(materials)

        report[category] = {
            "status": "covered" if sources else "missing",
            "source_count": len(sources),
            "total_items": total_items,
            "sources": sources,
            "nearest_source_km": min(
                (s["distance_km"] for s in sources), default=None
            )
        }

    # 2. 队伍专长覆盖分析（类似逻辑）
    if params.required_specialties:
        for spec in params.required_specialties:
            ...

    # 3. 生成覆盖度摘要
    covered = [c for c, v in report.items() if v["status"] == "covered"]
    missing = [c for c, v in report.items() if v["status"] == "missing"]

    summary = {
        "coverage_ratio": len(covered) / len(params.required_categories),
        "covered_categories": covered,
        "missing_categories": missing,
        "recommendation": generate_recommendation(missing, params.severity)
    }

    return {"detail": report, "summary": summary}
```

#### 3.3.5 覆盖度不足时的建议生成

```python
def generate_recommendation(missing_categories, severity):
    """
    根据缺失类别和严重程度，生成补充建议。
    """
    if not missing_categories:
        return {"action": "sufficient", "message": "所有所需物资类别均已覆盖"}

    recommendations = []

    # 映射：缺失类别 → 建议搜索的高德 POI 类型
    category_to_poi = {
        "RESCUE": {"poi_type": "医院", "reason": "缺少救生装备，建议查询附近医院"},
        "FIRE": {"poi_type": "消防站", "reason": "缺少消防器材，建议查询附近消防站"},
        "VEHICLE": {"poi_type": "汽车救援", "reason": "缺少作业车辆，建议查询社会救援力量"},
    }

    for cat in missing_categories:
        if cat in category_to_poi:
            recommendations.append(category_to_poi[cat])
        else:
            recommendations.append({
                "poi_type": None,
                "reason": f"缺少 {cat} 类物资，建议扩大搜索范围或人工协调"
            })

    return {
        "action": "need_supplement",
        "missing": missing_categories,
        "recommendations": recommendations
    }
```

### 3.4 算法三：DispatchOptimizer（调度优化）

#### 3.4.1 功能

从候选资源中选出最优组合，生成分梯队调度方案。

#### 3.4.2 设计思路

这不是一个复杂的运筹优化问题（资源量级小），而是一个**贪心选择 + 梯队编排**的问题：

核心目标：用最少的资源点覆盖所有需求类别，同时优先选距离近、评分高的资源。

#### 3.4.3 输入参数

```python
class DispatchOptimizerParams:
    required_categories: list[str]
    required_specialties: list[str] = None
    candidate_warehouses: list[NearbySearchResult]
    candidate_teams: list[NearbySearchResult]

    # 约束条件
    exclude_ids: list[str] = None         # 用户排除的资源
    preferred_ids: list[str] = None       # 用户指定必须包含的资源
    max_warehouses: int = 5               # 最多选几个仓库
    max_teams: int = 5                    # 最多选几支队伍

    # 梯队划分阈值
    tier1_distance_km: float = 15.0       # 第一梯队距离阈值
    tier2_distance_km: float = 35.0       # 第二梯队距离阈值
```

#### 3.4.4 核心算法：贪心覆盖选择

```python
def optimize_dispatch(params):
    """
    贪心算法选出最优资源组合。

    策略：每轮选择"能覆盖最多未满足类别且距离最近"的资源，
    直到所有类别被覆盖或候选耗尽。
    """
    # 0. 应用约束
    candidates = filter_by_constraints(params)

    # 1. 初始化
    uncovered = set(params.required_categories)
    selected_warehouses = []
    selected_teams = []

    # 1.1 如果用户指定了必须包含的资源，先加入
    if params.preferred_ids:
        for res in candidates:
            if res.resource_id in params.preferred_ids:
                if res.resource_type == "warehouse":
                    selected_warehouses.append(res)
                else:
                    selected_teams.append(res)
                uncovered -= set(res.matched_categories)

    # 2. 贪心选择仓库
    remaining_wh = [w for w in candidates
                    if w.resource_type == "warehouse"
                    and w.resource_id not in {s.resource_id for s in selected_warehouses}]

    while uncovered and remaining_wh and len(selected_warehouses) < params.max_warehouses:
        # 对每个候选计算"边际价值"：能新覆盖多少未满足类别
        best = None
        best_value = -1

        for wh in remaining_wh:
            new_coverage = len(set(wh.matched_categories) & uncovered)
            if new_coverage == 0:
                continue
            # 边际价值 = 新覆盖数 * 100 - 距离惩罚
            value = new_coverage * 100 - wh.distance_km
            if value > best_value:
                best_value = value
                best = wh

        if best is None:
            break

        selected_warehouses.append(best)
        uncovered -= set(best.matched_categories)
        remaining_wh.remove(best)

    # 3. 选择救援队伍（按专长匹配 + 距离排序）
    unmatched_specs = set(params.required_specialties or [])
    remaining_teams = [t for t in candidates
                       if t.resource_type == "team"
                       and t.resource_id not in {s.resource_id for s in selected_teams}]

    # 按 relevance_score 排序，取 top
    remaining_teams.sort(key=lambda t: t.relevance_score, reverse=True)

    for team in remaining_teams:
        if len(selected_teams) >= params.max_teams:
            break
        matched_specs = set(team.matched_specialties or []) & unmatched_specs
        if matched_specs or team.relevance_score >= 60:
            selected_teams.append(team)
            unmatched_specs -= matched_specs

    # 4. 编排梯队
    dispatch_plan = arrange_tiers(
        selected_warehouses, selected_teams, params
    )

    return dispatch_plan
```

#### 3.4.5 梯队编排

```python
def arrange_tiers(warehouses, teams, params):
    """
    将选中的资源按距离分梯队。
    """
    all_resources = (
        [{"type": "warehouse", "data": w} for w in warehouses] +
        [{"type": "team", "data": t} for t in teams]
    )

    tier1 = []  # 第一梯队：快速到达
    tier2 = []  # 第二梯队：增援力量
    tier3 = []  # 第三梯队：后备补充

    for res in all_resources:
        dist = res["data"].distance_km
        if dist <= params.tier1_distance_km:
            tier1.append(res)
        elif dist <= params.tier2_distance_km:
            tier2.append(res)
        else:
            tier3.append(res)

    # 每个梯队内按 relevance_score 排序
    for tier in [tier1, tier2, tier3]:
        tier.sort(key=lambda r: r["data"].relevance_score, reverse=True)

    return {
        "tier1": {
            "label": "第一梯队（15km内，预计15分钟到达）",
            "resources": tier1
        },
        "tier2": {
            "label": "第二梯队（15-35km，预计30分钟到达）",
            "resources": tier2
        },
        "tier3": {
            "label": "第三梯队（35km以上，预计45分钟+）",
            "resources": tier3
        },
        "still_uncovered": list(uncovered),  # 仍未覆盖的需求
        "summary": {
            "total_warehouses": len(warehouses),
            "total_teams": len(teams),
            "coverage_ratio": 1 - len(uncovered) / max(len(params.required_categories), 1)
        }
    }
```

---

## 4. 工具接口设计

原子算法封装为两个 Function Calling 工具，供模型调用。

### 4.1 工具一：search_emergency_resources

**定位**：整合 NearbySearch + CoverageAnalysis，一次调用完成"搜索+分析"。

**Function Calling Schema**：

```json
{
  "name": "search_emergency_resources",
  "description": "根据事故位置和所需资源类别，搜索附近的应急仓库和救援队伍，返回候选资源列表和覆盖度分析",
  "parameters": {
    "type": "object",
    "properties": {
      "longitude": {
        "type": "number",
        "description": "事故点经度"
      },
      "latitude": {
        "type": "number",
        "description": "事故点纬度"
      },
      "road_code": {
        "type": "string",
        "description": "事故所在路段编号，如 G72、G80。有则填写，可提高同路段资源匹配精度"
      },
      "stake": {
        "type": "number",
        "description": "事故桩号，如 120.5。有则填写"
      },
      "required_categories": {
        "type": "array",
        "items": {"type": "string"},
        "description": "所需物资类别列表。可选值：SIGN(交通标志)、WARNING(警示设备)、PPE(防护用品)、FIRE(消防器材)、TOOL(工具机械)、VEHICLE(车辆)、MATERIAL(抢险材料)、RESCUE(救生装备)、COMMS(通讯照明)、DEICE(防冰除雪)"
      },
      "required_specialties": {
        "type": "array",
        "items": {"type": "string"},
        "description": "所需救援队伍专长。可选值：rescue(救援)、clearance(清障)、emergency_repair(抢险)"
      },
      "radius_km": {
        "type": "number",
        "description": "搜索半径（公里），默认 50"
      },
      "exclude_ids": {
        "type": "array",
        "items": {"type": "string"},
        "description": "排除的资源ID列表（用于用户反馈后重新搜索）"
      }
    },
    "required": ["longitude", "latitude", "required_categories"]
  }
}
```

**返回结构**：

```json
{
  "candidates": {
    "warehouses": [
      {
        "resource_id": "...",
        "name": "灵川西收费站物资储备库",
        "distance_km": 5.2,
        "distance_type": "stake",
        "same_road": true,
        "relevance_score": 82.5,
        "contact": {"name": "张三", "phone": "138xxxx"},
        "matched_categories": ["WARNING", "PPE"],
        "unmatched_categories": ["RESCUE"],
        "materials_summary": {
          "WARNING": [
            {"name": "锥桶", "quantity": 50, "unit": "个"},
            {"name": "爆闪灯", "quantity": 20, "unit": "个"}
          ],
          "PPE": [...]
        },
        "recommend_reasons": [
          "距事故点 5.2km，同路段 G72",
          "覆盖所需类别：WARNING、PPE",
          "综合评分 82.5"
        ]
      }
    ],
    "teams": [
      {
        "resource_id": "...",
        "name": "XX救援队",
        "distance_km": 8.3,
        "relevance_score": 76.0,
        "team_size": 15,
        "specialties": ["rescue", "clearance"],
        "matched_specialties": ["rescue"],
        "contact": {"name": "李四", "phone": "139xxxx"},
        "recommend_reasons": [
          "距事故点 8.3km",
          "专长匹配：救援",
          "队伍规模 15 人"
        ]
      }
    ]
  },
  "coverage": {
    "coverage_ratio": 0.67,
    "covered_categories": ["WARNING", "PPE"],
    "missing_categories": ["RESCUE"],
    "recommendation": {
      "action": "need_supplement",
      "missing": ["RESCUE"],
      "recommendations": [
        {"poi_type": "医院", "reason": "缺少救生装备，建议查询附近医院"}
      ]
    }
  }
}
```

### 4.2 工具二：optimize_dispatch_plan

**定位**：在模型确认候选资源后，调用 DispatchOptimizer 生成分梯队调度方案。

**Function Calling Schema**：

```json
{
  "name": "optimize_dispatch_plan",
  "description": "基于搜索到的候选资源，生成最优的分梯队调度方案。在 search_emergency_resources 之后调用",
  "parameters": {
    "type": "object",
    "properties": {
      "required_categories": {
        "type": "array",
        "items": {"type": "string"},
        "description": "所需物资类别列表"
      },
      "required_specialties": {
        "type": "array",
        "items": {"type": "string"},
        "description": "所需队伍专长列表"
      },
      "exclude_ids": {
        "type": "array",
        "items": {"type": "string"},
        "description": "排除的资源ID（用户明确不要的）"
      },
      "preferred_ids": {
        "type": "array",
        "items": {"type": "string"},
        "description": "必须包含的资源ID（用户指定要用的）"
      }
    },
    "required": ["required_categories"]
  }
}
```

**返回结构**：

```json
{
  "dispatch_plan": {
    "tier1": {
      "label": "第一梯队（预计15分钟内到达）",
      "resources": [
        {
          "type": "team",
          "name": "XX救援队",
          "distance_km": 8.3,
          "action": "立即出动，执行现场救援",
          "contact": {"name": "李四", "phone": "139xxxx"}
        },
        {
          "type": "warehouse",
          "name": "灵川西收费站物资储备库",
          "distance_km": 5.2,
          "action": "取用物资：锥桶x50、爆闪灯x20、反光背心x30",
          "contact": {"name": "张三", "phone": "138xxxx"}
        }
      ]
    },
    "tier2": { ... },
    "tier3": { ... }
  },
  "coverage_summary": {
    "coverage_ratio": 0.67,
    "covered": ["WARNING", "PPE"],
    "still_missing": ["RESCUE"],
    "suggestion": "RESCUE 类物资内部资源未覆盖，建议查询附近医院或社会救援力量"
  }
}
```

---

## 5. 模型与算法的协作流程

### 5.1 标准调度流程

```
步骤 1：模型推断需求
  模型基于灾情信息，确定：
  - required_categories: ["WARNING", "RESCUE", "COMMS"]
  - required_specialties: ["rescue", "clearance"]
  - 提取事故坐标和路段信息

步骤 2：模型调用 search_emergency_resources
  传入坐标、所需类别、所需专长
  ↓
  算法返回候选列表 + 覆盖度分析

步骤 3：模型评估覆盖度
  如果 coverage_ratio = 1.0 → 直接调用 optimize_dispatch_plan
  如果有 missing_categories → 根据建议调用高德 POI 补充外部资源
  如果候选太少 → 扩大 radius_km 重新搜索

步骤 4：模型调用 optimize_dispatch_plan
  传入需求和约束
  ↓
  算法返回分梯队调度方案

步骤 5：模型编排最终方案
  将调度方案整合到完整的应急指挥方案中
  附上每个资源的推荐理由
  呈现给用户确认
```

### 5.2 用户反馈后的重算流程

```
场景 A：用户说"XX仓库不用了，太远了"
  模型提取 exclude_ids
  → 重新调用 optimize_dispatch_plan(exclude_ids=[...])
  → 算法自动用其他候选替补

场景 B：用户说"把XX救援队也加上"
  模型提取 preferred_ids
  → 重新调用 optimize_dispatch_plan(preferred_ids=[...])
  → 算法将指定队伍强制加入方案

场景 C：用户说"再找找有没有消防器材"
  模型追加 required_categories
  → 重新调用 search_emergency_resources(required_categories=[..., "FIRE"])
  → 可能需要扩大搜索范围

场景 D：用户说"这个方案可以，但第一梯队再加一支队伍"
  模型调整 max_teams 或手动追加
  → 重新调用 optimize_dispatch_plan
```

### 5.3 Skill Prompt 要点

资源调度 Skill 的 prompt 应引导模型按以下方式行动：

```
你现在需要为事故调度应急资源。请按以下步骤操作：

1. 根据灾情信息推断所需的物资类别和队伍专长：
   - 物资类别从以下选取：SIGN, WARNING, PPE, FIRE, TOOL, VEHICLE, MATERIAL, RESCUE, COMMS, DEICE
   - 队伍专长从以下选取：rescue, clearance, emergency_repair

2. 调用 search_emergency_resources 搜索附近资源

3. 检查返回的 coverage 字段：
   - 如果 coverage_ratio >= 0.8，继续下一步
   - 如果有 missing_categories，根据 recommendations 决定是否调用 search_nearby_pois 补充
   - 如果候选资源太少（少于 3 个），扩大搜索半径重试

4. 调用 optimize_dispatch_plan 生成调度方案

5. 将调度方案呈现给用户时，包含以下信息：
   - 分梯队的资源列表（名称、距离、联系人、携带物资）
   - 每个资源的推荐理由
   - 未覆盖的需求及补充建议
   - 明确询问用户是否需要调整
```

---

## 6. 与其他 Skill 的协作

### 6.1 与态势感知 Skill

- 态势感知提供事故坐标（geocode_address 工具的输出）→ 资源调度使用该坐标搜索
- 态势感知提供路况信息 → 模型在编排方案时参考，判断某条路线是否可行

### 6.2 与知识检索 Skill

- 知识检索返回的法规可能规定"某类事故必须出动消防力量" → 模型据此追加 FIRE 类需求
- 两者在 PLAN_GENERATION 阶段并行工作，互不依赖

### 6.3 与人机协作 Skill

- 资源调度结果通过人机协作 Skill 的"方案选择"或"确认征询"模式呈现给用户
- 用户反馈通过 exclude_ids / preferred_ids 参数传回调度算法

### 6.4 与风险评估 Skill

- 风险评估会检查"资源充足性"维度 → 依赖资源调度的 coverage_ratio
- 如果评估认为资源不足 → 触发回退到 PLAN_GENERATION，可能需要扩大搜索范围重新调度

---

## 7. 性能与边界考虑

### 7.1 性能

- 数据规模（263仓库 + 221队伍）全量内存，单次搜索遍历 < 500 条，耗时在毫秒级
- 无需数据库、无需向量索引，简单的遍历 + 计算 + 排序即可
- 瓶颈在模型推理而非算法计算

### 7.2 边界情况处理

| 边界情况 | 处理策略 |
|----------|----------|
| 搜索半径内无任何资源 | 自动扩大半径至 100km 重试一次，仍无结果则提示模型调用外部 POI |
| 某个资源点缺少坐标 | 跳过该资源点，在日志中记录 |
| 事故位置不在任何已知路段上 | 只使用经纬度距离，不使用桩号距离 |
| 用户排除了所有近距离资源 | 算法正常执行，返回的方案中标注"最近资源距离较远" |
| 物资数量为 0 | 在结果中标注"库存可能为零，建议电话确认" |

### 7.3 数据时效性提示

所有返回结果应附带数据时效性说明：

```json
{
  "data_freshness": {
    "note": "物资数据基于最近一次核查，实际库存可能有变动",
    "suggestion": "建议出发前电话确认关键物资的可用性"
  }
}
```

---

## 8. 实施步骤

| 步骤 | 内容 | 预计工作量 |
|------|------|-----------|
| 1 | 实现 Haversine 距离计算 + 桩号距离计算 | 0.5 天 |
| 2 | 实现 NearbySearch 算法 | 1 天 |
| 3 | 实现 CoverageAnalysis 算法 | 0.5 天 |
| 4 | 实现 DispatchOptimizer 算法 | 1 天 |
| 5 | 封装为两个 Function Calling 工具 | 0.5 天 |
| 6 | 编写资源调度 Skill 的 SKILL.yaml 和 prompt.md | 0.5 天 |
| 7 | 单元测试 + 与 Agent Core 联调 | 1-2 天 |