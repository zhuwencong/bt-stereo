@echo off
setlocal
cd /d "%~dp0"

rem ============================================================
rem  启动脚本
rem  设计原则：任何失败都必须让用户看到中文原因，绝不静默退出。
rem  （旧版用 pythonw + exit /b 0，缺 tkinter 时双击毫无反应，
rem    用户完全无从排障。）
rem ============================================================

rem ---------- 1. 找 Python ----------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY goto no_python

rem Windows 应用商店的占位符会"存在"但跑不起来，必须真跑一次才算数
%PY% -c "import sys" >nul 2>nul
if errorlevel 1 goto no_python

rem ---------- 2. 版本 ----------
%PY% -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul
if errorlevel 1 goto bad_version

rem ---------- 3. 依赖（分模块检查，好报清楚缺哪个）----------
%PY% -c "import numpy" >nul 2>nul
if errorlevel 1 goto no_deps
%PY% -c "import comtypes" >nul 2>nul
if errorlevel 1 goto no_deps
%PY% -c "import tkinter" >nul 2>nul
if errorlevel 1 goto no_tk

rem ---------- 4. 启动 ----------
rem 先用 pythonw 静默启动（不弹黑框）；3 秒后若进程不在，说明崩了，
rem 再用 cmd /k 前台重跑一次，让 traceback 直接显示出来。
set "PWG="
where pythonw >nul 2>nul && set "PWG=pythonw"
if not defined PWG (
    start "" %PY% -m bt_stereo
    exit /b 0
)

start "" %PWG% -m bt_stereo
call :wait 3

tasklist /FI "IMAGENAME eq pythonw.exe" 2>nul | find /I "pythonw.exe" >nul
if not errorlevel 1 exit /b 0

rem ---- 没起来：前台重跑，把错误亮出来 ----
echo.
echo ==========================================
echo   程序启动失败了，下面是具体错误信息
echo ==========================================
echo.
cmd /k "%PY% -m bt_stereo"
exit /b 1

rem ---------- 等待若干秒（不用 timeout.exe：stdin 被重定向时会报错）----------
:wait
ping -n %1 127.0.0.1 >nul
exit /b 0

rem ============================================================
rem  出错分支
rem ============================================================
:no_python
echo ==========================================
echo   [X] 没找到可用的 Python
echo ==========================================
echo.
echo  注意：如果你见过 "python" 这个命令，它可能只是
echo  Windows 应用商店的占位符，并不是真的 Python。
echo.
echo  两个办法，任选其一：
echo.
echo    [A] 装 Python（装完回来双击本文件即可）
echo        https://www.python.org/downloads/
echo        安装时务必勾选这两项：
echo          - Add python.exe to PATH
echo          - tcl/tk and IDLE
echo.
echo    [B] 用便携版，不用装任何东西（推荐给不想折腾的）
echo        https://github.com/zhuwencong/bt-stereo/releases/latest
echo.
pause
exit /b 1

:bad_version
echo [X] Python 版本太旧，本程序需要 3.10 或更高。
echo.
%PY% -c "import sys; print('    当前版本：' + sys.version.split()[0])"
echo.
echo     请到 https://www.python.org/downloads/ 安装新版本。
echo.
pause
exit /b 1

:no_deps
echo ==========================================
echo   [X] 缺少运行库（numpy 或 comtypes）
echo ==========================================
echo.
echo  先双击 setup.bat 自动装好，或手动执行：
echo      %PY% -m pip install numpy comtypes
echo.
echo  国内网络慢可以加镜像：
echo      %PY% -m pip install numpy comtypes -i https://pypi.tuna.tsinghua.edu.cn/simple
echo.
pause
exit /b 1

:no_tk
echo ==========================================
echo   [X] 你的 Python 缺少 tkinter（图形界面模块）
echo ==========================================
echo.
echo  精简安装的 Python、或用包管理器装的 Python，经常不带
echo  tkinter。本程序要开窗口就必须有它。
echo.
echo  三个办法，任选其一：
echo.
echo    [1] 补装 tkinter（已有 Python 的话最快）
echo        重新运行当初的 Python 安装包，选 Modify，
echo        勾上 "tcl/tk and IDLE"，然后下一步。
echo.
echo    [2] 用便携版，不用装任何东西
echo        https://github.com/zhuwencong/bt-stereo/releases/latest
echo.
echo    [3] 只用命令行（功能一样全，只是没有窗口）
echo        %PY% -m bt_stereo --cli list
echo        %PY% -m bt_stereo --cli run
echo.
pause
exit /b 1
