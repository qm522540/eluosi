#!/bin/bash
# 快速部署脚本 - 从GitHub拉取最新代码，构建前端，重启后端
set -e

PROJECT_DIR="/data/ecommerce-ai"
cd $PROJECT_DIR

echo "=========================================="
echo "  开始部署..."
echo "=========================================="

echo ""
echo ">> [1/5] 拉取最新代码..."
git pull origin main

echo ""
echo ">> [2/5] 安装/更新后端依赖..."
source venv/bin/activate
pip install -r requirements.txt -q

echo ""
echo ">> [3/5] 安装前端依赖..."
cd $PROJECT_DIR/frontend
npm install --legacy-peer-deps 2>&1 | tail -1

echo ""
echo ">> [4/5] 构建前端..."
npm run build

echo ""
echo ">> [5/5] 重启后端服务..."
cd $PROJECT_DIR
sudo supervisorctl restart ecommerce:*

echo ""
echo "=========================================="
echo "  部署完成！"
echo "=========================================="
supervisorctl status ecommerce:*
echo ""
echo "前端已构建到: $PROJECT_DIR/frontend/dist"
