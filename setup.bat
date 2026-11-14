@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo   第一次使用：安装运行需要的两个库
echo ==========================================
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY goto no_python

%PY% -c "import sys" >nul 2>nul
if errorlevel 1 goto no_python

echo [1/3] 检查 Python 版本 ...
%PY% -c "import sys; assert sys.version_info >= (3, 10), sys.version; print('     Python ' + sys.version.split()[0] + ' OK')"
if errorlevel 1 (
    echo [X] Python 版本太旧，需要 3.10 或更高。
    pause
    exit /b 1
)

rem 版本检查通过未必能装包（比如某些嵌入式发行版没有 pip）
echo [2/3] 检查 pip ...
%PY% -m pip --version >nul 2>nul
if errorlevel 1 (
    echo [X] 这个 Python 没有 pip，无法安装依赖。
    echo     建议改用便携版：https://github.com/zhuwencong/bt-stereo/releases/latest
    pause
    exit /b 1
)

echo [3/3] 安装 numpy 和 comtypes ...
rem 不加 --upgrade：避免把用户/其它工具正在用的 numpy 顶到新版本
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [X] 安装失败。如果是网络问题，可以试试国内镜像：
    echo     %PY% -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    echo.
    pause
    exit /b 1
)

rem 装完必须真跑一次才算成功，pip 退出码 0 不代表能 import
echo.
echo 验证依赖 ...
%PY% -c "import numpy, comtypes; print('     numpy ' + numpy.__version__ + ' / comtypes ' + comtypes.__version__ + ' OK')"
if errorlevel 1 (
    echo [X] 依赖装了但导入失败，请把上面的错误信息发给作者。
    pause
    exit /b 1
)

%PY% -c "import tkinter" >nul 2>nul
if errorlevel 1 (
    echo.
    echo [!] 提醒：这个 Python 还缺少 tkinter，图形界面会打不开。
    echo     重新运行 Python 安装包选 Modify，勾上 "tcl/tk and IDLE" 即可补装。
    echo     或者直接用便携版（不需要 Python）：
    echo     https://github.com/zhuwencong/bt-stereo/releases/latest
    echo.
)

echo.
echo ==========================================
echo   安装完成！现在双击 "启动.bat" 就能用了
echo ==========================================
echo.
pause
exit /b 0

:no_python
echo [X] 没找到可用的 Python。
echo.
echo     你看到的 "python" 可能只是应用商店占位符。
echo     请到 https://www.python.org/downloads/ 下载安装，
echo     安装时务必勾选 "Add python.exe to PATH" 和 "tcl/tk and IDLE"。
echo.
echo     不想装也行，直接用便携版：
echo     https://github.com/zhuwencong/bt-stereo/releases/latest
echo.
pause
exit /b 1
