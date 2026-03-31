"""
地图可视化工具

使用高德地图 JS API 在聊天界面生成动态路径规划地图。
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

def generate_rescue_map_html(
    start_lat: float, 
    start_lon: float, 
    end_lat: float, 
    end_lon: float, 
    start_name: str = "事故点",
    end_name: str = "救援力量",
    map_container_id: str = "container"
) -> str:
    """
    生成高德地图路径规划的 HTML 代码
    
    Args:
        start_lat: 起点纬度
        start_lon: 起点经度
        end_lat: 终点纬度
        end_lon: 终点经度
        start_name: 起点名称
        end_name: 终点名称
        map_container_id: 地图容器ID (需唯一)
        
    Returns:
        HTML 字符串
    """
    
    # ⚠️ 注意: JS API 需要专门的 Key (不同于 Web 服务 Key)
    # 这里为了演示，我们假设用户已经有了一个 JS API Key
    # 如果没有，可以使用 demo key 或者提示用户去申请
    # 通常 JS API Key 需要在前端加载，为了简单起见，这里注入一个通用的加载逻辑
    
    # 默认使用环境变量中的 Key，如果没有则回退到一个默认值 (注意：实际生产需替换为你的 JS Key)
    js_api_key = os.getenv("GAODE_JS_API_KEY", "b78a07dde4df95ad9b9cb75a97cdf10c") 
    security_code = os.getenv("GAODE_JS_SECURITY_CODE", "") # JS API 现在需要安全密钥

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta http-equiv="X-UA-Compatible" content="IE=edge">
        <meta name="viewport" content="initial-scale=1.0, user-scalable=no, width=device-width">
        <style>
        html, body, #{map_container_id} {{
            width: 100%;
            height: 400px;
            margin: 0;
            padding: 0;
            border-radius: 8px;
        }}
        #panel {{
            position: fixed;
            background-color: white;
            max-height: 90%;
            overflow-y: auto;
            top: 10px;
            right: 10px;
            width: 280px;
        }}
        </style>
        <script type="text/javascript">
            window._AMapSecurityConfig = {{
                securityJsCode: '{security_code}',
            }};
        </script>
        <script type="text/javascript" src="https://webapi.amap.com/maps?v=2.0&key={js_api_key}&plugin=AMap.Driving"></script>
    </head>
    <body>
        <div id="{map_container_id}"></div>
        <script type="text/javascript">
            // 确保地图容器存在后再初始化
            function initMap() {{
                try {{
                    if (!AMap) return;
                    
                    var map = new AMap.Map("{map_container_id}", {{
                        resizeEnable: true,
                        center: [{start_lon}, {start_lat}],
                        zoom: 13
                    }});

                    // 构造路线规划类
                    var driving = new AMap.Driving({{
                        map: map,
                        // panel: "panel" // 结果列表将在此容器中进行展示
                    }}); 

                    // 根据起终点经纬度规划驾车导航路线
                    driving.search(
                        new AMap.LngLat({start_lon}, {start_lat}), 
                        new AMap.LngLat({end_lon}, {end_lat}), 
                        function(status, result) {{
                            if (status === 'complete') {{
                                console.log('绘制驾车路线完成')
                            }} else {{
                                console.log('获取驾车数据失败：' + result)
                            }}
                        }}
                    );
                    
                    // 添加简单的 Marker
                    var startMarker = new AMap.Marker({{
                        position: new AMap.LngLat({start_lon}, {start_lat}),
                        title: "{start_name}",
                        label: {{ content: "{start_name}", offset: new AMap.Pixel(0, -20) }}
                    }});
                    
                    var endMarker = new AMap.Marker({{
                        position: new AMap.LngLat({end_lon}, {end_lat}),
                        title: "{end_name}",
                        label: {{ content: "{end_name}", offset: new AMap.Pixel(0, -20) }}
                    }});
                    
                    map.add([startMarker, endMarker]);
                    
                }} catch(e) {{
                    console.error("地图加载失败", e);
                    document.getElementById("{map_container_id}").innerHTML = 
                        "<div style='padding:20px;text-align:center;color:#666'>地图组件加载失败，请检查网络或Key配置。<br>起点: {start_name}<br>终点: {end_name}</div>";
                }}
            }}
            
            // 延迟一点初始化，确保 DOM 也就绪
            setTimeout(initMap, 500);
        </script>
    </body>
    </html>
    """
    return html_content
