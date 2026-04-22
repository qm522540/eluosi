#!/bin/bash
# ============================================================
# 俄罗斯电商AI系统 — 阿里云ECS一键环境部署脚本
# 服务器: Ubuntu 22.04 LTS
# 作者: 老林（架构师）
# 日期: 2026-04-07
# 用法: 在服务器上以root执行
#   bash setup_server.sh
# ============================================================

set -e  # 任何命令失败立即退出

echo "=========================================="
echo "  俄罗斯电商AI系统 - 服务器环境部署"
echo "=========================================="

# ---- 0. 基础变量 ----
DATA_DIR="/data"
PROJECT_DIR="/data/ecommerce-ai"
MYSQL_ROOT_PASS="Ecom@2026Secure"
REDIS_PASS="Redis@2026Ecom"
DEPLOY_USER="deploy"

# ---- 1. 系统更新 + 基础工具 ----
echo ""
echo "[1/10] 系统更新 + 基础工具..."
apt-get update -y
apt-get upgrade -y
apt-get install -y \
    curl wget git vim htop unzip tree \
    software-properties-common \
    build-essential libssl-dev libffi-dev \
    pkg-config libmysqlclient-dev \
    supervisor nginx \
    ufw

# ---- 2. 创建部署用户 + 数据目录 ----
echo ""
echo "[2/10] 创建部署用户和目录结构..."
if ! id "$DEPLOY_USER" &>/dev/null; then
    useradd -m -s /bin/bash $DEPLOY_USER
    echo "$DEPLOY_USER:DeployPass2026!" | chpasswd
fi

mkdir -p $DATA_DIR/{mysql,redis,logs,backups}
mkdir -p $PROJECT_DIR
mkdir -p /home/$DEPLOY_USER/.ssh

# 设置SSH密钥（本地免密登录）
cat >> /home/$DEPLOY_USER/.ssh/authorized_keys << 'SSHKEY'
ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQCl3ANmqKV145fhM2Yt0rieacpzqKCvWbtpWBo10ev+NdL9NE8TJ3szzvgO/D80TrFKn89Q5P2q0KNst/p+WhC2Eg5qoshefyyzkbVTd+3QAcP0dLqfmRxs+dUiYsaVgTGseu/vWCpOdB002vNs+brz+4l//O+nxGGwn5X9hJlEzu9jXTwX/XjmujOYe7kHOP0+uylKOfP54P7aj7HdlOE50bkk4YTwy27eUSfoQ3i7z7m0az/NCPXB6nb7qYcMoVBJ2xJh35SiaCgz+EEm7wn2ACDKUMlAnD6o/HSTstOxCeH7ok3EtBrnorYgVHiCWuqJ1QqmNsF/CUGSNpxPtVwgn6CqsRbppkPrHa+OdG6k4fxdkL8mqAjwAyweZFacylFHHixJJmAkYCehplZ7/Kcp9yuH5gC0wveaSmkwu9hGh91WbXtwgLYt2lq2zH3A/3hZfJOzfLQ2MIr5DhIko7lJLc6gAnEWpdYZXKLhIkkLvAU5raulI77JU0Ws0XiEX3Y6o7GRMhAULGrmIlfmww+IMIFqhbNYAJP3L9U4Z0/XiByYubYFMwH6MdXzC1gcBQJyaZfF21A9UDUR+/BFN0/62amXXZis29v2TC0pPuPpwsDjUVakfe5+jCtXtby0tbIgPL/0EWgkdDQTzib/K10WIYP7gkkCZELqupmt5pVlSQ== wcq@eluosi-dev
SSHKEY

