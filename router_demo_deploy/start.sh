#!/bin/bash
cd "$(dirname "$0")"

echo "=========================================="
echo "  OpenClaw Router Demo - 启动脚本"
echo "=========================================="
echo ""

PORT=${PORT:-8080}

if [ -d "venv" ]; then
    echo "检测到虚拟环境，正在激活..."
    source venv/bin/activate
else
    echo "未检测到虚拟环境，正在创建..."
    python3 -m venv venv
    source venv/bin/activate
    echo "正在安装依赖..."
    pip install -r requirements.txt
fi

echo ""
echo "正在启动服务 (端口: $PORT)..."
echo "访问地址: http://localhost:$PORT"
echo "按 Ctrl+C 停止服务"
echo ""

python app.py