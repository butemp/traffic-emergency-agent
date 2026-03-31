"""
高德地图API工具集

提供地理信息、交通状况、天气查询等功能，用于支持应急指挥决策。
"""

import json
import logging
import os
import requests
from typing import Any, Dict, Optional
from .base import BaseTool

logger = logging.getLogger(__name__)


# 共享的API Key配置
class GaodeConfig:
    """高德API配置"""
    # 默认API Key（可以通过环境变量覆盖）
    API_KEY = os.getenv("GAODE_API_KEY", "b78a07dde4df95ad9b9cb75a97cdf10c")
    BASE_URL = "https://restapi.amap.com/v3"

    @classmethod
    def set_api_key(cls, api_key: str):
        """设置API Key"""
        cls.API_KEY = api_key

    @classmethod
    def get_headers(cls):
        """获取请求头"""
        return {
            "Content-Type": "application/json"
        }


class CheckTrafficStatus(BaseTool):
    """
    查询指定坐标点周边的交通拥堵情况
    """

    @property
    def name(self) -> str:
        return "check_traffic_status"

    @property
    def description(self) -> str:
        return """查询指定坐标点周边的交通拥堵情况，实时获取道路通行状态。

适用于路线规划、出行建议、交通状况分析等场景。返回整体路况评估（畅通/缓行/拥堵）和具体道路详情。

使用场景：
- 用户询问某地的交通状况
- 需要评估事故对周边交通的影响
- 规划救援路线时需要避开拥堵路段

参数说明：
- longitude: 经度坐标
- latitude: 纬度坐标
- radius: 搜索半径（米），默认1500，最大5000
- level: 道路等级，默认5（主干道）
"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "longitude": {
                    "type": "number",
                    "description": "经度坐标，如北京116.48"
                },
                "latitude": {
                    "type": "number",
                    "description": "纬度坐标，如北京39.99"
                },
                "radius": {
                    "type": "integer",
                    "description": "搜索半径（米），默认1500，最大5000",
                    "default": 1500,
                    "minimum": 1,
                    "maximum": 5000
                }
            },
            "required": ["longitude", "latitude"]
        }

    def execute(
        self,
        longitude: float,
        latitude: float,
        radius: int = 1500
    ) -> str:
        """执行交通状态查询"""
        logger.info(f"查询交通状况: ({longitude}, {latitude}), 半径={radius}米")

        url = f"{GaodeConfig.BASE_URL}/traffic/status/circle"
        params = {
            "key": GaodeConfig.API_KEY,
            "location": f"{longitude},{latitude}",
            "radius": radius,
            "level": 5
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            data = response.json()

            if data.get('status') == '1':
                info = data.get('trafficinfo', {})

                # 解析拥堵状态
                evaluation = info.get('evaluation', {})
                status_code = evaluation.get('status', '0')
                status_map = {
                    '1': '畅通',
                    '2': '缓行',
                    '3': '拥堵',
                    '0': '未知'
                }

                result = {
                    "status": "success",
                    "traffic_status": status_map.get(status_code, "未知"),
                    "description": info.get('description', ''),
                    "roads": []
                }

                # 提取具体道路信息
                if 'roads' in info:
                    for road in info['roads'][:10]:  # 最多返回10条
                        result["roads"].append({
                            "name": road.get('name', ''),
                            "status": road.get('status_desc', ''),
                            "speed": road.get('speed', 0),
                            "direction": road.get('direction', '')
                        })

                logger.info(f"查询成功: 状态={result['traffic_status']}")
                return json.dumps(result, ensure_ascii=False, indent=2)
            else:
                error_msg = data.get('info', '未知错误')
                logger.error(f"查询失败: {error_msg}")
                return json.dumps({
                    "status": "error",
                    "message": error_msg
                }, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"请求异常: {e}")
            return json.dumps({
                "status": "error",
                "message": str(e)
            }, ensure_ascii=False, indent=2)


class GetWeatherByLocation(BaseTool):
    """
    通过经纬度查询天气信息
    """

    @property
    def name(self) -> str:
        return "get_weather_by_location"

    @property
    def description(self) -> str:
        return """通过经纬度查询指定地点的实时天气信息。

