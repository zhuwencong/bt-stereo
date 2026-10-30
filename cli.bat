@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m bt_stereo --cli list
echo.
echo ==========================================
echo  Choose LEFT / RIGHT speaker and SOURCE
echo ==========================================
echo.
python -m bt_stereo --cli run
pause
