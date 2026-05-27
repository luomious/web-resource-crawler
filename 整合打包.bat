@echo off
chcp 65001 >nul
cd /d "E:\VSCode\VSCode-Workspace\Web Resource Crawler"

:: 获取用户名（处理中文乱码）
for /f "tokens=2 delims=\" %%a in ('whoami') do set USER=%%a

set PY=C:\Users\%USER%\AppData\Local\Programs\Python\Python312\python.exe
set SP=C:\Users\%USER%\AppData\Roaming\Python\Python313\site-packages

echo ==========================================
echo   网页资源爬虫 - 整合打包
echo ==========================================
echo.

if not exist "%PY%" (
    echo 错误: 找不到 Python
    echo %PY%
    pause & exit /b 1
)

echo [1/4] 安装依赖...
"%PY%" -m pip install packaging pywin32-ctypes --target "%SP%" -q
echo   完成

echo [2/4] 清除旧文件...
taskkill /F /IM "网页资源爬虫.exe" 2>nul
taskkill /F /IM "python.exe" 2>nul
rmdir /S /Q build dist 2>nul
del /Q *.spec 2>nul
echo   完成

echo [3/4] 打包中（约2-3分钟）...
set PYTHONPATH=%SP%
"%PY%" -m PyInstaller --onefile --windowed --name "网页资源爬虫" --add-data "core;core" --hidden-import PyQt5 --hidden-import requests --clean --noconfirm gui.py

if not exist "dist\网页资源爬虫.exe" (
    echo   打包失败！查看上方错误信息
    pause & exit /b 1
)
echo   完成

echo [4/4] 部署 + 清理桌面...
copy /Y "dist\网页资源爬虫.exe" "%USERPROFILE%\Desktop\" >nul
del /Q "%USERPROFILE%\Desktop\网页资源爬虫.vbs" 2>nul
del /Q "%USERPROFILE%\Desktop\启动爬虫.bat" 2>nul
rmdir /S /Q build 2>nul
del /Q *.spec 2>nul

echo.
echo ==========================================
echo   成功！桌面只有一个 EXE
echo   输入: https://www.asmr.one/work/RJ01568719
echo ==========================================
pause
