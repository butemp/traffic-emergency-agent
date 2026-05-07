"""列出任务 & 取消任务示例。

GET    /api/v1/tasks          列出任务
DELETE /api/v1/tasks/{task_id} 取消任务
"""

import requests

BASE_URL = "http://localhost:8000"

# ── 列出所有任务 ──────────────────────────────────────────

resp = requests.get(f"{BASE_URL}/api/v1/tasks")
data = resp.json()
print(f"共 {data['total']} 个任务:")
for t in data["tasks"]:
    print(f"  {t['task_id']}  {t['status']}  {t['incident_description'][:40]}")


# ── 按状态过滤 ────────────────────────────────────────────

resp = requests.get(f"{BASE_URL}/api/v1/tasks", params={"status": "running"})
running = resp.json()
print(f"\n运行中的任务: {running['total']}")


# ── 分页查询 ──────────────────────────────────────────────

resp = requests.get(f"{BASE_URL}/api/v1/tasks", params={"limit": 5, "offset": 0})
page = resp.json()
print(f"\n第 1 页（最多 5 条）: {len(page['tasks'])} 条")


# ── 取消任务 ──────────────────────────────────────────────

task_id = "替换为实际的task_id"
resp = requests.delete(f"{BASE_URL}/api/v1/tasks/{task_id}")
if resp.status_code == 200:
    print(f"\n任务已取消: {resp.json()}")
elif resp.status_code == 404:
    print(f"\n任务不存在: {task_id}")
