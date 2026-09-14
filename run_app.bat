@echo off
title PyQt6 Download Manager - ChkeaPikheat
cd /d " %~dp0\
echo ========================================================
echo Launching PyQt6 Download Manager (One UI 9)
echo ========================================================
echo.
python -m downloader_app.main
if %errorlevel% neq 0 (
 echo.
 echo Application exited with an error. Press any key to close...
 pause >nul
)
