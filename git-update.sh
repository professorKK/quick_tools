#!/bin/bash
# git 快捷提交脚本
#
# 用法:
#   ./git-update.sh 更新内容
#   ./git-update.sh 修复 CAN 通道分配      # 多词不用加引号
#   ./git-update.sh "修复 CAN 通道分配"    # 加引号也行
#
# 生成提交信息: YYMMDD: 更新内容
# 例如 2026-09-23 执行 → 260923: 修复 CAN 通道分配

set -e

if [ $# -eq 0 ]; then
    echo "用法: $0 更新内容"
    echo "例如: $0 修复 CAN 通道分配"
    exit 1
fi

DATE=$(date +%y%m%d)
MSG="${DATE}: $*"

git add .

# 没有改动时不报错，直接退出（否则 git commit 会抛 "nothing to commit"）
if git diff --cached --quiet; then
    echo "没有需要提交的改动，已跳过。"
    exit 0
fi

git commit -m "$MSG"
echo "已提交: $MSG"
