@echo off
setlocal
cd /d "%~dp0"
call conda run --no-capture-output -n chardet python -m pip install -r packaging/requirements-windows.txt
if errorlevel 1 exit /b 1
call conda run --no-capture-output -n chardet python -m PyInstaller --noconfirm --clean app.spec
if errorlevel 1 (
  pause
  exit /b 1
)
echo Built: dist\group_by_character\group_by_character.exe

if defined HANZI_UPDATE_FEED (
  call conda run --no-capture-output -n chardet python packaging/native_release.py windows
  if errorlevel 1 exit /b 1
)
