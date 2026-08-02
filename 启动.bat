@echo off
chcp 65001 >nul
echo === 清理残留进程 ===
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000.*LISTENING"') do taskkill /F /PID %%a 2>nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5174.*LISTENING"') do taskkill /F /PID %%a 2>nul
echo === 启动后端 ===
start "SteelDigitize-Backend" cmd /c "cd /d G:\SteelDigitize\backend && python -m uvicorn main:app --port 8000 --host 127.0.0.1"
echo === 启动前端 ===
start "SteelDigitize-Frontend" cmd /c "cd /d G:\SteelDigitize\frontend && npm run dev"
echo.
echo 后端: http://localhost:8000
echo 前端: http://localhost:5174
pause