# 也设置root的SSH密钥
mkdir -p /root/.ssh
cat >> /root/.ssh/authorized_keys << 'SSHKEY'
ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQCl3ANmqKV145fhM2Yt0rieacpzqKCvWbtpWBo10ev+NdL9NE8TJ3szzvgO/D80TrFKn89Q5P2q0KNst/p+WhC2Eg5qoshefyyzkbVTd+3QAcP0dLqfmRxs+dUiYsaVgTGseu/vWCpOdB002vNs+brz+4l//O+nxGGwn5X9hJlEzu9jXTwX/XjmujOYe7kHOP0+uylKOfP54P7aj7HdlOE50bkk4YTwy27eUSfoQ3i7z7m0az/NCPXB6nb7qYcMoVBJ2xJh35SiaCgz+EEm7wn2ACDKUMlAnD6o/HSTstOxCeH7ok3EtBrnorYgVHiCWuqJ1QqmNsF/CUGSNpxPtVwgn6CqsRbppkPrHa+OdG6k4fxdkL8mqAjwAyweZFacylFHHixJJmAkYCehplZ7/Kcp9yuH5gC0wveaSmkwu9hGh91WbXtwgLYt2lq2zH3A/3hZfJOzfLQ2MIr5DhIko7lJLc6gAnEWpdYZXKLhIkkLvAU5raulI77JU0Ws0XiEX3Y6o7GRMhAULGrmIlfmww+IMIFqhbNYAJP3L9U4Z0/XiByYubYFMwH6MdXzC1gcBQJyaZfF21A9UDUR+/BFN0/62amXXZis29v2TC0pPuPpwsDjUVakfe5+jCtXtby0tbIgPL/0EWgkdDQTzib/K10WIYP7gkkCZELqupmt5pVlSQ== wcq@eluosi-dev
SSHKEY

chmod 700 /root/.ssh /home/$DEPLOY_USER/.ssh
chmod 600 /root/.ssh/authorized_keys /home/$DEPLOY_USER/.ssh/authorized_keys
chown -R $DEPLOY_USER:$DEPLOY_USER /home/$DEPLOY_USER/.ssh
chown -R $DEPLOY_USER:$DEPLOY_USER $PROJECT_DIR

# ---- 3. 安装 Python 3.11 ----
echo ""
echo "[3/10] 安装 Python 3.11..."
add-apt-repository -y ppa:deadsnakes/ppa
apt-get update -y
apt-get install -y python3.11 python3.11-venv python3.11-dev python3.11-distutils

# 设置python3.11为默认python3
update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
update-alternatives --set python3 /usr/bin/python3.11

# 安装pip
curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11
python3.11 -m pip install --upgrade pip

echo "Python版本: $(python3.11 --version)"

# ---- 4. 安装 MySQL 8.0 ----
echo ""
echo "[4/10] 安装 MySQL 8.0..."
apt-get install -y mysql-server

# 启动MySQL
systemctl start mysql
systemctl enable mysql

# 设置root密码和安全配置
mysql -u root <<MYSQL_INIT
ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY '${MYSQL_ROOT_PASS}';
DELETE FROM mysql.user WHERE User='';
DELETE FROM mysql.user WHERE User='root' AND Host NOT IN ('localhost', '127.0.0.1', '::1');
DROP DATABASE IF EXISTS test;
DELETE FROM mysql.db WHERE Db='test' OR Db='test\\_%';
FLUSH PRIVILEGES;

-- 创建项目数据库
CREATE DATABASE IF NOT EXISTS ecommerce_ai
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

-- 创建应用专用用户
CREATE USER IF NOT EXISTS 'ecom_app'@'localhost' IDENTIFIED BY 'EcomApp@2026DB';
GRANT ALL PRIVILEGES ON ecommerce_ai.* TO 'ecom_app'@'localhost';
FLUSH PRIVILEGES;
MYSQL_INIT

# MySQL配置优化
cat > /etc/mysql/mysql.conf.d/custom.cnf << 'MYSQLCNF'
[mysqld]
# 字符集
character-set-server = utf8mb4
collation-server = utf8mb4_unicode_ci

# 数据目录（如有独立数据盘可改为/data/mysql）
# datadir = /data/mysql

# InnoDB优化
innodb_buffer_pool_size = 1G
innodb_log_file_size = 256M
innodb_flush_log_at_trx_commit = 2
innodb_flush_method = O_DIRECT

# 连接数
max_connections = 200

# 慢查询日志
slow_query_log = 1
slow_query_log_file = /var/log/mysql/slow.log
long_query_time = 2

# 禁止外部访问
bind-address = 127.0.0.1
MYSQLCNF

systemctl restart mysql
echo "MySQL 安装完成，数据库 ecommerce_ai 已创建"

# ---- 5. 安装 Redis ----
echo ""
echo "[5/10] 安装 Redis..."
apt-get install -y redis-server

# Redis配置
sed -i "s/^# requirepass .*/requirepass ${REDIS_PASS}/" /etc/redis/redis.conf
sed -i "s/^bind .*/bind 127.0.0.1 ::1/" /etc/redis/redis.conf
sed -i "s/^# maxmemory .*/maxmemory 512mb/" /etc/redis/redis.conf
sed -i "s/^# maxmemory-policy .*/maxmemory-policy allkeys-lru/" /etc/redis/redis.conf

