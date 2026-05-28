# API接口替换需求文档

## 一、背景说明

当前项目使用本地静态 JSON 文件存储周边资源（仓库）和专家库数据。为获取实时数据，需要将本地数据读取逻辑替换为API接口调用。

**影响范围：**
- 专家库查询功能
- 仓库（应急物资）查询功能

## 二、API接口信息

### 2.1 基础配置

| 配置项 | 值 |
|--------|-----|
| 基础地址 | `https://tocc.itsgx.cn:10003/prod-api` |
| 鉴权方式 | Header: `X-API-Key: mZRsWLNomAaBrcor9skwqbQUvbwTsFYb` |
| 支持环境变量 | `TOCC_BASE_URL`, `TOCC_API_KEY` |

### 2.2 专家库接口

**接口地址：** `GET /expertAI/list`

**请求示例：**
```python
import requests
import os

base_url = os.getenv("TOCC_BASE_URL", "https://tocc.itsgx.cn:10003/prod-api").rstrip("/")
api_key = os.getenv("TOCC_API_KEY", "mZRsWLNomAaBrcor9skwqbQUvbwTsFYb")

resp = requests.get(
    f"{base_url}/expertAI/list",
    headers={"X-API-Key": api_key, "Accept": "application/json"}
)
data = resp.json()
```

**返回结构：**
```json
{
  "code": 200,
  "msg": "success",
  "totle": 573,
  "data": [/* 专家列表 */]
}
```

**可用查询参数：**
| 参数 | 类型 | 说明 |
|------|------|------|
| name | String | 姓名 |
| sex | String | 性别（0男 1女 2未知） |
| specialtyField | String | 擅长专业 |
| professionalTitle | String | 职称 |
| workUnit | String | 工作单位 |
| experStatus | String | 专家状态（1启用 2停用） |

### 2.3 仓库接口

**接口地址：** `GET /warehouseAi/list`

**请求示例：**
```python
resp = requests.get(
    f"{base_url}/warehouseAi/list",
    headers={"X-API-Key": api_key, "Accept": "application/json"}
)
data = resp.json()
```

**返回结构：**
```json
{
  "code": 200,
  "msg": "查询成功",
  "total": 275,
  "rows": [/* 仓库列表 */],
  "pageNum": 1,
  "pageSize": 10
}
```

**可用查询参数：**
| 参数 | 类型 | 说明 |
|------|------|------|
| pageNum | Integer | 页码，默认1 |
| pageSize | Integer | 每页条数，默认10 |
| warehouseName | String | 仓库名称 |
| belongOrgName | String | 所属单位名称 |
| address | String | 详细地址 |
| roadCode | String | 路段编号 |
| materialName | String | 物资名称（模糊查询） |
| verificationState | String | 检录状态：0未检录 1已检录 2逾期 3需更新 |

## 三、字段映射关系

### 3.1 专家库字段映射

| 本地JSON字段 | API返回字段 | 说明 |
|-------------|-------------|------|
| id | id | 专家ID |
| name | name | 姓名 |
| sex | sex | 性别 |
| birthday | birthday | 出生日期 |
| dept_id | deptId | 部门ID |
| specialty_field | specialtyField | 擅长专业 |
| duties | duties | 职务 |
| professional_title | professionalTitle | 职称 |
| work_unit | workUnit | 工作单位 |
| education | education | 学历 |
| major | major | 专业 |
| graduation_school | graduationSchool | 毕业院校 |
| phone | phone | 联系电话 |
| email | email | 邮箱 |
| address | address | 地址 |
| longitude | longitude | 经度 |
| latitude | latitude | 纬度 |
| declaration_type | declarationType | 申报类型 |
| exper_status | experStatus | 专家状态 |
| remark | remark | 备注 |

**API新增字段（本地没有）：**
- `deptName` - 部门名称
- `createTime` - 创建时间
- `updateTime` - 更新时间
- `distance` - 距离
- `isAssociated` - 是否已关联
- `delFlag` - 删除标记

### 3.2 仓库字段映射

