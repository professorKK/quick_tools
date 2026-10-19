@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 exit /b 1
)

call ".venv\Scripts\activate.bat"
python -m pip install -e ".[dev]" pyinstaller
if errorlevel 1 exit /b 1

pyinstaller --noconfirm QuickTools.spec
if errorlevel 1 exit /b 1

echo.
echo Windows packaging complete: %CD%\dist\QuickTools\QuickTools.exe
endlocal
