@echo off
rem Daily run for Windows Task Scheduler: download new prices, then forecast tomorrow.
rem Everything the scripts print is added to logs\daily.log.

cd /d "%~dp0"
if not exist logs mkdir logs
set PYTHONIOENCODING=utf-8

echo ===== %date% %time% ===== >> logs\daily.log
python main.py >> logs\daily.log 2>&1
python predict.py >> logs\daily.log 2>&1
