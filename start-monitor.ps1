[CmdletBinding()]
param([string]$ListenHost='127.0.0.1',[int]$Port=8765)
$ErrorActionPreference='Stop'
$url="http://127.0.0.1:$Port/#sync"
try {
    $health=Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
    if ($health.status -eq 'ok') { Start-Process $url; exit 0 }
} catch {}
& (Join-Path $PSScriptRoot 'start.ps1') -ListenHost $ListenHost -Port $Port -InitialView sync
exit $LASTEXITCODE
