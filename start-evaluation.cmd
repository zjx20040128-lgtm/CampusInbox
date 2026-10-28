@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run-evaluation.ps1" %*
set "evaluation_exit=%errorlevel%"
echo.
echo Evaluation finished. Exit code: %evaluation_exit%
pause
exit /b %evaluation_exit%
