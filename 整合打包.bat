@echo off
chcp 65001 >nul
cd /d "E:\VSCode\VSCode-Workspace\Web Resource Crawler"

echo ==========================================
echo   网页资源爬虫 - 一键打包部署
echo ==========================================
echo.

set VENV_DIR=%CD%\venv
set PYTHON=%VENV_DIR%\Scripts\python.exe
set PIP=%VENV_DIR%\Scripts\pip.exe

:: 检查 venv
if not exist "%PYTHON%" (
    echo [错误] 找不到 venv 中的 Python
    echo 路径: %PYTHON%
    pause & exit /b 1
)

echo [1/5] 安装/更新打包工具...
"%PIP%" install -U pyinstaller -q
if errorlevel 1 (
    echo [错误] PyInstaller 安装失败
    pause & exit /b 1
)
echo   完成

echo [2/5] 清除旧文件...
taskkill /F /IM "网页资源爬虫.exe" 2>nul
timeout /t 1 /nobreak >nul
rmdir /S /Q build 2>nul
rmdir /S /Q dist 2>nul
del /Q *.spec 2>nul
echo   完成

echo [3/5] 打包中（约2-3分钟，请等待）...
"%PYTHON%" -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name "网页资源爬虫" ^
    --add-data "core;core" ^
    --hidden-import PyQt5 ^
    --hidden-import requests ^
    --hidden-import bs4 ^
    --hidden-import urllib3 ^
    --hidden-import lxml ^
    --clean ^
    --noconfirm ^
    gui.py

if not exist "dist\网页资源爬虫.exe" (
    echo.
    echo [错误] 打包失败！查看上方错误信息
    pause & exit /b 1
)
echo   完成

echo [4/5] 复制到桌面...
copy /Y "dist\网页资源爬虫.exe" "%USERPROFILE%\Desktop\" >nul
echo   完成

echo [5/5] 清理桌面多余文件...
del /Q "%USERPROFILE%\Desktop\网页资源爬虫.bat" 2>nul
del /Q "%USERPROFILE%\Desktop\网页资源爬虫.vbs" 2>nul
del /Q "%USERPROFILE%\Desktop\启动爬虫.bat" 2>nul
echo   完成

echo.
echo ==========================================
echo   成功！桌面已只有一个 EXE
echo   支持 asmr.one / 普通网页 / HLS 下载
echo ==========================================
pause
