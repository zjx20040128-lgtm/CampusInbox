[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
& (Join-Path $PSScriptRoot 'build.ps1') -RunTests
exit $LASTEXITCODE
