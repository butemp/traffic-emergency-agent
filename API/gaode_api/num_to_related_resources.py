import requests

def search_nearby_resources(lng, lat, keyword, api_key, radius=1000):
    """
    根据经纬度查找周边资源
    :param keyword: 搜索关键词，如 "充电桩"
    :param radius: 搜索半径（米）
    """
    url = "https://restapi.amap.com/v3/place/around"
    all_pois = []
    page = 1
    
    while True:
        params = {
            "key": api_key,
            "location": f"{lng},{lat}",
            "keywords": keyword,
            "radius": radius,
            "sortrule": "distance",
            "offset": 20, # 每页20条
            "page": page,
            "extensions": "all" # 获取更详细信息（如评分）
        }
        
        try:
            res = requests.get(url, params=params, timeout=5)
            data = res.json()
            
            if data["status"] == "1":
                pois = data.get("pois", [])
                if not pois:
                    break # 如果当前页没有数据，说明取完了
                
                # 简单清洗数据，只取我们关心的字段
                for poi in pois:
                    all_pois.append({
                        "name": poi.get("name"),
                        "type": poi.get("type"),
                        "distance": poi.get("distance"), # 距离（米）
                        "address": poi.get("address"),
                        "location": poi.get("location")
                    })
                
                print(f"第 {page} 页获取成功，本页 {len(pois)} 条...")
                page += 1
                
                # 安全限制：防止数据太多死循环，这里限制最多爬前5页
                if page > 5: 
                    break
            else:
                print(f"API报错: {data.get('info')}")
                break
                
        except Exception as e:
            print(f"请求异常: {e}")
            break
            
    return all_pois

# --- 使用示例 ---
my_key = "b78a07dde4df95ad9b9cb75a97cdf10c"
# 比如：查找当前坐标周围 2公里 内的 "超市"
results = search_nearby_resources(108, 22, "医院", my_key, radius=200000)

print(f"\n总共找到 {len(results)} 个资源：")
for item in results[:3]: # 只打印前3个看看
    print(item)
    
'''第 1 页获取成功，本页 20 条...
第 2 页获取成功，本页 20 条...
第 3 页获取成功，本页 6 条...

总共找到 46 个资源：
{'name': '叫安镇卫生院那荡分院', 'type': '医疗保健服务;综合医院;卫生院', 'distance': '7250', 'address': '016乡道', 'location': '107.949115,21.955108'}
{'name': '叫安卫生院', 'type': '医疗保健服务;综合医院;卫生院', 'distance': '12330', 'address': '思阳镇', 'location': '107.971968,22.107680'}
{'name': '上思县叫安镇卫生院板细分院', 'type': '医疗保健服务;综合医院;卫生院', 'distance': '12567', 'address': '267县道', 'location': '107.883737,22.033594'}'''