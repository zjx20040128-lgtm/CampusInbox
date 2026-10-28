@echo off
echo Starting CampusInbox background reminders...
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-phone-web-push.ps1"
pause
