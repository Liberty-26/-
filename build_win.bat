@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo   SteelDigitize Pro - Windows 一键打包
echo   需要：已安装 Python 3.11+ 与 Node.js 18+
echo ============================================
echo.

echo [1/4] 安装后端依赖（含打包工具与识别 SDK）...
cd backend
pip install -r requirements.txt pyinstaller yescan || goto :err

echo [2/4] 打包内置后端（SteelDigitizeBackend.exe）...
pyinstaller --noconfirm --clean --name SteelDigitizeBackend --onedir --noconsole ^
  --collect-all uvicorn --collect-all fastapi --collect-all openpyxl --collect-all yescan ^
  --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto ^
  --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets.auto ^
  --hidden-import uvicorn.lifespan.on backend_entry.py || goto :err

echo [3/4] 构建前端并准备 Electron 资源...
cd ..\frontend
call npm install || goto :err
call npm run build || goto :err
cd ..\electron
if not exist backend-dist mkdir backend-dist
if exist backend-dist\SteelDigitizeBackend rmdir /S /Q backend-dist\SteelDigitizeBackend
xcopy /E /I /Y ..\backend\dist\SteelDigitizeBackend backend-dist\SteelDigitizeBackend >nul || goto :err

echo [4/4] 打包 Windows 安装包（含桌面快捷方式）...
call npm install || goto :err
call npm run dist:win || goto :err

echo.
echo ============================================
echo   打包完成！安装包位置：
echo   electron\release\SteelDigitize-Pro-Setup-1.0.0.exe
echo   用户安装后桌面会自动出现快捷方式，双击即可打开。
echo ============================================
pause
exit /b 0

:err
echo.
echo 打包失败，请检查上方错误信息后重试。
pause
exit /b 1