支持获取当前天气状况和未来天气预报，适用于出行规划、户外活动安排等场景。

使用场景：
- 用户询问某地的天气情况
- 评估天气对应急处置的影响
- 雨雪天气需要调整救援方案

参数说明：
- longitude: 经度坐标
- latitude: 纬度坐标
- extensions: 'base'=实况天气，'all'=天气预报
"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "longitude": {
                    "type": "number",
                    "description": "经度坐标"
                },
                "latitude": {
                    "type": "number",
                    "description": "纬度坐标"
                },
                "extensions": {
                    "type": "string",
                    "description": "天气类型：base=实况，all=预报",
                    "default": "base",
                    "enum": ["base", "all"]
                }
            },
            "required": ["longitude", "latitude"]
        }

    def execute(
        self,
        longitude: float,
        latitude: float,
        extensions: str = "base"
    ) -> str:
        """执行天气查询"""
        logger.info(f"查询天气: ({longitude}, {latitude}), 类型={extensions}")

        # 第一步：逆地理编码获取adcode
        regeo_url = f"{GaodeConfig.BASE_URL}/geocode/regeo"
        regeo_params = {
            "key": GaodeConfig.API_KEY,
            "location": f"{longitude},{latitude}",
            "extensions": "base"
        }

        try:
            # 获取adcode
            r1 = requests.get(regeo_url, params=regeo_params, timeout=10)
            data1 = r1.json()

            if data1.get('status') != '1':
                error_msg = data1.get('info', '定位失败')
                logger.error(f"逆地理编码失败: {error_msg}")
                return json.dumps({
                    "status": "error",
                    "message": f"定位失败: {error_msg}"
                }, ensure_ascii=False, indent=2)

            # 提取adcode
            adcode = data1['regeocode']['addressComponent']['adcode']
            district = data1['regeocode']['addressComponent']['district']

            # 第二步：查询天气
            weather_url = f"{GaodeConfig.BASE_URL}/weather/weatherInfo"
            weather_params = {
                "key": GaodeConfig.API_KEY,
                "city": adcode,
                "extensions": extensions
            }

            r2 = requests.get(weather_url, params=weather_params, timeout=10)
            data2 = r2.json()

            if data2.get('status') == '1':
                if extensions == "base" and data2.get('lives'):
                    # 实况天气
                    w = data2['lives'][0]
                    result = {
                        "status": "success",
                        "location": district,
                        "weather": w.get('weather'),
                        "temperature": f"{w.get('temperature')}℃",
                        "wind_direction": w.get('winddirection'),
                        "wind_power": w.get('windpower'),
                        "humidity": f"{w.get('humidity')}%",
                        "report_time": w.get('reporttime')
                    }
                elif extensions == "all" and data2.get('forecasts'):
                    # 预报天气
                    f = data2['forecasts'][0]
                    result = {
                        "status": "success",
                        "location": district,
                        "province": f.get('province'),
                        "city": f.get('city'),
                        "report_time": f.get('reporttime'),
                        "casts": f.get('casts', [])
                    }
                else:
                    result = {
                        "status": "success",
                        "message": "未获取到天气数据"
                    }

                logger.info(f"查询成功: {district}")
                return json.dumps(result, ensure_ascii=False, indent=2)
            else:
                error_msg = data2.get('info', '天气查询失败')
                logger.error(f"天气查询失败: {error_msg}")
                return json.dumps({
                    "status": "error",
                    "message": error_msg
                }, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"请求异常: {e}")
            return json.dumps({
                "status": "error",
                "message": str(e)
            }, ensure_ascii=False, indent=2)