systemctl restart redis-server
systemctl enable redis-server
echo "Redis 安装完成"

# ---- 6. 安装 Node.js 18 LTS ----
echo ""
echo "[6/10] 安装 Node.js 18 LTS..."
curl -fsSL https://deb.nodesource.com/setup_18.x | bash -
apt-get install -y nodejs
echo "Node.js版本: $(node --version)"
echo "npm版本: $(npm --version)"

# ---- 7. 创建Python虚拟环境 + 安装依赖 ----
echo ""
echo "[7/10] 创建Python虚拟环境..."
python3.11 -m venv $PROJECT_DIR/venv
source $PROJECT_DIR/venv/bin/activate

pip install --upgrade pip
pip install \
    fastapi==0.110.0 \
    "uvicorn[standard]==0.27.0" \
    sqlalchemy==2.0.25 \
    pymysql==1.1.0 \
    alembic==1.13.1 \
    pydantic==2.5.3 \
    pydantic-settings==2.1.0 \
    redis==5.0.1 \
    celery==5.3.6 \
    httpx==0.26.0 \
    "python-jose[cryptography]==3.3.0" \
    "passlib[bcrypt]==1.7.4" \
    python-multipart==0.0.6 \
    python-dotenv==1.0.0 \
    openpyxl==3.1.2 \
    cryptography \
    mysqlclient

deactivate
chown -R $DEPLOY_USER:$DEPLOY_USER $PROJECT_DIR

echo "Python虚拟环境创建完成: $PROJECT_DIR/venv"

# ---- 8. 配置 Nginx ----
echo ""
echo "[8/10] 配置 Nginx..."
cat > /etc/nginx/sites-available/ecommerce-ai << 'NGINX'
server {
    listen 80;
    server_name _;

    # 前端静态文件
    location / {
        root /data/ecommerce-ai/frontend/dist;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    # 后端API代理
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_read_timeout 120s;
    }

    # WebSocket预留
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }

    # 静态资源缓存
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff2?)$ {
        root /data/ecommerce-ai/frontend/dist;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # 禁止访问隐藏文件
    location ~ /\. {
        deny all;
    }
}
NGINX

# 启用站点
ln -sf /etc/nginx/sites-available/ecommerce-ai /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

nginx -t && systemctl restart nginx
systemctl enable nginx
echo "Nginx 配置完成"

# ---- 9. 配置 Supervisor ----
echo ""
echo "[9/10] 配置 Supervisor..."

mkdir -p /data/logs

cat > /etc/supervisor/conf.d/ecommerce-ai.conf << 'SUPERVISOR'
; FastAPI主进程
[program:fastapi]
command=/data/ecommerce-ai/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
directory=/data/ecommerce-ai
user=deploy
autostart=true
autorestart=true
startsecs=5
stopwaitsecs=30
stopasgroup=true
killasgroup=true
stdout_logfile=/data/logs/fastapi.log
stderr_logfile=/data/logs/fastapi_err.log
stdout_logfile_maxbytes=50MB
stdout_logfile_backups=5
environment=PATH="/data/ecommerce-ai/venv/bin:%(ENV_PATH)s"

; Celery Worker
[program:celery-worker]
command=/data/ecommerce-ai/venv/bin/celery -A app.tasks.celery_app worker --loglevel=info --concurrency=2
directory=/data/ecommerce-ai
user=deploy
autostart=true
autorestart=true
startsecs=10
stopwaitsecs=60
stopasgroup=true
killasgroup=true
stdout_logfile=/data/logs/celery_worker.log
stderr_logfile=/data/logs/celery_worker_err.log
stdout_logfile_maxbytes=50MB
stdout_logfile_backups=5
environment=PATH="/data/ecommerce-ai/venv/bin:%(ENV_PATH)s"

; Celery Beat (定时调度)
[program:celery-beat]
command=/data/ecommerce-ai/venv/bin/celery -A app.tasks.celery_app beat --loglevel=info
directory=/data/ecommerce-ai
user=deploy
autostart=true
autorestart=true
startsecs=10
stopwaitsecs=10
stdout_logfile=/data/logs/celery_beat.log
stderr_logfile=/data/logs/celery_beat_err.log
stdout_logfile_maxbytes=50MB
stdout_logfile_backups=5
environment=PATH="/data/ecommerce-ai/venv/bin:%(ENV_PATH)s"

; 进程组
[group:ecommerce]
programs=fastapi,celery-worker,celery-beat
SUPERVISOR

