@echo off
setlocal
cd /d "C:\Dev\Daily Stock"
set PYTHONIOENCODING=utf-8
set LOGDIR=C:\Dev\Daily Stock\logs
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
echo [%date% %time%] === start chips_report.py ===>> "%LOGDIR%\chips.log"
C:\Users\stick\.local\bin\uv.exe run python -X utf8 chips_report.py>> "%LOGDIR%\chips.log" 2>&1
echo [%date% %time%] === end chips_report.py exit=%errorlevel% ===>> "%LOGDIR%\chips.log"
exit /b %errorlevel%
