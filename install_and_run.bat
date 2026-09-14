@echo off
title PyQt6 Download Manager - Auto Setup & Launcher
cd /d " %~dp0\
echo ========================================================
echo PyQt6 Download Manager - Automated Setup
echo ========================================================
echo.
echo [1/3] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
 echo [ERROR] Python is not installed or not in PATH!
 echo Please install Python 3.10+ from python.org and check \Add python.exe to PATH\.
 pause
 exit /b 1
)
echo [2/3] Installing required packages from requirements.txt...
python -m pip install -r requirements.txt
echo.
echo [3/3] Starting Application...
echo.
python -m downloader_app.main
if %errorlevel% neq 0 (
 echo.
 echo [ERROR] Application failed to launch.
 pause
)