class GeocodeAddress(BaseTool):
    """
    将地址转换为经纬度坐标
    """

    @property
    def name(self) -> str:
        return "geocode_address"

    @property
    def description(self) -> str:
        return """将自然语言地址转换为精确的经纬度坐标。

支持从简单地址到复杂详细地址的解析，适用于地图标注、位置定位、距离计算等场景。

使用场景：
- 用户提供"北京市朝阳区建国路88号"等地址
- 需要将地址转换为坐标后再查询天气/交通
- 用户描述灾害发生地点使用的是地址而非坐标

参数说明：
- address: 待转换的地址字符串
- city: 指定城市（可选，提高准确性）
"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": "待转换的地址，如'北京市朝阳区建国路88号'"
                },
                "city": {
                    "type": "string",
                    "description": "指定城市，如'北京市'，可提高准确性"
                }
            },
            "required": ["address"]
        }

    def execute(self, address: str, city: str = "") -> str:
        """执行地址编码"""
        logger.info(f"地址编码: address='{address}', city='{city}'")

        url = f"{GaodeConfig.BASE_URL}/geocode/geo"
        params = {
            "key": GaodeConfig.API_KEY,
            "address": address
        }

        if city:
            params["city"] = city

        try:
            response = requests.get(url, params=params, timeout=10)
            data = response.json()

            if data.get('status') == '1':
                geocodes = data.get('geocodes', [])

                if geocodes:
                    # 返回第一个（最相关）结果
                    geo = geocodes[0]
                    location = geo.get('location', '').split(',')

                    result = {
                        "status": "success",
                        "count": len(geocodes),
                        "formatted_address": geo.get('formatted_address', ''),
                        "longitude": float(location[0]) if len(location) > 0 else None,
                        "latitude": float(location[1]) if len(location) > 1 else None,
                        "level": geo.get('level', ''),
                        "adcode": geo.get('adcode', '')
                    }

                    logger.info(f"编码成功: {result['formatted_address']} → ({result['longitude']}, {result['latitude']})")
                    return json.dumps(result, ensure_ascii=False, indent=2)
                else:
                    logger.warning("未找到匹配的地址")
                    return json.dumps({
                        "status": "not_found",
                        "message": "未找到匹配的地址，请尝试更详细的地址描述"
                    }, ensure_ascii=False, indent=2)
            else:
                error_msg = data.get('info', '地址编码失败')
                logger.error(f"编码失败: {error_msg}")
                return json.dumps({
                    "status": "error",
                    "message": error_msg
                }, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"请求异常: {e}")
            return json.dumps({
                "status": "error",
                "message": str(e)
            }, ensure_ascii=False, indent=2)


class ReverseGeocode(BaseTool):
    """
    将经纬度坐标转换为地址描述
    """

    @property
    def name(self) -> str:
        return "reverse_geocode"

    @property
    def description(self) -> str:
        return """将经纬度坐标转换为人类可读的详细地址描述。

适用于GPS定位后的地址显示、地图坐标标注解释、位置分享等场景。

使用场景：
- 需要将坐标转换为可读地址
- 确认坐标对应的实际位置
- 用户提供了坐标需要确认地点

