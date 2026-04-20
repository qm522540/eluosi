#!/bin/bash
# Git pre-commit hook：提交前跑快速预检，拦住明显错误
# 安装：bash scripts/install-hooks.sh

set -e

# ==== 数据库迁移版本号撞号检查 ====
# 04-18（043）+ 04-19（048）连撞两次。硬拦防第 3 次。
staged_migrations=$(git diff --cached --name-only --diff-filter=A | grep -E '^database/migrations/versions/[0-9]{3}_.*\.sql$' || true)
if [ -n "$staged_migrations" ]; then
    echo "==== 迁移版本号撞号检查 ===="
    conflict=0
    for new_file in $staged_migrations; do
        ver=$(basename "$new_file" | cut -c1-3)
        # 查 versions/ 目录下同版本号的所有文件（排除自己）
        existing=$(ls "database/migrations/versions/${ver}_"*.sql 2>/dev/null | grep -v "^${new_file}$" || true)
        if [ -n "$existing" ]; then
            echo "ERROR: 迁移版本号 ${ver} 已被占用"
            echo "  新加: $new_file"
            echo "  已有: $existing"
            conflict=1
        fi
    done
    if [ $conflict -eq 1 ]; then
        echo ""
        echo "请把你的迁移文件重命名为下一个可用版本号后再 commit。"
        echo "查看当前最大版本号：ls database/migrations/versions/ | tail -5"
        exit 1
    fi
    echo "通过（$(echo "$staged_migrations" | wc -l) 个迁移）"
fi

# 只检查 staged 的 Python 文件
staged_py=$(git diff --cached --name-only --diff-filter=ACM | grep -E '^app/.*\.py$' || true)

if [ -n "$staged_py" ]; then
    echo "==== Python 语法预检 ===="
    # 用系统 python 跑 compile 足够检 SyntaxError（不需要 venv）
    PYTHON_BIN="${PYTHON_BIN:-python}"
    # 必须不仅存在，还能真正执行（Windows Store stub 的 python.exe 存在但跑不了）
    if ! "$PYTHON_BIN" -c "pass" > /dev/null 2>&1; then
        PYTHON_BIN=python3
    fi
    if ! "$PYTHON_BIN" -c "pass" > /dev/null 2>&1; then
        echo "WARN: 找不到可用的 python/python3（或是 Windows stub），跳过预检"
        exit 0
    fi

    has_err=0
    for f in $staged_py; do
        if [ -f "$f" ]; then
            "$PYTHON_BIN" -m py_compile "$f" 2>&1 || has_err=1
        fi
    done

    if [ $has_err -ne 0 ]; then
        echo ""
        echo "ERROR: Python 语法错误，提交已中止"
        echo "修正后重新 git add + commit。"
        exit 1
    fi
    echo "通过（$(echo "$staged_py" | wc -l) 个文件）"
fi

# TODO: 前端 eslint 检查（需先装 eslint）
staged_jsx=$(git diff --cached --name-only --diff-filter=ACM | grep -E '^frontend/src/.*\.(jsx?|tsx?)$' || true)
if [ -n "$staged_jsx" ] && [ -f "frontend/node_modules/.bin/eslint" ]; then
    echo "==== 前端 eslint ===="
    cd frontend && ./node_modules/.bin/eslint $(echo "$staged_jsx" | sed 's|frontend/||g') || exit 1
    cd - > /dev/null
    echo "通过"
fi

exit 0
