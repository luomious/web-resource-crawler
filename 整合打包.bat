@echo off
chcp 65001 >nul
cd /d "E:\VSCode\VSCode-Workspace\Web Resource Crawler"

set PY=C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python312\python.exe
set SP=C:\Users\%USERNAME%\AppData\Roaming\Python\Python313\site-packages

echo ==========================================
echo   网页资源爬虫 - 整合打包生成单EXE
echo ==========================================
echo.

echo [1/4] 安装缺失依赖...
%PY% -m pip install packaging pywin32-ctypes --target "%SP%" -q
echo   完成

echo [2/4] 清除旧文件...
taskkill /F /IM "网页资源爬虫.exe" 2>nul
rmdir /S /Q build dist 2>nul
del /Q *.spec 2>nul
echo   完成

echo [3/4] 打包中...
set PYTHONPATH=%SP%
%PY% -m PyInstaller --onefile --windowed --name "网页资源爬虫" --add-data "core;core" --hidden-import PyQt5 --hidden-import requests --clean --noconfirm gui.py

if not exist "dist\网页资源爬虫.exe" (
    echo   打包失败！
    pause & exit /b 1
)
echo   完成

echo [4/4] 部署 + 清理...
copy /Y "dist\网页资源爬虫.exe" "%USERPROFILE%\Desktop\" >nul
del /Q "%USERPROFILE%\Desktop\网页资源爬虫.vbs" "%USERPROFILE%\Desktop\启动爬虫.bat" 2>nul
rmdir /S /Q build 2>nul
del /Q *.spec 2>nul

echo.
echo ==========================================
echo   成功！桌面只有一个 网页资源爬虫.exe
echo   输入: https://www.asmr.one/work/RJ01568719
echo ==========================================
pause
