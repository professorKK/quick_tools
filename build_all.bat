@echo off
REM ==========================================================================
REM QuickTools Windows 一键打包脚本
REM
REM 一次产出三种分发形式，全部放在 dist\win\ 下（与 Linux 的 dist\linux\ 分开）：
REM   dist\win\QuickTools\QuickTools.exe        目录版（启动最快，需整个文件夹分发）
REM   dist\win\QuickTools.exe                   单文件版（约 21MB，直接发这一个文件）
REM   dist\win\QuickTools-Setup.exe             安装包（需已安装 Inno Setup 6）
REM
REM 中间文件放在 build\win\、build\win_onefile\，不会混进分发包。
REM Inno Setup 未安装时会跳过安装包，前两项照常完成。
REM 只需要目录版时用 build_windows.bat。
REM 用法：双击本文件，或在命令行执行 build_all.bat
REM ==========================================================================

REM 让命令行正确显示中文（UTF-8）。
REM 注意：本文件必须保持 CRLF 换行，否则 cmd 会把多行拼成一条命令执行。
chcp 65001 >nul

setlocal

REM 切换到脚本所在目录（%~dp0 是本脚本所在的文件夹）。
cd /d "%~dp0"

REM 如果项目里还没有虚拟环境 .venv，就用 py -3 创建一个。
if not exist ".venv\Scripts\python.exe" (
  echo 正在创建虚拟环境 .venv ...
  py -3 -m venv .venv
  if errorlevel 1 goto :fail
)

REM 启用虚拟环境，后面所有命令都只用项目自己的 Python。
call ".venv\Scripts\activate.bat"

REM 程序正在运行时文件被占用，PyInstaller 会以 PermissionError 失败，
REM 这里提前检查并给出明确提示。
tasklist /fi "IMAGENAME eq QuickTools.exe" 2>nul | findstr /i "QuickTools.exe" >nul
if not errorlevel 1 (
  echo 检测到 QuickTools.exe 正在运行，请先从状态栏菜单退出程序后再打包。
  goto :fail
)

echo.
echo ========== [1/3] 安装依赖 ==========
python -m pip install --disable-pip-version-check -q -e ".[dev]" pyinstaller
if errorlevel 1 goto :fail

echo.
echo ========== [2/3] 打包：Windows 目录版 ==========
python -m PyInstaller --noconfirm --distpath dist\win --workpath build\win QuickTools.spec
if errorlevel 1 goto :fail

echo.
echo ========== [2/3] 打包：Windows 单文件版 ==========
REM 单文件版直接放进 dist\win\，与目录版的 QuickTools 文件夹并存。
python -m PyInstaller --noconfirm --distpath dist\win --workpath build\win_onefile QuickTools-onefile.spec
if errorlevel 1 goto :fail

echo.
echo ========== [3/3] 打包：Windows 安装包 ==========
REM 依次在常见安装路径和 PATH 中查找 Inno Setup 的编译命令 ISCC.exe。
REM 注意：winget 默认按用户安装到 %LOCALAPPDATA%\Programs，不会写进 PATH。
set "ISCC="
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC for /f "delims=" %%i in ('where iscc 2^>nul') do set "ISCC=%%i"

if not defined ISCC (
  echo 未检测到 Inno Setup 6，已跳过安装包。
  echo 需要安装包时请先安装 https://jrsoftware.org/isdl.php ，再重新运行本脚本。
) else (
  "%ISCC%" installer.iss
  if errorlevel 1 goto :fail
)

echo.
echo ==================== 打包完成 ====================
echo   目录版：%CD%\dist\win\QuickTools\QuickTools.exe
echo           （分发时要整个 dist\win\QuickTools 文件夹一起拷贝）
echo   单文件：%CD%\dist\win\QuickTools.exe
if defined ISCC (
  echo   安装包：%CD%\dist\win\QuickTools-Setup.exe
) else (
  echo   安装包：未生成（缺少 Inno Setup 6）
)
echo ==================================================
endlocal
exit /b 0

:fail
echo.
echo 打包失败，请查看上面的错误信息。
endlocal
exit /b 1
