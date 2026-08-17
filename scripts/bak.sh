#!/usr/bin/env bash
# 修改任何已有文件前，先在同目录生成 .bak 备份（沙盒原则的一部分）。
# 用法: bash scripts/bak.sh path/to/file.py
set -euo pipefail

if [ -z "${1:-}" ]; then
  echo "用法: bash scripts/bak.sh <file>"
  exit 1
fi

if [ ! -f "$1" ]; then
  echo "文件不存在: $1"
  exit 1
fi

cp -p "$1" "$1.bak"
echo "已备份: $1.bak"
