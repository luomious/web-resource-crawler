@echo off
cd /d "E:\VSCode\VSCode-Workspace\Web Resource Crawler"

echo ==========================================
echo   网页资源爬虫 - 打包器
echo ==========================================
echo.

echo 查找 Python...
set PYTHON=
if exist "E:\Anaconda\python.exe" (
    echo   找到: E:\Anaconda\python.exe
    set PYTHON=E:\Anaconda\python.exe
)
if "%PYTHON%"=="" (
    echo   Python 未找到，请先安装 Python
    echo   下载: https://www.python.org/downloads/
    pause & exit /b 1
)

echo 检查 PyInstaller...
%PYTHON% -c "import PyInstaller; print('   OK')" 2>nul || (
    echo   正在安装 PyInstaller...
    %PYTHON% -m pip install pyinstaller --user -q
)

echo 清除缓存...
rmdir /S /Q build dist 2>nul
del /Q *.spec 2>nul
rmdir /S /Q __pycache__ core\__pycache__ 2>nul

echo 打包中（2-3分钟）...
%PYTHON% -m PyInstaller --onefile --windowed --name "网页资源爬虫" --add-data "core;core" --hidden-import PyQt5 --hidden-import requests --hidden-import bs4 --hidden-import lxml --clean --noconfirm gui.py

if not exist "dist\网页资源爬虫.exe" (
    echo 打包失败！
    pause & exit /b 1
)

taskkill /F /IM "网页资源爬虫.exe" 2>nul
copy /Y "dist\网页资源爬虫.exe" "%USERPROFILE%\Desktop\网页资源爬虫.exe" >nul

echo.
echo ==========================================
echo   成功！
echo   输入: https://www.asmr.one/work/RJ01568719
echo   应显示 113 个资源
echo ==========================================
pause
