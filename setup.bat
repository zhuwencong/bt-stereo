@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ==========================================
echo   第一次使用：安装运行需要的两个库
echo ==========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [X] 没找到 Python。
    echo     请先到 https://www.python.org/downloads/ 下载安装，
    echo     安装时务必勾选 "Add python.exe to PATH"。
    echo.
    pause
    exit /b 1
)

echo [1/2] 检查 Python 版本 ...
python -c "import sys; assert sys.version_info >= (3, 10), sys.version; print('     Python', sys.version.split()[0], 'OK')"
if errorlevel 1 (
    echo [X] Python 版本太旧，需要 3.10 或更高。
    pause
    exit /b 1
)

echo [2/2] 安装 numpy 和 comtypes ...
python -m pip install --upgrade numpy comtypes
if errorlevel 1 (
    echo.
    echo [X] 安装失败。如果是网络问题，可以试试国内镜像：
    echo     python -m pip install numpy comtypes -i https://pypi.tuna.tsinghua.edu.cn/simple
    echo.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo   安装完成！现在双击 "启动.bat" 就能用了
echo ==========================================
echo.
pause
