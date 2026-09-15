@echo off
cd /d "%~dp0"
call conda run --no-capture-output -n chardet python app.py
if errorlevel 1 pause
