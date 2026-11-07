@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
python crawler_v2.py select --delay 5 --jitter 0 --stats-every 10 --verify-timeout 120 --page-timeout 45 %*
pause
