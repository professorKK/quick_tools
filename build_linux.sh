#!/usr/bin/env bash
# ============================================================================
# QuickTools Linux 打包脚本
#
# 作用：用 PyInstaller 把项目打包成独立的目录版程序，目标机器不需要安装
#       Python 也能运行。
# 产物：dist/QuickTools/QuickTools
#       分发时要整个 dist/QuickTools 文件夹一起拷贝。
# 用法：在任意目录执行  ./build_linux.sh
# ============================================================================

# -e：任何命令出错就立即停止；
# -u：使用未定义变量时报错；
# -o pipefail：管道中任何一步失败都算失败。
set -euo pipefail

# 切换到脚本所在目录，保证下面用到的相对路径都正确。
cd "$(dirname "$0")"

# 如果项目里还没有虚拟环境 .venv，就创建一个，避免污染系统 Python。
if [ ! -x ".venv/bin/python" ]; then
  python3 -m venv .venv
fi

# 在虚拟环境里安装：
#   -e '.[dev]'  本项目（可编辑安装，附带测试依赖）
#   pyinstaller  打包工具
.venv/bin/pip install -e '.[dev]' pyinstaller

# 按照 QuickTools.spec 的配置打包。
# --noconfirm：如果已有旧产物，直接覆盖，不再询问。
.venv/bin/pyinstaller --noconfirm QuickTools.spec

# 告诉用户最终可执行文件在哪里。
echo
echo "Linux 打包完成：$(pwd)/dist/QuickTools/QuickTools"
