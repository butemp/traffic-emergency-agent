"""创建方案生成任务示例。

POST /api/v1/tasks

注意：不传 config 时，服务端会依次检查：
  1. 环境变量 OPENAI_MODEL / OPENAI_BASE_URL / OPENAI_API_KEY
  2. defaults.py 中的硬编码默认值（deepseek-ai/DeepSeek-V3.2）
如果部署环境设了这些环境变量，实际使用的模型可能不是 deepseek。
要确保使用 deepseek，请显式传 config。
"""

import requests

BASE_URL = "http://localhost:8000"

# ── 最简请求：只传事件描述 ────────────────────────────────
# 使用服务端默认模型配置（取决于环境变量和 defaults.py）

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


# ── 指定使用 deepseek 模型 ────────────────────────────────
# 显式传 config 可以覆盖环境变量，确保使用指定的模型

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
        "config": {
            "OPENAI_API_KEY": "sk-TBi6zDfq2SkTvyZQCusU7g",
            "OPENAI_MODEL": "deepseek-ai/DeepSeek-V3.2",
            "OPENAI_BASE_URL": "https://ai.gxtri.cn/llm/v1",
            "OPENAI_MAX_TOKENS": "65536",
        },
    },
)
print("\n指定模型请求:")
print("task_id:", resp2.json()["task_id"])
