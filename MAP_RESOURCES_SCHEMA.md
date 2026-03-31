# 地图资源库数据结构设计

本文档描述了模拟地图资源库（Map Resources）的 JSON 数据结构设计。该结构旨在支持应急指挥场景下的快速检索、路径计算和排班管理。

## 1. 数据结构概览

每个地图资源为一个 JSON 对象，包含以下核心模块：

*   **基础信息 (`id`, `name`, `type`, `status`)**: 用于快速筛选和分类。
*   **地理位置 (`location`)**: 包含经纬度和地址，支持距离计算。
*   **功能描述 (`description`)**: 资源的详细能力和容量，支持语义检索。
*   **联系人与排班 (`contact`)**: 支持固定排班和临时值班的复杂逻辑。
*   **元数据 (`metadata`)**: 数据的时效性和优先级管理。

## 2. 详细字段说明

### 2.1 基础信息 (Base Info)

| 字段名 | 类型 | 必填 | 说明 | 示例 |
| :--- | :--- | :--- | :--- | :--- |
| `id` | string | 是 | 唯一标识符，建议使用前缀区分类型。 | `"res_001"` |
| `name` | string | 是 | 资源点的显示名称。 | `"南宁市第一人民医院应急医疗点"` |
| `type` | string | 是 | 资源类型枚举，用于快速过滤。<br>枚举值：<br>- `medical`: 医疗资源<br>- `police`: 交警/公安<br>- `fire`: 消防救援<br>- `inventory`: 物资储备库<br>- `transport`: 交通工具(直升机/拖车) | `"medical"` |
| `status` | string | 是 | 当前可用状态。<br>枚举值：<br>- `active`: 可用<br>- `busy`: 任务中/繁忙<br>- `maintenance`: 维护中<br>- `closed`: 关闭 | `"active"` |

### 2.2 地理位置 (Location)

| 字段名 | 类型 | 必填 | 说明 | 示例 |
| :--- | :--- | :--- | :--- | :--- |
| `location.latitude` | float | 是 | 纬度 (WGS84坐标系)。 | `22.8170` |
| `location.longitude` | float | 是 | 经度 (WGS84坐标系)。 | `108.3665` |
| `location.address` | string | 是 | 具体的文本地址，用于导航显示。 | `"南宁市青秀区七星路89号"` |

> **设计意图**: 将经纬度独立为 float 类型，方便 Agent 直接读取并代入 Haversine 公式计算与事故点的直线距离。

### 2.3 功能描述 (Description)

| 字段名 | 类型 | 必填 | 说明 | 示例 |
| :--- | :--- | :--- | :--- | :--- |
| `description.summary` | string | 是 | 简短的能力概述。 | `"三级甲等综合医院..."` |
| `description.capabilities` | list[str] | 否 | 关键标签列表，用于关键词匹配。 | `["重症监护", "直升机停机坪"]` |
| `description.capacity` | object | 否 | 具体的容量指标（动态结构）。 | `{"total_beds": 1200}` |

### 2.4 联系人与排班 (Contact & Roster)

这是本设计的核心，支持“不同时间找不同人”的场景。

| 字段名 | 类型 | 必填 | 说明 | 示例 |
| :--- | :--- | :--- | :--- | :--- |
| `contact.general_phone` | string | 是 | 24小时对外总机/值班室电话。 | `"0771-1201234"` |
| `contact.emergency_channel` | string | 否 | 无线电通讯频道。 | `"400.150MHz"` |
| `contact.default_contact` | object | 是 | 兜底联系人（当排班表查不到时使用）。 | `{"name": "总值班", "phone": "..."}` |
| `contact.duty_roster` | list | 否 | 排班规则列表，优先级从上到下。 | (见下文) |

#### 排班规则 (`duty_roster` item)

排班表是一个列表，Agent 查询时应遍历此列表，找到第一个符合当前时间的规则。

**类型 1: 特定日期值班 (`specific_date`)**
优先级最高，用于节假日或特殊时期的临时顶班。
```json
{
  "type": "specific_date",
  "date": "2026-03-01",       // 格式 YYYY-MM-DD
  "shift": "full_day",        // 或具体时间段 "08:00-20:00"
  "name": "王五院长",
  "phone": "13600000000"
}
```

**类型 2: 固定周排班 (`fixed_weekly`)**
用于常规轮班。
```json
{
  "type": "fixed_weekly",
  "day_of_week": 1,           // 1=周一, 7=周日
  "shift": "08:00-20:00",     // 24小时制时间段
  "name": "张三主任",
  "phone": "13800000000"
}
```

### 2.5 元数据 (Metadata)

| 字段名 | 类型 | 必填 | 说明 | 示例 |
| :--- | :--- | :--- | :--- | :--- |
| `metadata.last_updated` | string | 是 | 数据最后更新时间。 | `"2026-02-28"` |
| `metadata.priority_level` | int | 否 | 调度优先级 (1=最高, 5=最低)。<br>用于在资源充足时优先推荐大医院或专业救援队。 | `1` |

## 3. JSON 示例

```json
{
  "id": "res_001",
  "name": "南宁市第一人民医院应急医疗点",
  "type": "medical",
  "status": "active",
  "location": {
    "latitude": 22.8170,
    "longitude": 108.3665,
    "address": "南宁市青秀区七星路89号"
  },
  "description": {
    "summary": "三级甲等综合医院，具备重症监护和直升机救援能力。",
    "capabilities": ["重症监护", "烧伤处理", "直升机停机坪"],
    "capacity": { "emergency_beds": 50 }
  },
  "contact": {
    "general_phone": "0771-1201234",
    "duty_roster": [
      {
        "type": "specific_date",
        "date": "2026-03-01",
        "name": "王五院长",
        "phone": "13600136000"
      },
      {
        "type": "fixed_weekly",
        "day_of_week": 1,
        "shift": "08:00-20:00",
        "name": "张三主任",
        "phone": "13800138000"
      }
    ],
    "default_contact": {
      "name": "总值班室",
      "phone": "0771-2633333"
    }
  },
  "metadata": {
    "last_updated": "2026-02-28",
    "priority_level": 1
  }
}
```
