import requests

def get_geo(address, key):
    url = "https://restapi.amap.com/v3/geocode/geo"
    params = {
        "key": key,
        "address": address
    }
    response = requests.get(url, params=params)
    return response.json()

# 替换成你的 Key
my_key = "b78a07dde4df95ad9b9cb75a97cdf10c"
result = get_geo("南宁市江南区322国道与210国道交叉口西20米", my_key)
print(result)


#  {'status': '1', 'info': 'OK', 'infocode': '10000', 'count': '2', 'geocodes': [{'formatted_address': '广西壮族自治区南宁市江南区与210国道', 'country': '中国', 'province': '广西壮族自治区', 'citycode': '0771', 'city': '南宁市', 'district': '江南区', 'township': [], 'neighborhood': {'name': [], 'type': []}, 'building': {'name': [], 'type': []}, 'adcode': '450105', 'street': '与210国道', 'number': [], 'location': '108.218310,22.643972', 'level': '道路'}, {'formatted_address': '陕西省榆林市榆阳区榆阳区国道与210国道', 'country': '中国', 'province': '陕西省', 'citycode': '0912', 'city': '榆林市', 'district': '榆阳区', 'township': [], 'neighborhood': {'name': [], 'type': []}, 'building': {'name': [], 'type': []}, 'adcode': '610802', 'street': '榆阳区国道', 'number': [], 'location': '109.718650,38.286666', 'level': '道路'}]}