import requests

def get_traffic_around(lng, lat, api_key, radius=1500):
    """
    查询坐标点周边的交通拥堵情况
    radius: 搜索半径，单位米 (最大5000)
    """
    url = "https://restapi.amap.com/v3/traffic/status/circle"
    params = {
        "key": api_key,
        "location": f"{lng},{lat}",
        "radius": radius,
        "level": 5,      # 5=关注主干道 (不填则包含所有小路)
        "extensions": "base"
    }
    
    try:
        response = requests.get(url, params=params, timeout=5)
        data = response.json()
        
        if data['status'] == '1':
            info = data['trafficinfo']
            desc = info['description']
            
            # 解析拥堵状态码：1:畅通, 2:缓行, 3:拥堵
            status_map = {'1': '🟢 畅通', '2': '🟡 缓行', '3': '🔴 拥堵', '0': '⚪️ 未知'}
            status_code = info['evaluation']['status']
            status_text = status_map.get(status_code, "未知")
            
            print(f"🚗 整体路况：{status_text}")
            print(f"📝 详细描述：{desc}")
            
            # 如果想看具体哪条路堵，可以遍历 roads 字段
            if 'roads' in info:
                print("\n--- 主要道路详情 ---")
                for road in info['roads'][:5]: # 只显示前5条
                    print(f"• {road['name']}: {road['status_desc']} (平均速度 {road['speed']}km/h)")
        else:
            print(f"查询失败: {data.get('info')}")
            
    except Exception as e:
        print(f"请求发生错误: {e}")

# --- 运行测试 ---
# 替换你的 Key
MY_KEY = "b78a07dde4df95ad9b9cb75a97cdf10c"
# 测试坐标
get_traffic_around(116.482086, 39.990496, MY_KEY)

'''🚗 整体路况：🟡 缓行
📝 详细描述：酒仙桥路：从酒仙桥北路到芳园西路严重拥堵；京密路：五元桥附近进京方向行驶缓慢；芳园西路：从将台西路到将台路行驶缓慢；万红路：自西向东畅通，反向缓慢。'''