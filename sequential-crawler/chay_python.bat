@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
python crawler.py run --browser --browser-channel chrome --stealth --delay 8 --jitter 2 --stats-every 15 %*
pause
