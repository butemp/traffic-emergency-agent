#!/usr/bin/env bash
# 服务启动: chainlit run web_app.py --host 0.0.0.0 --port 8000
BASE="http://localhost:8000/api/v1"

# 健康检查
curl -s "$BASE/health" | python3 -m json.tool

# 创建任务
RESP=$(curl -s -X POST "$BASE/tasks" \
  -H "Content-Type: application/json" \
  -d '{"incident_description":"G72高速K85处三车追尾，2人受伤"}')
echo "$RESP" | python3 -m json.tool
TASK_ID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['task_id'])")

# 查询状态
curl -s "$BASE/tasks/$TASK_ID" | python3 -m json.tool

# 列出任务
curl -s "$BASE/tasks" | python3 -m json.tool

# 取消任务
curl -s -X DELETE "$BASE/tasks/$TASK_ID" | python3 -m json.tool
