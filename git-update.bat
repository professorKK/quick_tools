@echo off
REM ==========================================================================
REM git-update.sh 的 Windows 包装器
REM
REM 作用：让 Windows 的 cmd / PowerShell / 资源管理器双击也能使用同一套提交逻辑，
REM       真正的实现仍然是仓库根目录的 git-update.sh（只维护一份，避免两份逻辑跑偏）。
REM 依赖：Git for Windows 自带的 bash。
REM 用法：
REM   git-update.bat 更新内容
REM   git-update.bat 修复 通道分配      （多词不用加引号）
REM 生成提交信息：YYMMDD: 更新内容
REM ==========================================================================

REM 让命令行正确显示中文（UTF-8）。本文件必须保持 CRLF 换行。
chcp 65001 >nul

setlocal

REM 无论从哪里调用，都切到仓库根目录再提交。
cd /d "%~dp0"

REM 找 bash：优先 PATH，其次 Git for Windows 的常见安装位置。
set "BASH="
where bash >nul 2>nul && set "BASH=bash"
if not defined BASH if exist "%ProgramFiles%\Git\bin\bash.exe" set "BASH=%ProgramFiles%\Git\bin\bash.exe"
if not defined BASH if exist "%ProgramFiles(x86)%\Git\bin\bash.exe" set "BASH=%ProgramFiles(x86)%\Git\bin\bash.exe"
if not defined BASH if exist "%LOCALAPPDATA%\Programs\Git\bin\bash.exe" set "BASH=%LOCALAPPDATA%\Programs\Git\bin\bash.exe"

if not defined BASH (
  echo 未找到 bash。git-update.bat 需要 Git for Windows 自带的 bash，
  echo 请安装 Git for Windows：https://git-scm.com/download/win
  exit /b 1
)

"%BASH%" "%~dp0git-update.sh" %*
exit /b %errorlevel%
