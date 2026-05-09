"""健康检查示例。

GET /api/v1/health
"""

import requests

BASE_URL = "http://localhost:8000"

resp = requests.get(f"{BASE_URL}/api/v1/health")
print("状态码:", resp.status_code)
if resp.status_code == 200:
    print(resp.json())
else:
    print("响应内容:", resp.text[:200])
# 预期输出:
# 状态码: 200
# {"status": "healthy", "timestamp": "...", "python_version": "...", "tasks_total": 0, "tasks_running": 0}
