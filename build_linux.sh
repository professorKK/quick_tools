#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  python3 -m venv .venv
fi

.venv/bin/pip install -e '.[dev]' pyinstaller
.venv/bin/pyinstaller --noconfirm QuickTools.spec

echo
echo "Linux 打包完成：$(pwd)/dist/QuickTools/QuickTools"
