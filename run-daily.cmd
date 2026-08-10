@echo off
setlocal
cd /d "C:\Dev\Daily Stock"
set PYTHONIOENCODING=utf-8
set LOGDIR=C:\Dev\Daily Stock\logs
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
echo [%date% %time%] === start main.py ===>> "%LOGDIR%\daily.log"
C:\Users\stick\.local\bin\uv.exe run python -X utf8 main.py>> "%LOGDIR%\daily.log" 2>&1
echo [%date% %time%] === end main.py exit=%errorlevel% ===>> "%LOGDIR%\daily.log"
exit /b %errorlevel%
