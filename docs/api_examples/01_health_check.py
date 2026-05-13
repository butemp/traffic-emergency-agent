"""健康检查: GET /api/v1/health"""

import requests

resp = requests.get("http://localhost:8000/api/v1/health")
print(resp.json())
