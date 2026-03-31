import requests

def get_weather_by_location(lng, lat, api_key):
    """
    输入经纬度，自动查询当地天气
    """
    # --- 第1步：通过经纬度获取 adcode (行政区编码) ---
    regeo_url = "https://restapi.amap.com/v3/geocode/regeo"
    regeo_params = {
        "key": api_key,
        "location": f"{lng},{lat}",
        "extensions": "base"
    }
    
    try:
        # 请求逆地理编码
        r1 = requests.get(regeo_url, params=regeo_params, timeout=5)
        data1 = r1.json()
        
        if data1['status'] != '1':
            print(f"定位失败: {data1.get('info')}")
            return

        # 提取 adcode 和 区县名称
        adcode = data1['regeocode']['addressComponent']['adcode']
        district = data1['regeocode']['addressComponent']['district']
        
        print(f"📍 定位成功：{district} (编码: {adcode})")
        
        # --- 第2步：通过 adcode 查询天气 ---
        weather_url = "https://restapi.amap.com/v3/weather/weatherInfo"
        weather_params = {
            "key": api_key,
            "city": adcode,     # 必须传 adcode
            "extensions": "base" # base=实况, all=预报
        }
        
        r2 = requests.get(weather_url, params=weather_params, timeout=5)
        data2 = r2.json()
        
        if data2['status'] == '1' and data2['lives']:
            w = data2['lives'][0]
            print(f"🌤  天气：{w['weather']}")
            print(f"🌡  温度：{w['temperature']}℃")
            print(f"🌬  风向：{w['winddirection']}风 (风力{w['windpower']}级)")
            print(f"💧 湿度：{w['humidity']}%")
            print(f"🕒 发布时间：{w['reporttime']}")
        else:
            print("未查询到天气信息")

    except Exception as e:
        print(f"请求发生错误: {e}")

# --- 运行测试 ---
# 替换你的 Key
MY_KEY = "b78a07dde4df95ad9b9cb75a97cdf10c"
# 测试坐标：北京朝阳区某地
get_weather_by_location(116.482086, 39.990496, MY_KEY)

'''📍 定位成功：朝阳区 (编码: 110105)
🌤  天气：晴
🌡  温度：-4℃
🌬  风向：西南风 (风力≤3级)
💧 湿度：30%
🕒 发布时间：2026-01-21 19:38:09'''