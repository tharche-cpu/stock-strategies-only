@echo off
setlocal
cd /d "C:\Dev\Daily Stock"
set PYTHONIOENCODING=utf-8
set LOGDIR=C:\Dev\Daily Stock\logs
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
echo [%date% %time%] === start premarket.py ===>> "%LOGDIR%\premarket.log"
C:\Users\stick\.local\bin\uv.exe run python -X utf8 premarket.py>> "%LOGDIR%\premarket.log" 2>&1
echo [%date% %time%] === end premarket.py exit=%errorlevel% ===>> "%LOGDIR%\premarket.log"
exit /b %errorlevel%
