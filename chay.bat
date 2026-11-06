@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
pip install -q -r requirements.txt
python scraper.py watch %*
pause
