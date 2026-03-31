# 高德地图API工具Schema定义
# 用于API接口规范、参数验证和文档生成

GAODE_API_SCHEMAS = {
    "check_traffic_status": {
        "name": "check_traffic_status",
        "description": "查询指定坐标点周边的交通拥堵情况，实时获取道路通行状态。适用于路线规划、出行建议、交通状况分析等场景。返回整体路况评估（畅通/缓行/拥堵）和具体道路详情，包括道路名称、当前状态、平均速度等关键信息。可用于智能导航、城市交通监控、出行时间预估等应用。",
        "parameters": {
            "type": "object",
            "properties": {
                "longitude": {
                    "type": "number",
                    "description": "经度坐标，表示地理位置的东西方向。中国地区经度范围约73-135度，北京约116度，上海约121度。请确保经纬度配对正确。",
                    "minimum": -180,
                    "maximum": 180
                },
                "latitude": {
                    "type": "number",
                    "description": "纬度坐标，表示地理位置的南北方向。中国地区纬度范围约18-53度，北京约40度，上海约31度。请与经度配合使用。",
                    "minimum": -90,
                    "maximum": 90
                },
                "radius": {
                    "type": "integer",
                    "description": "交通状况搜索半径，单位米。半径越大，覆盖道路越多，但可能影响数据准确性。建议：城市内用1000-2000米，跨区域查询用3000-5000米。最大支持5000米（5公里）。",
                    "default": 1500,
                    "minimum": 1,
                    "maximum": 5000
                },
                "level": {
                    "type": "integer",
                    "description": "道路等级筛选，控制返回道路的类型。0=所有道路，1=高速，2=城市快速路，3=主干道，4=次干道，5=县乡村道。默认5关注主要通行道路，适合大多数交通查询需求。设置为0可获得最全面的道路信息，但可能包含很多小路。",
                    "default": 5,
                    "enum": [0, 1, 2, 3, 4, 5]
                }
            },
            "required": ["longitude", "latitude"]
        },
        "returns": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "整体路况状态：1=畅通，2=缓行，3=拥堵，0=未知。状态码帮助快速判断当前区域通行状况。"
                },
                "description": {
                    "type": "string",
                    "description": "路况详细文字描述，包含主要拥堵路段、缓行区域等具体信息，帮助用户了解交通状况详情。"
                },
                "roads": {
                    "type": "array",
                    "description": "具体道路信息列表，每条道路包含名称、状态描述、平均速度等详细信息。最多返回附近的主要道路，便于分析具体哪条路拥堵。"
                }
            }
        }
    },

    "get_weather_by_location": {
        "name": "get_weather_by_location",
        "description": "通过经纬度查询指定地点的实时天气信息，提供准确的气象数据服务。支持获取当前天气状况和未来天气预报，适用于出行规划、户外活动安排、农业决策等场景。返回温度、天气现象、风力风向、湿度等关键气象要素，帮助用户做出基于天气的合理决策。API会自动识别坐标所属的行政区划，确保天气数据的准确性。",
        "parameters": {
            "type": "object",
            "properties": {
                "longitude": {
                    "type": "number",
                    "description": "经度坐标，精确定位到东西方向位置。系统会根据经纬度自动匹配最近的气象观测站点。中国范围内建议提供精确到小数点后6位的坐标以获得最佳结果。",
                    "minimum": -180,
                    "maximum": 180
                },
                "latitude": {
                    "type": "number",
                    "description": "纬度坐标，精确定位到南北方向位置。与经度配合使用，确保定位准确。不同纬度的天气差异较大，请尽量提供精确坐标。",
                    "minimum": -90,
                    "maximum": 90
                },
                "extensions": {
                    "type": "string",
                    "description": "天气信息类型选择。'base'返回实况天气（当前时刻的真实天气数据），'all'返回天气预报（未来几天的预测天气）。实况天气适用于了解当前状况，预报天气适用于未来规划。默认为实况天气。",
                    "default": "base",
                    "enum": ["base", "all"]
                }
            },
            "required": ["longitude", "latitude"]
        },
        "returns": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "object",
                    "description": "天气数据所属的地理位置信息，包含行政区划名称和编码，帮助用户确认天气数据的具体对应区域。"
                },
                "weather": {
                    "type": "object",
                    "description": "详细的天气信息数据集，包含温度、天气现象、风力等级、空气湿度等多项气象要素。数据来源于气象部门官方观测，具有较高权威性和准确性。"
                }
            }
        }
    },

    "geocode_address": {
        "name": "geocode_address",
        "description": "将自然语言描述的地理地址转换为精确的经纬度坐标，实现地址数字化。支持从简单地址到复杂详细地址的解析，适用于地图标注、位置定位、距离计算、导航起点终点设置等场景。该工具采用智能地址匹配算法，能够识别标准地址、路名+门牌号、地标建筑等多种地址格式。返回结果包含坐标信息、行政区划、地址级别等丰富数据，为后续地理信息系统应用提供基础数据支持。",
        "parameters": {
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": "待转换的地址字符串，支持多种格式：1）标准地址'北京市朝阳区建国路88号'；2）道路地址'南京市中山路'；3）地标建筑'天安门广场'；4）交叉口'建设路与解放路交叉口'。地址越详细，定位越准确。建议包含省市区信息以提高匹配精度。",
                    "minLength": 1
                },
                "city": {
                    "type": "string",
                    "description": "指定查询城市，可显著提高地址解析的准确性和速度。当输入的地址不包含城市信息时，此参数特别有用。例如输入'万达广场'时，指定城市为'北京市'可以避免匹配到其他城市的万达广场。支持城市全称或简称，如'北京'、'上海市'、'广州'等。",
                }
            },
            "required": ["address"]
        },
        "returns": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "查询状态标识：'1'表示成功，其他值表示失败。失败时可能伴随错误信息，帮助用户了解失败原因。"
                },
                "count": {
                    "type": "string",
                    "description": "返回结果数量，表示找到多少个匹配地址。通常返回1-3个最相关的结果，当输入地址不够具体时可能返回多个候选项。"
                },
                "geocodes": {
                    "type": "array",
                    "description": "地理编码结果数组，每个元素包含完整的地址解析信息。按照相关性排序，第一个结果通常是最准确的匹配。"
                }
            }
        }
    },

    "search_nearby_pois": {
        "name": "search_nearby_pois",
        "description": "基于指定位置坐标搜索周边的兴趣点（POI），提供全面的周边设施信息检索服务。支持查找各类生活服务设施，包括餐饮美食、购物商场、医疗服务、交通设施、旅游景点等。适用于生活服务推荐、商业选址分析、旅游规划、应急设施查找等多种场景。支持自定义搜索范围、结果排序、分页获取等高级功能，确保用户能够快速找到目标地点。返回数据包含名称、类型、距离、详细地址、坐标等完整信息，便于后续导航和联系。",
        "parameters": {
            "type": "object",
            "properties": {
                "longitude": {
                    "type": "number",
                    "description": "中心点的经度坐标，作为周边搜索的基准位置。建议提供精确坐标以获得准确的距离计算结果。搜索范围是以此坐标为中心的圆形区域。",
                    "minimum": -180,
                    "maximum": 180
                },
                "latitude": {
                    "type": "number",
                    "description": "中心点的纬度坐标，与经度配合确定搜索中心点。坐标精度直接影响搜索结果的准确性，特别是距离计算。"
                },
                "keywords": {
                    "type": "string",
                    "description": "搜索关键词，支持多种输入方式：1）具体类型'医院'、'超市'、'餐厅'；2）品牌名称'肯德基'、'星巴克'；3）服务类型'ATM'、'加油站'；4）设施名称'地铁站'、'停车场'。关键词越具体，搜索结果越精准。支持模糊匹配，如'美食'可匹配餐厅、小吃店等。",
                    "minLength": 1
                },
                "radius": {
                    "type": "integer",
                    "description": "搜索半径，单位米。定义搜索范围的大小，应根据实际需求调整：步行推荐500-1000米，驾车推荐1000-3000米，跨区域搜索可设置更大半径。注意：半径越大，返回结果越多但可能相关性降低。最大支持50000米（50公里）。",
                    "default": 1000,
                    "minimum": 1,
                    "maximum": 50000
                },
                "sortrule": {
                    "type": "string",
                    "description": "结果排序方式：'distance'按距离从近到远排序，适合查找最近的设施；'weight'按综合权重排序，考虑知名度、人气等因素，适合查找热门推荐。默认按距离排序。",
                    "default": "distance",
                    "enum": ["distance", "weight"]
                },
                "max_pages": {
                    "type": "integer",
                    "description": "最大获取页数，控制返回结果数量。每页包含20条POI信息，设置max_pages=5可获取最多100条结果。当需要更多结果时可以增大此值，但建议不要超过10页以避免数据冗余。适用于需要全面了解周边设施分布的场景。",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 10
                }
            },
            "required": ["longitude", "latitude", "keywords"]
        },
        "returns": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "实际返回的POI结果总数，帮助用户了解搜索结果的丰富程度。当结果较少时，可能需要扩大搜索半径或更换搜索关键词。"
                },
                "pois": {
                    "type": "array",
                    "description": "POI详细信息列表，按照指定的排序规则排列。每个POI包含完整的识别和定位信息，可直接用于导航、联系、评价等后续操作。"
                }
            }
        }
    },

    "reverse_geocode": {
        "name": "reverse_geocode",
        "description": "将经纬度坐标转换为人类可读的详细地址描述，实现逆地理编码功能。适用于GPS定位后的地址显示、地图坐标标注解释、位置分享等场景。该工具能够将数字坐标转换为包含行政区划、街道信息、地标建筑等要素的自然语言地址，帮助用户理解和确认位置信息。支持基础地址信息和详细地址信息两种返回模式，可根据需求选择合适的数据粒度。返回地址遵循中国地址规范标准，可直接用于邮寄、导航输入等用途。",
        "parameters": {
            "type": "object",
            "properties": {
                "longitude": {
                    "type": "number",
                    "description": "经度坐标，表示位置的东西方向。注意：在高德地图API中，经度参数需放在纬度之前。请确保坐标使用正确的坐标系（GCJ02坐标系），否则可能影响地址解析精度。"
                },
                "latitude": {
                    "type": "number",
                    "description": "纬度坐标，表示位置的南北方向。与经度配合使用，精确定位到具体位置。坐标精度会影响地址解析的准确性，建议提供至少6位小数的精确坐标。"
                },
                "radius": {
                    "type": "integer",
                    "description": "逆地理编码搜索半径，单位米。当坐标附近没有明显地址特征时，系统会在指定半径范围内查找最近的地址信息。城市内建议设置1000米以内，偏远地区可适当扩大至3000-5000米。"
                },
                "extensions": {
                    "type": "string",
                    "description": "返回信息详细程度：'base'返回基础地址信息（包含完整地址和基本行政区划），适合简单显示需求；'all'返回详细信息（包含街道门牌、周边POI、兴趣点等），适合需要丰富位置信息的场景。默认返回基础信息。",
                    "default": "base",
                    "enum": ["base", "all"]
                }
            },
            "required": ["longitude", "latitude"]
        },
        "returns": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "查询状态码：'1'表示成功解析，其他值表示查询失败。失败原因可能包括坐标无效、位置在海中或其他无法解析的区域。"
                },
                "formatted_address": {
                    "type": "string",
                    "description": "完整格式的地址字符串，按照中国地址书写规范生成，从大到小依次包含：国家+省份+城市+区县+街道+门牌号等。这是最直观的地址表达方式，适合直接展示给用户。"
                },
                "addressComponent": {
                    "type": "object",
                    "description": "地址的组成结构要素，将完整地址拆分为独立的行政区划和地理要素，便于程序化处理和精确匹配。包含国家、省、市、区、街道等各级行政区划信息。"
                }
            }
        }
    }
}


def get_schema(api_name):
    """获取指定API的schema定义"""
    return GAODE_API_SCHEMAS.get(api_name)


def list_all_schemas():
    """列出所有可用的schema名称"""
    return list(GAODE_API_SCHEMAS.keys())


if __name__ == "__main__":
    # 示例：获取特定API的schema
    schema = get_schema("check_traffic_status")
    print(f"API名称: {schema['name']}")
    print(f"API描述: {schema['description']}")
    
    # 列出所有可用的schema
    print(f"\n可用的API Schema:")
    for name in list_all_schemas():
        print(f"- {name}")