"""健康检查示例。

GET /api/v1/health
"""

import requests

BASE_URL = "http://localhost:8000"

resp = requests.get(f"{BASE_URL}/api/v1/health")
print(resp.status_code)
print(resp.json())
# 预期输出:
# 200
# {"status": "healthy", "timestamp": "...", "python_version": "...", "tasks_total": 0, "tasks_running": 0}
