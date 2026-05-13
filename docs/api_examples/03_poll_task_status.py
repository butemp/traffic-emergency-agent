"""创建任务并轮询直到完成。"""

import time
import requests

BASE = "http://localhost:8000/api/v1"

# 创建任务
task_id = requests.post(f"{BASE}/tasks", json={
    "incident_description": "G72高速K85处三车追尾，2人受伤",
}).json()["task_id"]
print(f"任务已创建: {task_id}\n")

# 轮询（建议 3-5 秒间隔）
while True:
    data = requests.get(f"{BASE}/tasks/{task_id}").json()
    status = data["status"]
    progress = data.get("progress", {})
    pipeline = progress.get('pipeline_status', '')
    action = progress.get('current_action', '')
    print(f"[{status}] {action}" + (f" | {pipeline}" if pipeline else ""))

    if status == "completed":
        result = data["result"]
        print(f"\n方案前 500 字:\n{result['plan_markdown'][:500]}")
        print(f"\n章节: {list(result['sections'].keys())}")
        break

    if status in ("failed", "cancelled"):
        print(f"\n任务终止: {data.get('error', {})}")
        break

    time.sleep(5)
