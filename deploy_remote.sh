#!/bin/bash
# ==============================================================
# 俄罗斯电商AI系统 - 远程部署脚本
# 从本地通过SSH执行，部署到生产服务器
#
# 用法：bash deploy_remote.sh [选项]
#   无参数        完整部署（拉代码+后端重启+前端构建+健康检查）
#   --backend     仅后端（拉代码+pip+重启supervisor）
#   --frontend    仅前端（拉代码+npm build）
#   --migrate FILE  执行数据库迁移（传migrations/versions/下的文件名）
#                   示例: bash deploy_remote.sh --migrate 016_ai_pricing.sql
#   --status      查看服务状态
#   --logs        查看最近50行应用日志
#   --db SQL      执行任意SQL语句
#                   示例: bash deploy_remote.sh --db "SELECT COUNT(*) FROM shops"
# ==============================================================

set -e

# ==================== 服务器配置 ====================
SERVER="47.84.130.136"
PORT=443
USER="root"
DIR="/data/ecommerce-ai"
DB_USER="ecom_app"
DB_PASS="EcomApp@2026DB"
DB_NAME="ecommerce_ai"

SSH="ssh -o ConnectTimeout=15 -o StrictHostKeyChecking=no -p ${PORT} ${USER}@${SERVER}"

# ==================== 工具函数 ====================
step() { echo ""; echo "==== $1 ===="; }

run() { ${SSH} "$1"; }

check() {
    step "检查SSH连接"
    if run "echo ok" > /dev/null 2>&1; then
        echo "连接正常 (${SERVER}:${PORT})"
    else
        echo "SSH连接失败！检查网络或服务器"
        exit 1
    fi
}

# ==================== 部署动作 ====================
pull()      { step "拉取代码";       run "cd ${DIR} && git pull origin main"; }
pipi()      { step "Python依赖";     run "cd ${DIR} && source venv/bin/activate && pip install -r requirements.txt -q 2>&1 | tail -3"; }
pycompile() {
    step "Python 语法预检"
    run "cd ${DIR} && source venv/bin/activate && python -m compileall -q app/ 2>&1" || {
        echo "ERROR: Python 语法错误，中止部署。"
        exit 1
    }
    echo "语法预检通过"
}
restart()   { step "重启后端";       run "sudo supervisorctl restart all"; sleep 2; run "sudo supervisorctl status"; }
build()     { step "构建前端";       run "cd ${DIR}/frontend && rm -rf node_modules/.vite dist && npm run build"; }
health()    {
    step "健康检查（最多等 30 秒）"
    local attempt=0
    local max=15  # 15 * 2s = 30s
    local r=""
    while [ $attempt -lt $max ]; do
        r=$(run "curl -s -o /dev/null -w '%{http_code}|' http://localhost:8000/api/v1/system/health && curl -s http://localhost:8000/api/v1/system/health" 2>&1)
        if echo "$r" | grep -q '"code":0'; then
            echo "API 正常（第 $((attempt+1)) 次检测）: $r"
            return 0
        fi
        attempt=$((attempt+1))
        sleep 2
    done
    echo ""
    echo "ERROR: 30 秒内 API 未就绪，最后返回: $r"
    echo "==== 最近 60 行后端错误日志 ===="
    run "tail -60 /data/logs/fastapi_err.log 2>&1" || true
    exit 1
}
migrate()   {
    [ -z "$1" ] && echo "请指定SQL文件名: --migrate 016_ai_pricing.sql" && exit 1
    step "数据库迁移: $1"
    pull
    run "cd ${DIR} && mysql -u ${DB_USER} -p'${DB_PASS}' ${DB_NAME} < database/migrations/versions/$1"
    echo "迁移完成"
}
status()    { step "服务状态"; run "sudo supervisorctl status"; }
logs()      { step "应用日志(最近50行)"; run "tail -50 ${DIR}/logs/app.log 2>/dev/null || journalctl -u ecommerce -n 50 --no-pager 2>/dev/null || echo '未找到日志'"; }
dbexec()    { run "mysql -u ${DB_USER} -p'${DB_PASS}' ${DB_NAME} -e \"$1\""; }

# ==================== 主入口 ====================
case "${1:-full}" in
    full|"")    check; pull; pipi; pycompile; restart; build; health; step "部署完成" ;;
    --backend)  check; pull; pipi; pycompile; restart; health ;;
    --frontend) check; pull; build ;;
    --migrate)  check; migrate "$2" ;;
    --status)   check; status ;;
    --logs)     check; logs ;;
    --db)       check; dbexec "$2" ;;
    *) echo "未知选项: $1"; echo "用法: bash deploy_remote.sh [full|--backend|--frontend|--migrate <file>|--status|--logs|--db <sql>]"; exit 1 ;;
esac
