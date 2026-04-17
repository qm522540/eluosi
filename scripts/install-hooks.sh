#!/bin/bash
# 安装 git hooks（一次性执行）
# 把 scripts/pre-commit.sh 链接/复制到 .git/hooks/pre-commit
set -e

HOOK_DIR=".git/hooks"
if [ ! -d "$HOOK_DIR" ]; then
    echo "ERROR: 不是 git 仓库根目录，跑这个脚本请先 cd 到仓库根"
    exit 1
fi

# Windows / Git Bash 软链接不稳定，直接复制
cp scripts/pre-commit.sh "$HOOK_DIR/pre-commit"
chmod +x "$HOOK_DIR/pre-commit"

echo "已安装 pre-commit 钩子 → $HOOK_DIR/pre-commit"
echo "提交时会自动跑 Python 语法预检（目前只对 app/*.py）"
echo ""
echo "如需跳过钩子：git commit --no-verify（请谨慎使用）"
