[CmdletBinding()]
param([switch]$RunTests,[switch]$IfStale)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$build=Join-Path $PSScriptRoot '.build'
New-Item -ItemType Directory -Path $build -Force | Out-Null
$candidates=@(
  (Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'),
  (Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe')
)
$csc=$candidates|Where-Object { Test-Path -LiteralPath $_ }|Select-Object -First 1
if(-not $csc){throw 'Windows .NET Framework C# compiler was not found.'}
$refs=@('/r:System.dll','/r:System.Core.dll','/r:System.Drawing.dll','/r:System.Windows.Forms.dll','/r:System.Web.Extensions.dll')
$sources=@(Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.cs' -File|Sort-Object Name|ForEach-Object FullName)
if($RunTests){
  $tests=@(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'tests') -Filter '*.cs' -File|Sort-Object Name|ForEach-Object FullName)
  $output=Join-Path $build 'DesktopAppTests.exe'
  & $csc /nologo /codepage:65001 /target:exe /main:DesktopAppTests @refs "/out:$output" @sources @tests
  if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
  & $output
  exit $LASTEXITCODE
}
$output=Join-Path $root 'artifacts\desktop\CampusInbox-Learning-Assistant.exe'
New-Item -ItemType Directory -Path (Split-Path -Parent $output) -Force | Out-Null
if($IfStale -and (Test-Path -LiteralPath $output)){
  $built=(Get-Item -LiteralPath $output).LastWriteTimeUtc
  $inputs=@($sources)+(Join-Path $PSScriptRoot 'build.ps1')
  if(-not ($inputs|Where-Object { (Get-Item -LiteralPath $_).LastWriteTimeUtc -gt $built })){exit 0}
}
& $csc /nologo /codepage:65001 /platform:x64 /target:winexe /main:CourseInbox.Desktop.Program @refs "/out:$output" @sources
exit $LASTEXITCODE
