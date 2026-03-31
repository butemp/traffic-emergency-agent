#!/bin/bash
# 启动Web界面

HOST=${CHAINLIT_HOST:-0.0.0.0}
PORT=${CHAINLIT_PORT:-8000}

chainlit run web_app.py --host $HOST --port $PORT
