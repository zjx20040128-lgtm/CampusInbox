[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$env:PYTHONIOENCODING='utf-8'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$OutputEncoding=[Console]::OutputEncoding
$taskRoot=Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'find-python.ps1')
$taskBasePython=Resolve-CIPython
$taskVenv=Join-Path $taskRoot '.venv'
$taskPython=Join-Path $taskVenv 'Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    & $taskBasePython -m venv $taskVenv
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create project Python environment.' }
}
& $taskPython -m pip install --disable-pip-version-check -r (Join-Path $taskRoot 'requirements-mobile.txt')
if ($LASTEXITCODE -ne 0) { throw 'Cannot install optional discovery dependencies; manual connection still works.' }
& $taskPython -c 'import zeroconf,ifaddr;print(zeroconf.__version__)'
if ($LASTEXITCODE -ne 0) { throw 'Discovery dependency verification failed.' }
Write-Output 'Ready. Restart CourseInbox using start-lan.cmd.'
