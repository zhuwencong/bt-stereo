@echo off
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 goto nopython
python -c "import numpy, comtypes" >nul 2>nul
if errorlevel 1 goto nodeps

set "PY=python"
where pythonw >nul 2>nul
if not errorlevel 1 set "PY=pythonw"
start "" %PY% -m bt_stereo
exit /b 0

:nopython
echo [ERROR] Python not found in PATH. Install Python 3.10+ first.
pause
exit /b 1

:nodeps
echo [ERROR] Missing packages. Run: python -m pip install numpy comtypes
pause
exit /b 1
