"""创建任务: POST /api/v1/tasks

不传 config 时使用服务端默认模型（deepseek-ai/DeepSeek-V3.2）。
"""

import requests

BASE = "http://localhost:8000/api/v1"

# 最简请求：只需一句灾情描述
resp = requests.post(f"{BASE}/tasks", json={
    "incident_description": "G72高速K85处三车追尾，2人受伤",
})
print(resp.json())  # {"task_id": "...", "status": "pending", "created_at": "..."}
