"""创建方案生成任务示例。

POST /api/v1/tasks
"""

import requests

BASE_URL = "http://localhost:8000"

# ── 最简请求：只传事件描述 ────────────────────────────────

resp = requests.post(
    f"{BASE_URL}/api/v1/tasks",
    json={
        "incident_description": "G72高速K85处三车追尾，2人受伤",
    },
)
print("状态码:", resp.status_code)  # 201
data = resp.json()
print("task_id:", data["task_id"])
print("status:", data["status"])      # pending
print("created_at:", data["created_at"])


# ── 完整请求：附带预填充灾情信息和模型配置 ────────────────

resp2 = requests.post(
    f"{BASE_URL}/api/v1/tasks",
    json={
        "incident_description": "S31高速K120处危化品罐车泄漏，双向交通中断，3人被困",
        "incident_info": {
            "incident_type": "危化品泄漏",
            "severity": "critical",
            "location_text": "S31高速K120",
            "casualty_status": "3人被困",
            "scene_status": "双向阻断",
            "hazmat_involved": True,
            "hazmat_type": "液化天然气",
        },
        "media_urls": [
            "https://example.com/scene1.jpg",
        ],
        "config": {
            "OPENAI_API_KEY": "sk-xxx",
            "OPENAI_MODEL": "deepseek-ai/DeepSeek-V3.2",
            "OPENAI_BASE_URL": "https://ai.gxtri.cn/llm/v1",
            "OPENAI_MAX_TOKENS": "65536",
        },
    },
)
print("\n完整请求:")
print("task_id:", resp2.json()["task_id"])
