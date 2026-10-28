param(
    [ValidateSet('rules','compare','prepare')][string]$Action='rules',
    [string[]]$Models=@(),
    [string]$Labels='',
    [int]$Limit=0
)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
. (Join-Path $PSScriptRoot 'find-python.ps1')
$python=Resolve-CIPython
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONDONTWRITEBYTECODE='1'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new()
$arguments=@('-B',(Join-Path $PSScriptRoot 'evaluate-recognition.py'))
if ($Action -eq 'prepare') {
    $workDirectory=Join-Path $root 'data/verification'
    New-Item -ItemType Directory -Path $workDirectory -Force | Out-Null
    $target=Join-Path $workDirectory ('notice-labels-workbench-'+(Get-Date -Format 'yyyyMMdd-HHmmss-ffff')+'.json')
    $arguments+=@('--prepare',$target)
    Write-Host ('Local annotation file: '+$target)
} else {
    $output=Join-Path $root ('artifacts/evaluation/'+$Action+'-'+(Get-Date -Format 'yyyyMMdd-HHmmss-ffff')+'.json')
    $arguments+=@('--mode',$Action,'--output',$output)
    Write-Host ('Report: '+$output)
}
if ($Models.Count) {$arguments+=@('--models');$arguments+=$Models}
if ($Labels) {$arguments+=@('--labels',$Labels)}
if ($Limit) {$arguments+=@('--limit',[string]$Limit)}
& $python @arguments
exit $LASTEXITCODE