supervisorctl reread
supervisorctl update
echo "Supervisor 配置完成（进程会在代码部署后启动）"

# ---- 10. 防火墙配置 ----
echo ""
echo "[10/10] 配置防火墙..."
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP
ufw allow 443/tcp   # HTTPS（后续域名用）
ufw --force enable

echo "防火墙已启用，开放端口: 22, 80, 443"

# ---- 创建部署脚本 ----
echo ""
echo "创建快速部署脚本..."

cat > /data/ecommerce-ai/deploy.sh << 'DEPLOY'
#!/bin/bash
# 快速部署脚本 - 从GitHub拉取最新代码并重启服务
set -e

PROJECT_DIR="/data/ecommerce-ai"
cd $PROJECT_DIR

echo ">> 拉取最新代码..."
git pull origin main

echo ">> 激活虚拟环境..."
source venv/bin/activate

echo ">> 安装/更新依赖..."
pip install -r requirements.txt -q

echo ">> 重启服务..."
sudo supervisorctl restart ecommerce:*

echo ">> 部署完成！"
supervisorctl status ecommerce:*
DEPLOY

chmod +x /data/ecommerce-ai/deploy.sh

# ---- 创建项目.env文件 ----
cat > /data/ecommerce-ai/.env << ENVFILE
# ===== 数据库 =====
DB_HOST=localhost
DB_PORT=3306
DB_NAME=ecommerce_ai
DB_USER=ecom_app
DB_PASSWORD=EcomApp@2026DB

# ===== Redis =====
REDIS_URL=redis://:${REDIS_PASS}@localhost:6379/0

# ===== JWT =====
JWT_SECRET_KEY=$(openssl rand -hex 32)
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=1440

# ===== AI模型API =====
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
KIMI_API_KEY=
KIMI_BASE_URL=https://api.moonshot.cn/v1
GLM_API_KEY=
GLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4

# ===== 企业微信 =====
WECHAT_WORK_CORP_ID=
WECHAT_WORK_AGENT_ID=
WECHAT_WORK_SECRET=
WECHAT_WORK_BOT_WEBHOOK=

# ===== 平台API限速 =====
WB_RATE_LIMIT_PER_MINUTE=60
OZON_RATE_LIMIT_PER_MINUTE=60
YANDEX_RATE_LIMIT_PER_MINUTE=60

# ===== 环境 =====
ENV=production
DEBUG=false
ENVFILE

chown $DEPLOY_USER:$DEPLOY_USER /data/ecommerce-ai/.env
chmod 600 /data/ecommerce-ai/.env

# ---- 最终输出 ----
echo ""
echo "=========================================="
echo "  部署完成！环境信息汇总"
echo "=========================================="
echo ""
echo "系统: $(lsb_release -ds)"
echo "Python: $(python3.11 --version)"
echo "MySQL: $(mysql --version | awk '{print $3}')"
echo "Redis: $(redis-server --version | awk '{print $3}')"
echo "Node.js: $(node --version)"
echo "Nginx: $(nginx -v 2>&1 | awk -F/ '{print $2}')"
echo ""
echo "-------- 目录结构 --------"
echo "项目目录: $PROJECT_DIR"
echo "虚拟环境: $PROJECT_DIR/venv"
echo "日志目录: /data/logs/"
echo "备份目录: /data/backups/"
echo ""
echo "-------- 数据库 --------"
echo "数据库名: ecommerce_ai"
echo "应用用户: ecom_app"
echo "MySQL root密码: ${MYSQL_ROOT_PASS}"
echo "应用DB密码: EcomApp@2026DB"
echo ""
echo "-------- Redis --------"
echo "Redis密码: ${REDIS_PASS}"
echo ""
echo "-------- 服务管理 --------"
echo "启动全部:   supervisorctl start ecommerce:*"
echo "停止全部:   supervisorctl stop ecommerce:*"
echo "重启全部:   supervisorctl restart ecommerce:*"
echo "查看状态:   supervisorctl status"
echo ""
echo "-------- 快速部署 --------"
echo "代码更新后执行: bash /data/ecommerce-ai/deploy.sh"
echo ""
echo "-------- 下一步 --------"
echo "1. 在本地初始化Git仓库并推送到GitHub"
echo "2. 在服务器上 git clone 到 /data/ecommerce-ai/"
echo "3. 运行数据库迁移SQL"
echo "4. supervisorctl start ecommerce:*"
echo "=========================================="
