#!/usr/bin/env bash
# HTTP API cURL 调用示例
# 服务启动方式: chainlit run web_app.py --host 0.0.0.0 --port 8000

BASE_URL="http://localhost:8000"

# ── 1. 健康检查 ───────────────────────────────────────────
echo "=== 健康检查 ==="
curl -s "${BASE_URL}/api/v1/health" | python3 -m json.tool

# ── 2. 创建任务（最简） ──────────────────────────────────
echo -e "\n=== 创建任务 ==="
TASK_RESPONSE=$(curl -s -X POST "${BASE_URL}/api/v1/tasks" \
  -H "Content-Type: application/json" \
  -d '{"incident_description":"G72高速K85处三车追尾，2人受伤"}')
echo "${TASK_RESPONSE}" | python3 -m json.tool

# 提取 task_id
TASK_ID=$(echo "${TASK_RESPONSE}" | python3 -c "import sys,json; print(json.load(sys.stdin)['task_id'])")
echo "task_id: ${TASK_ID}"

# ── 3. 查询任务状态 ──────────────────────────────────────
echo -e "\n=== 查询任务状态 ==="
curl -s "${BASE_URL}/api/v1/tasks/${TASK_ID}" | python3 -m json.tool

# ── 4. 列出所有任务 ──────────────────────────────────────
echo -e "\n=== 列出所有任务 ==="
curl -s "${BASE_URL}/api/v1/tasks" | python3 -m json.tool

# ── 5. 按状态过滤 ────────────────────────────────────────
echo -e "\n=== 运行中的任务 ==="
curl -s "${BASE_URL}/api/v1/tasks?status=running" | python3 -m json.tool

# ── 6. 取消任务 ──────────────────────────────────────────
echo -e "\n=== 取消任务 ==="
curl -s -X DELETE "${BASE_URL}/api/v1/tasks/${TASK_ID}" | python3 -m json.tool

# ── 7. 创建任务（完整参数） ──────────────────────────────
echo -e "\n=== 创建任务（完整参数） ==="
curl -s -X POST "${BASE_URL}/api/v1/tasks" \
  -H "Content-Type: application/json" \
  -d '{
    "incident_description": "S31高速K120处危化品罐车泄漏，双向交通中断，3人被困",
    "incident_info": {
      "incident_type": "危化品泄漏",
      "severity": "critical",
      "location_text": "S31高速K120",
      "casualty_status": "3人被困",
      "scene_status": "双向阻断",
      "hazmat_involved": true,
      "hazmat_type": "液化天然气"
    }
  }' | python3 -m json.tool
