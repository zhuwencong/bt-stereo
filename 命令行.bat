@echo off
setlocal
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo [X] 没找到可用的 Python。请先双击 setup.bat，或改用便携版。
    pause
    exit /b 1
)

%PY% -m bt_stereo --cli list
echo.
echo ==========================================
echo  依次填入 左声道音箱 / 右声道音箱 / 音源
echo  （填编号或名字片段都行，音源不能和左右相同）
echo ==========================================
echo.
%PY% -m bt_stereo --cli run
pause
