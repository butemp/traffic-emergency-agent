import requests

def get_address_by_location(lng, lat, api_key):
    """
    输入：经度(lng), 纬度(lat), 高德Key
    输出：详细地址字符串，如果失败返回 None
    """
    url = "https://restapi.amap.com/v3/geocode/regeo"
    params = {
        "key": api_key,
        "location": f"{lng},{lat}", # 自动拼接为 "经度,纬度"
        "extensions": "base",       # 如果只想要地址字符串，用 base 更快、省流量
        "radius": 1000
    }
    
    try:
        res = requests.get(url, params=params, timeout=5)
        data = res.json()
        
        if data.get("status") == "1":
            # 提取完整地址
            return data["regeocode"]["formatted_address"]
        else:
            print(f"请求错误: {data.get('info')}")
            return None
            
    except Exception as e:
        print(f"网络或解析异常: {e}")
        return None

# 测试
my_key = "b78a07dde4df95ad9b9cb75a97cdf10c"
# 注意：经度在前
address = get_address_by_location(108, 22, my_key)
print(f"查询结果: {address}")

# 广西壮族自治区防城港市上思县叫安镇016乡道