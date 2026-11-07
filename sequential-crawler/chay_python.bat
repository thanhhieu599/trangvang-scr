@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
python crawler.py select --browser --browser-channel chrome --stealth --delay 5 --jitter 1 --stats-every 15 --verify-timeout 120 --page-timeout 45 %*
pause
