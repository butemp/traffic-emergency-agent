"""轮询任务状态直到完成示例。

GET /api/v1/tasks/{task_id}
"""

import time
import requests

BASE_URL = "http://localhost:8000"


def create_task() -> str:
    resp = requests.post(
        f"{BASE_URL}/api/v1/tasks",
        json={"incident_description": "G72高速K85处三车追尾，2人受伤"},
    )
    resp.raise_for_status()
    return resp.json()["task_id"]


def poll_until_done(task_id: str, interval: float = 3.0, timeout: float = 600.0):
    """轮询任务状态，直到 completed / failed / cancelled。"""
    start = time.time()
    while time.time() - start < timeout:
        resp = requests.get(f"{BASE_URL}/api/v1/tasks/{task_id}")
        resp.raise_for_status()
        data = resp.json()

        status = data["status"]
        progress = data.get("progress", {})
        print(
            f"[{status}] phase={progress.get('phase', '')} "
            f"iter={progress.get('iteration', 0)} "
            f"action={progress.get('current_action', '')}"
        )

        if status == "completed":
            result = data.get("result", {})
            print("\n=== 最终方案（前 500 字） ===")
            print(result.get("plan_markdown", "")[:500])
            print("\n=== 章节列表 ===")
            for title in result.get("sections", {}):
                print(f"  - {title}")
            return data

        if status in ("failed", "cancelled"):
            error = data.get("error", {})
            print(f"\n任务终止: code={error.get('code')} message={error.get('message')}")
            return data

        time.sleep(interval)

    print("轮询超时")
    return None


if __name__ == "__main__":
    task_id = create_task()
    print(f"任务已创建: {task_id}\n")
    poll_until_done(task_id)