| 本地JSON字段 | API返回字段 | 说明 |
|-------------|-------------|------|
| id | id | 仓库ID |
| warehouse_name | warehouseName | 仓库名称 |
| warehouse_type | warehouseType | 仓库类型 |
| belong_org_code | belongOrgCode | 所属单位code |
| belong_org_name | belongOrgName | 所属单位名称 |
| address | address | 详细地址 |
| principal | principal | 负责人 |
| contact_phone | contactPhone | 联系电话 |
| road_code | roadCode | 路段编号 |
| stake | stake | 桩号 |
| latitude | latitude | 纬度 |
| longitude | longitude | 经度 |
| remark | remark | 备注 |
| create_time | createTime | 创建时间 |
| verification_state | verificationState | 检录状态 |
| unitor | unitor | 检录人 |
| unitor_id | unitorId | 检录人ID |
| unitor_tel | unitorTel | 检录人电话 |

**API新增字段（本地没有）：**
- `warehouseTypeName` - 仓库类型名称
- `creator` - 创建人
- `updateTime` - 更新时间
- `updater` - 更新人
- `materials` - 物资列表
- `equipments` - 装备列表
- `totalMaterialCount` - 物资总数
- `distance` - 距离
- `isAssociated` - 是否已关联
- `nextDueAt` - 下次检录截止时间

**本地字段（API没有）：**
- `del_flag` - 删除标记
- `last_verified_at` - 最后检录时间

## 四、代码实现建议

### 4.1 封装API客户端

```python
# api_client.py
import os
import requests
from typing import List, Dict, Optional

class ToccApiClient:
    """TOCC API客户端"""

    def __init__(self):
        self.base_url = os.getenv("TOCC_BASE_URL", "https://tocc.itsgx.cn:10003/prod-api").rstrip("/")
        self.api_key = os.getenv("TOCC_API_KEY", "mZRsWLNomAaBrcor9skwqbQUvbwTsFYb")
        self.headers = {
            "X-API-Key": self.api_key,
            "Accept": "application/json"
        }

    def get_experts(self, **filters) -> List[Dict]:
        """获取专家列表

        Args:
            **filters: 查询过滤条件（name, specialtyField, workUnit等）

        Returns:
            专家列表
        """
        resp = requests.get(
            f"{self.base_url}/expertAI/list",
            headers=self.headers,
            params=filters,
            timeout=15
        )
        data = resp.json()
        return data.get("data", [])

    def get_warehouses(self, page: int = 1, page_size: int = 100, **filters) -> Dict:
        """获取仓库列表

        Args:
            page: 页码
            page_size: 每页条数
            **filters: 查询过滤条件（warehouseName, belongOrgName等）

        Returns:
            包含仓库列表和总数的字典
        """
        params = {"pageNum": page, "pageSize": page_size, **filters}
        resp = requests.get(
            f"{self.base_url}/warehouseAi/list",
            headers=self.headers,
            params=params,
            timeout=15
        )
        return resp.json()
```

### 4.2 使用示例

```python
# 使用示例
client = ToccApiClient()

# 获取所有专家
experts = client.get_experts()
print(f"专家总数: {len(experts)}")

# 按专业筛选专家
bridge_experts = client.get_experts(specialtyField="桥梁")

# 获取仓库数据
result = client.get_warehouses(page=1, page_size=100)
warehouses = result.get("rows", [])
total = result.get("total", 0)
print(f"仓库总数: {total}, 当前页: {len(warehouses)}")

# 按条件筛选仓库
result = client.get_warehouses(warehouseName="应急")
```

## 五、注意事项

1. **字段命名差异：** API返回字段使用驼峰命名（如 `specialtyField`），本地JSON使用下划线命名（如 `specialty_field`），需要进行映射或统一

2. **分页处理：** 仓库接口支持分页，如需获取全部数据，需要循环调用或设置较大的 `pageSize`

3. **错误处理：**
   - 专家库接口约 573 条数据
   - 仓库接口约 275 条数据
   - 建议添加超时和异常处理

4. **性能考虑：**
   - 可以考虑添加本地缓存机制
   - 对于频繁调用的场景，可以定时刷新缓存

5. **数据差异：** API数据比本地数据略少，可能是因为API只返回启用/有效状态的数据

## 六、测试脚本参考

已提供的测试脚本位于 `traffic-emergency-agent/req_for_data/` 目录：

- `test_expertAI.py` - 测试专家库接口
- `test_warehouseAi.py` - 测试仓库接口

可直接运行测试：
```bash
python traffic-emergency-agent/req_for_data/test_expertAI.py
python traffic-emergency-agent/req_for_data/test_warehouseAi.py
```
