@echo off
setlocal
set "ROOT=%~dp0"
set "BUILD=%ROOT%desktop-app\build.ps1"
set "APP=%ROOT%artifacts\desktop\CampusInbox-Learning-Assistant.exe"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%BUILD%" -IfStale
if errorlevel 1 (
  echo CampusInbox desktop app build failed.
  if not "%CI_DESKTOP_LAUNCH_TEST%"=="1" pause
  exit /b 1
)
if "%CI_DESKTOP_LAUNCH_TEST%"=="1" exit /b 0
start "" "%APP%" %*
exit /b %ERRORLEVEL%