参数说明：
- longitude: 经度坐标
- latitude: 纬度坐标
- radius: 搜索半径（米）
- extensions: 'base'=基础信息，'all'=详细信息
"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "longitude": {
                    "type": "number",
                    "description": "经度坐标"
                },
                "latitude": {
                    "type": "number",
                    "description": "纬度坐标"
                },
                "radius": {
                    "type": "integer",
                    "description": "搜索半径（米），默认1000",
                    "default": 1000
                },
                "extensions": {
                    "type": "string",
                    "description": "返回详细程度：base=基础，all=详细",
                    "default": "base",
                    "enum": ["base", "all"]
                }
            },
            "required": ["longitude", "latitude"]
        }

    def execute(
        self,
        longitude: float,
        latitude: float,
        radius: int = 1000,
        extensions: str = "base"
    ) -> str:
        """执行逆地理编码"""
        logger.info(f"逆地理编码: ({longitude}, {latitude})")

        url = f"{GaodeConfig.BASE_URL}/geocode/regeo"
        params = {
            "key": GaodeConfig.API_KEY,
            "location": f"{longitude},{latitude}",
            "extensions": extensions,
            "radius": radius
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            data = response.json()

            if data.get('status') == '1':
                regeocode = data.get('regeocode', {})

                result = {
                    "status": "success",
                    "formatted_address": regeocode.get('formatted_address', ''),
                    "address_component": regeocode.get('addressComponent', {})
                }

                logger.info(f"解码成功: {result['formatted_address']}")
                return json.dumps(result, ensure_ascii=False, indent=2)
            else:
                error_msg = data.get('info', '逆地理编码失败')
                logger.error(f"解码失败: {error_msg}")
                return json.dumps({
                    "status": "error",
                    "message": error_msg
                }, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"请求异常: {e}")
            return json.dumps({
                "status": "error",
                "message": str(e)
            }, ensure_ascii=False, indent=2)


class SearchNearbyPOIs(BaseTool):
    """
    搜索周边兴趣点（POI）
    """

    @property
    def name(self) -> str:
        return "search_nearby_pois"

    @property
    def description(self) -> str:
        return """基于指定位置搜索周边的兴趣点（POI）。

支持查找医院、消防队、加油站等各类应急资源设施。适用于应急资源调度、周边设施查找等场景。

使用场景：
- 用户询问"附近有什么医院"
- 需要查找周边的消防队、加油站
- 查询周边的应急避难场所

参数说明：
- longitude: 经度坐标
- latitude: 纬度坐标
- keywords: 搜索关键词，如'医院'、'消防队'、'加油站'
- radius: 搜索半径（米），默认1000，最大50000
- sortrule: 'distance'=按距离排序，'weight'=按综合权重排序
"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "longitude": {
                    "type": "number",
                    "description": "经度坐标"
                },
                "latitude": {
                    "type": "number",
                    "description": "纬度坐标"
                },
                "keywords": {
                    "type": "string",
                    "description": "搜索关键词，如'医院'、'加油站'、'消防队'"
                },
                "radius": {
                    "type": "integer",
                    "description": "搜索半径（米），默认1000，最大50000",
                    "default": 1000,
                    "minimum": 1,
                    "maximum": 50000
                },
                "sortrule": {
                    "type": "string",
                    "description": "排序方式：distance=距离，weight=权重",
                    "default": "distance",
                    "enum": ["distance", "weight"]
                }
            },
            "required": ["longitude", "latitude", "keywords"]
        }

    def execute(
        self,
        longitude: float,
        latitude: float,
        keywords: str,
        radius: int = 1000,
        sortrule: str = "distance"
    ) -> str:
        """执行周边POI搜索"""
        logger.info(f"搜索周边POI: ({longitude}, {latitude}), 关键词='{keywords}', 半径={radius}米")

        url = f"{GaodeConfig.BASE_URL}/place/around"
        all_pois = []
        page = 1
        max_pages = 3  # 限制最多3页（60条结果）

        try:
            while page <= max_pages:
                params = {
                    "key": GaodeConfig.API_KEY,
                    "location": f"{longitude},{latitude}",
                    "keywords": keywords,
                    "radius": radius,
                    "sortrule": sortrule,
                    "offset": 20,
                    "page": page,
                    "extensions": "all"
                }

                response = requests.get(url, params=params, timeout=10)
                data = response.json()

                if data.get('status') == '1':
                    pois = data.get('pois', [])

                    if not pois:
                        break  # 当前页无数据，结束

                    for poi in pois:
                        all_pois.append({
                            "name": poi.get('name', ''),
                            "type": poi.get('type', ''),
                            "distance": poi.get('distance', ''),
                            "address": poi.get('address', ''),
                            "location": poi.get('location', ''),
                            "tel": poi.get('tel', '')
                        })

                    logger.debug(f"第{page}页获取{len(pois)}条POI")
                    page += 1
                else:
                    error_msg = data.get('info', '搜索失败')
                    logger.error(f"搜索失败: {error_msg}")
                    return json.dumps({
                        "status": "error",
                        "message": error_msg
                    }, ensure_ascii=False, indent=2)

            result = {
                "status": "success",
                "count": len(all_pois),
                "pois": all_pois
            }

            logger.info(f"搜索成功: 找到{len(all_pois)}个POI")
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"请求异常: {e}")
            return json.dumps({
                "status": "error",
                "message": str(e)
            }, ensure_ascii=False, indent=2)
