@echo off
REM ==========================================================================
REM QuickTools Windows 打包脚本（仅目录版）
REM
REM 作用：用 PyInstaller 把项目打包成独立的目录版程序，目标电脑不需要安装
REM       Python 也能运行。
REM 产物：dist\win\QuickTools\QuickTools.exe
REM       （按平台分目录，和 Linux 的 dist\linux\ 互不干扰）
REM       分发时要整个 dist\win\QuickTools 文件夹一起拷贝。
REM 需要单文件版和安装包时，请改用 build_all.bat。
REM 用法：双击本文件，或在命令行执行 build_windows.bat
REM ==========================================================================

REM 让命令行正确显示中文（UTF-8）。
chcp 65001 >nul

REM 让本文件里的变量只在本次运行期间有效。
setlocal

REM 切换到脚本所在目录（%~dp0 是本脚本所在的文件夹），
REM /d 表示如果不在同一盘符也一起切换。
cd /d "%~dp0"

REM 如果项目里还没有虚拟环境 .venv，就用 py -3 创建一个。
REM errorlevel 1 表示创建失败，直接退出。
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 exit /b 1
)

REM 启用虚拟环境，这样后面安装和打包都只用项目自己的 Python。
call ".venv\Scripts\activate.bat"

REM 如果 QuickTools.exe 正在运行，PyInstaller 会因为文件被占用而失败，
REM 这里提前检查并给出明确提示，而不是让用户看一堆 PermissionError。
tasklist /fi "IMAGENAME eq QuickTools.exe" 2>nul | findstr /i "QuickTools.exe" >nul
if not errorlevel 1 (
  echo 检测到 QuickTools.exe 正在运行，请先从状态栏菜单退出程序后再打包。
  exit /b 1
)

REM 依赖已装好时跳过 pip。网络不通时 pip 会卡在下载 setuptools 的构建
REM 隔离环境里，而且没有输出；只有缺依赖时才安装。
python -c "import PyInstaller, PIL, pynput, pystray, pytest" >nul 2>&1
if errorlevel 1 (
  echo 正在安装缺失的依赖...
  python -m pip install --disable-pip-version-check --no-build-isolation --timeout 15 -e ".[dev]" pyinstaller
  if errorlevel 1 exit /b 1
) else (
  echo 依赖已就绪，跳过安装。
)

REM 按照 QuickTools.spec 的配置打包。
REM 用 python -m PyInstaller 而不是直接调用 pyinstaller，
REM 确保用的是当前虚拟环境里的打包工具。
REM --noconfirm：如果已有旧产物，直接覆盖，不再询问。
REM --distpath/--workpath：产物放进 dist\win\，中间文件放进 build\win\，
REM 和 Linux 的 dist\linux\、build\linux\ 互不干扰。
python -m PyInstaller --noconfirm --distpath dist\win --workpath build\win QuickTools.spec
if errorlevel 1 exit /b 1

REM 某些沙箱/安全软件会给工作区文件打上 Low 完整性标签。带这个标签的 exe
REM 会以低权限启动，可能连 %TEMP%/%APPDATA% 都写不了。构建结束后标回 Medium。
icacls "dist\win" /setintegritylevel Medium /T >nul 2>&1

REM 提示最终可执行文件的位置。
echo.
echo Windows 打包完成：%CD%\dist\win\QuickTools\QuickTools.exe
endlocal
