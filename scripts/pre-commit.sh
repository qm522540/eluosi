#!/bin/bash
# Git pre-commit hook：提交前跑快速预检，拦住明显错误
# 安装：bash scripts/install-hooks.sh

set -e

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
