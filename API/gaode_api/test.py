import requests

API_KEY = "b78a07dde4df95ad9b9cb75a97cdf10c"  # 替换为你的高德 API Key

def geocode(address: str) -> tuple[float, float] | None:
    """将地址/地名转换为经纬度坐标"""
    url = "https://restapi.amap.com/v3/geocode/geo"
    params = {
        "key": API_KEY,
        "address": address,
    }
    resp = requests.get(url, params=params)
    data = resp.json()

    if data.get("status") == "1" and data["geocodes"]:
        location = data["geocodes"][0]["location"]  # "经度,纬度"
        lng, lat = location.split(",")
        return float(lng), float(lat)
    else:
        print(f"[地理编码失败] 地址: {address}, 错误: {data.get('info')}")
        return None


def driving_route(origin: tuple, destination: tuple, strategy: int = 0) -> dict | None:
    """
    驾车路径规划
    :param origin: 起点 (经度, 纬度)
    :param destination: 终点 (经度, 纬度)
    :param strategy: 路线策略 0=最快 1=最短 2=避收费 3=避高速 4=最优
    :return: 路线详情字典
    """
    url = "https://restapi.amap.com/v3/direction/driving"
    params = {
        "key": API_KEY,
        "origin": f"{origin[0]},{origin[1]}",
        "destination": f"{destination[0]},{destination[1]}",
        "strategy": strategy,
        "output": "json",
    }
    resp = requests.get(url, params=params)
    data = resp.json()

    if data.get("status") == "1":
        route = data["route"]["paths"][0]
        return {
            "距离": f"{float(route['distance']) / 1000:.1f} 公里",
            "预计时间": f"{int(route['duration']) // 60} 分钟",
            "红绿灯数": route.get("traffic_lights", "N/A"),
            "步骤数量": len(route["steps"]),
            "导航步骤": [
                {
                    "指令": step["instruction"],
                    "道路": step.get("road", "未知道路"),
                    "距离": f"{float(step['distance']):.0f} 米",
                }
                for step in route["steps"]
            ],
        }
    else:
        print(f"[路径规划失败] 错误: {data.get('info')}")
        return None


def plan_trip(origin_name: str, destination_name: str):
    """主函数：给定两个地名，输出路径规划结果"""
    print(f"📍 起点: {origin_name}")
    print(f"🏁 终点: {destination_name}\n")

    # Step 1: 地名 → 坐标
    origin_coord = geocode(origin_name)
    dest_coord = geocode(destination_name)

    if not origin_coord or not dest_coord:
        print("地理编码失败，请检查地名或 API Key")
        return

    print(f"起点坐标: {origin_coord}")
    print(f"终点坐标: {dest_coord}\n")

    # Step 2: 路径规划
    result = driving_route(origin_coord, dest_coord)

    if result:
        print(f"🚗 总距离: {result['距离']}")
        print(f"⏱  预计时间: {result['预计时间']}")
        print(f"🚦 红绿灯数: {result['红绿灯数']}")
        print(f"\n📋 导航步骤（共 {result['步骤数量']} 步）:")
        for i, step in enumerate(result["导航步骤"], 1):
            print(f"  {i:>2}. [{step['道路']}] {step['指令']} ({step['距离']})")


# ========== 运行示例 ==========
if __name__ == "__main__":
    plan_trip("北京天安门", "北京首都国际机场")

# 📍 起点: 北京天安门
# 🏁 终点: 北京首都国际机场

# 起点坐标: (116.397463, 39.909187)
# 终点坐标: (116.602545, 40.080213)

# 🚗 总距离: 29.6 公里
# ⏱  预计时间: 34 分钟
# 🚦 红绿灯数: 13

# 📋 导航步骤（共 17 步）:
#    1. [未知道路] 向北行驶396米右转 (396 米)
#    2. [东华门路] 沿东华门路向东行驶79米左转 (79 米)
#    3. [东华门路] 沿东华门路向东北行驶539米右转 (539 米)
#    4. [东华门大街] 沿东华门大街向东行驶107米左转 (107 米)
#    5. [北池子大街] 沿北池子大街向北行驶918米右转 (918 米)
#    6. [五四大街] 沿五四大街途径东四西大街、朝阳门内大街向东行驶2.7千米进入环岛 (2688 米)
#    7. [未知道路] 向东北行驶191米离开环岛 (191 米)
#    8. [朝阳门北大街] 沿朝阳门北大街向北行驶435米向左前方行驶进入主路 (435 米)
#    9. [东二环入口] 沿东二环入口途径东二环向北行驶1.9千米向右前方行驶进入匝道 (1871 米)
#   10. [东直门北桥] 沿东直门北桥途径S12机场高速向东北行驶17.9千米减速行驶到达收费站 (17867 米)
#   11. [S12机场高速] 沿S12机场高速向东北行驶314米靠左进入左岔路 (314 米)
#   12. [S12机场高速] 沿S12机场高速向北行驶3.0千米靠左 (2971 米)
#   13. [S12机场高速出口] 沿S12机场高速出口向北行驶470米向右后方行驶 (470 米)