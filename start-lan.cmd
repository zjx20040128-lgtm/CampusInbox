@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" -ListenHost 0.0.0.0 %*
if errorlevel 1 pause
