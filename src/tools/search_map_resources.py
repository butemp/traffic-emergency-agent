"""
地图资源检索工具

基于本地JSON数据，提供地理位置检索、类型筛选和智能排班计算。
"""

import json
import logging
import math
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import BaseTool

logger = logging.getLogger(__name__)


class SearchMapResources(BaseTool):
    """
    地图资源检索工具

    功能：
    1. 加载本地 Geo-JSON 数据
    2. 计算坐标距离 (Haversine 公式)
    3. 根据当前时间解析排班表，返回当前负责人
    """

    def __init__(self, data_dir: str = "data/graph"):
        """
        初始化

        Args:
            data_dir: 存放资源JSON文件的目录
        """
        self.data_dir = data_dir
        self.resources = []
        self._load_data()

    def _load_data(self):
        """加载数据目录下所有的JSON文件"""
        path = Path(self.data_dir)
        if not path.exists():
            logger.warning(f"地图数据目录不存在: {self.data_dir}")
            return

        count = 0
        for file_path in path.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.resources.extend(data)
                        count += len(data)
                    else:
                        logger.warning(f"文件格式错误（应为列表）: {file_path}")
            except Exception as e:
                logger.error(f"加载地图资源失败 {file_path}: {e}")
        
        logger.info(f"成功加载 {count} 个地图资源")

    @property
    def name(self) -> str:
        return "search_map_resources"

    @property
    def description(self) -> str:
        return """查询内部应急资源（医院、消防队、物资库、警力等）。

功能特点：
1. **必须提供经纬度**：不同于文本搜索，此工具需要使用 `geocode_address` 获取坐标后，基于经纬度搜索。
2. 支持按类型(medical/fire/police/inventory)筛选
3. 支持按距离排序
4. **自动计算当前值班负责人**：会根据当前时间查询排班表，返回具体联系人

使用场景：
- "基于坐标(22.81, 108.36)查找附近的医院"
- "该事故点周边的消防力量"

参数说明：
- keywords: 关键词（如"直升机", "重症监护"）
- resource_type: 资源类型 (medical, fire, police, inventory, transport)
- center_lat: **必填** 中心点纬度，用于计算距离
- center_lon: **必填** 中心点经度，用于计算距离
- radius_km: 搜索半径（公里），默认 20km
"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "string",
                    "description": "搜索关键词，如'直升机', '烧伤'"
                },
                "resource_type": {
                    "type": "string",
                    "enum": ["medical", "fire", "police", "inventory", "transport"],
                    "description": "资源类型"
                },
                "center_lat": {
                    "type": "number",
                    "description": "中心点纬度，用于计算距离（如果用户提供的是地址，请先调用 geocode_address 获取坐标）"
                },
                "center_lon": {
                    "type": "number",
                    "description": "中心点经度，用于计算距离（如果用户提供的是地址，请先调用 geocode_address 获取坐标）"
                },
                "radius_km": {
                    "type": "number",
                    "description": "搜索半径（公里），默认 50",
                    "default": 50
                }
            },
            "required": ["center_lat", "center_lon"]
        }

    def _calculate_distance(self, lat1, lon1, lat2, lon2) -> float:
        """Haversine公式计算两点距离（公里）"""
        R = 6371  # 地球半径
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat/2) * math.sin(dlat/2) + \
            math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * \
            math.sin(dlon/2) * math.sin(dlon/2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        return R * c

    def _get_current_contact(self, contact_info: Dict) -> Dict:
        """根据当前时间解析排班表"""
        now = datetime.now()
        today_date_str = now.strftime("%Y-%m-%d")
        # Python weekday: Mon=0, Sun=6. Resource format: Mon=1, Sun=7
        current_weekday = now.weekday() + 1 
        
        roster = contact_info.get("duty_roster", [])
        
        # 1. 优先匹配特定日期 (specific_date)
        for rule in roster:
            if rule.get("type") == "specific_date" and rule.get("date") == today_date_str:
                return {
                    "name": rule["name"],
                    "phone": rule["phone"],
                    "role": f"值班人员 ({today_date_str} 特勤)"
                }

        # 2. 其次匹配每周固定排班 (fixed_weekly)
        for rule in roster:
            if rule.get("type") == "fixed_weekly" and rule.get("day_of_week") == current_weekday:
                # 简单处理：暂不校验 shift 具体时间段，命中星期几就算
                return {
                    "name": rule["name"],
                    "phone": rule["phone"],
                    "role": f"值班人员 (周{current_weekday} 轮值)"
                }

        # 3. 兜底使用默认联系人
        default = contact_info.get("default_contact", {})
        return {
            "name": default.get("name", "N/A"),
            "phone": default.get("phone", "N/A"),
            "role": "默认联系人"
        }

    def execute(
        self,
        keywords: Optional[str] = None,
        resource_type: Optional[str] = None,
        center_lat: Optional[float] = None,
        center_lon: Optional[float] = None,
        radius_km: float = 50
    ) -> str:
        """执行搜索"""
        results = []
        
        logger.info(f"搜索地图资源: type={resource_type}, keywords={keywords}, loc=({center_lat}, {center_lon})")

        for res in self.resources:
            # 1. 类型过滤
            if resource_type and res.get("type") != resource_type:
                continue

            # 2. 关键词过滤 (名称 + 描述 + capability)
            if keywords:
                k = keywords.lower()
                text = (
                    res.get("name", "") + 
                    res.get("description", {}).get("summary", "") + 
                    " ".join(res.get("description", {}).get("capabilities", []))
                ).lower()
                if k not in text:
                    continue

            # 3. 距离过滤 (由于 center_lat 是必填，这里直接计算)
            res_lat = res["location"].get("latitude")
            res_lon = res["location"].get("longitude")

            if res_lat is None or res_lon is None:
                continue

            dist = self._calculate_distance(center_lat, center_lon, res_lat, res_lon)
            
            if dist > radius_km:
                continue
            
            res["_distance"] = dist

            # 4. 格式化输出 (包括计算联系人)
            current_contact = self._get_current_contact(res.get("contact", {}))
            
            # 安全获取 description 字段
            description = res.get("description", {})
            capabilities = description.get("capabilities", []) if description else []
            capacity = description.get("capacity", {}) if description else {}

            results.append({
                "id": res.get("id"),
                "name": res.get("name"),
                "type": res.get("type"),
                "distance_km": round(dist, 2) if dist != -1 else None,
                "address": res["location"]["address"],
                "latitude": res_lat,
                "longitude": res_lon,
                "contact_person": current_contact["name"],
                "contact_phone": current_contact["phone"],
                "contact_role": current_contact["role"],
                "capabilities": capabilities,
                "capacity": capacity
            })

        # 5. 排序：如果有距离，按距离升序
        if center_lat is not None:
            results.sort(key=lambda x: x["distance_km"])

        # 6. 生成结果文本，包含地图信息
        if not results:
            return "未找到符合条件的资源。"

        # 如果找到了资源，构建 JSON 结构的详细结果，以便前端解析
        # 注意：这里我们返回一个特殊的 JSON 字符串，包含 `_is_map_result`: true 标记
        
        display_text_lines = [f"共找到 {len(results)} 个资源："]
        for i, item in enumerate(results[:5]):
            dist_str = f" (距离 {item['distance_km']} km)" if item['distance_km'] is not None else ""
            display_text_lines.append(
                f"\n{i+1}. **{item['name']}** [{item['type']}]{dist_str}\n"
                f"   📍 地址: {item['address']}\n"
                f"   📞 联系: {item['contact_person']} ({item['contact_role']}) - **{item['contact_phone']}**"
                # f"   🛠️ 能力: {', '.join(item['capabilities'])}\n"
            )
        
        display_text = "\n".join(display_text_lines)
        
        # 构造返回给 Agent 的结果，同时包含结构化数据供前端绘图
        final_result = {
            "display_text": display_text,
            "resources": results[:5], # 只返回前5个给前端绘图
            "center": {"lat": center_lat, "lon": center_lon} if center_lat else None,
            "_is_map_result": True
        }
        
        return json.dumps(final_result, ensure_ascii=False)
