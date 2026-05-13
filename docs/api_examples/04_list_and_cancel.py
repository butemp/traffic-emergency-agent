"""列出任务 & 取消任务。"""

import requests

BASE = "http://localhost:8000/api/v1"

# 列出所有任务
data = requests.get(f"{BASE}/tasks").json()
for t in data["tasks"]:
    print(f"  {t['task_id']}  {t['status']}  {t['incident_description'][:40]}")

# 取消任务
task_id = "替换为实际的task_id"
resp = requests.delete(f"{BASE}/tasks/{task_id}")
print(resp.json())
