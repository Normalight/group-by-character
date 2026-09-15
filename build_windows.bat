@echo off
setlocal
cd /d "%~dp0"
call conda run --no-capture-output -n chardet python -m PyInstaller --noconfirm app.spec
if errorlevel 1 (
  pause
  exit /b 1
)
echo Built: dist\group_by_character\group_by_character.exe
