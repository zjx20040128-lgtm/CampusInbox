[CmdletBinding()]
param([switch]$Apply,[string]$InterfaceAlias='WLAN')
$ErrorActionPreference='Stop'
$env:PYTHONIOENCODING='utf-8'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$OutputEncoding=[Console]::OutputEncoding
$taskRoot=Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'find-python.ps1')
$taskPython=Resolve-CIPython
$taskBase=(& $taskPython -c 'import sys;print(sys._base_executable)').Trim()
if($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $taskBase -PathType Leaf)){throw 'Cannot verify the CourseInbox Python runtime.'}
# On Windows the venv launcher starts the base interpreter, which owns the socket.
$taskLauncherProgram=(Resolve-Path -LiteralPath $taskPython).Path
$taskBaseProgram=(Resolve-Path -LiteralPath $taskBase).Path
$taskProgram=$taskBaseProgram
$taskListeners=@(Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue)
foreach($taskListener in $taskListeners){
    $taskOwner=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskListener.OwningProcess)"
    if(-not $taskOwner.ExecutablePath -or $taskOwner.ExecutablePath -ne $taskProgram){throw 'The phone port is owned by an unexpected executable; nothing changed.'}
}
$taskAdapter=Get-NetAdapter -Name $InterfaceAlias -ErrorAction Stop
if($taskAdapter.Status -ne 'Up'){throw 'Connect the selected Wi-Fi interface first.'}
$taskName='CourseInbox-Phone-Reminders-TCP-8766'
$taskDisplay='CourseInbox phone reminders (TCP 8766, local Wi-Fi)'
$taskScope=@{Program=$taskProgram;InterfaceAlias=$InterfaceAlias;Protocol='TCP';LocalPort=8766;LocalAddress=@('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16');RemoteAddress='LocalSubnet';Profile=@('Private','Public');EdgeTraversalPolicy='Block'}
if(-not $Apply){@{Mode='Preview';Rule=$taskName;Scope=$taskScope} | ConvertTo-Json -Depth 5;return}
$taskPrincipal=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if(-not $taskPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Administrator approval is required to apply this one scoped firewall rule.'}
$taskExisting=Get-NetFirewallRule -Name $taskName -ErrorAction SilentlyContinue
if($taskExisting){
    $taskExistingApp=$taskExisting | Get-NetFirewallApplicationFilter
    $taskExistingPort=$taskExisting | Get-NetFirewallPortFilter
    $taskExistingAddress=$taskExisting | Get-NetFirewallAddressFilter
    $taskExistingInterface=$taskExisting | Get-NetFirewallInterfaceFilter
    if($taskExisting.Group -ne 'CourseInbox' -or $taskExisting.DisplayName -ne $taskDisplay -or $taskExistingApp.Program -notin @($taskProgram,$taskLauncherProgram) -or [string]$taskExistingPort.Protocol -ne 'TCP' -or [string]$taskExistingPort.LocalPort -ne '8766' -or $taskExistingAddress.RemoteAddress -notcontains 'LocalSubnet' -or $taskExistingInterface.InterfaceAlias -notcontains $InterfaceAlias){throw 'An existing firewall rule has a different scope; nothing changed.'}
    Set-NetFirewallRule -Name $taskName -Enabled True -Direction Inbound -Action Allow @taskScope | Out-Null
}else{New-NetFirewallRule -Name $taskName -DisplayName $taskDisplay -Group CourseInbox -Enabled True -Direction Inbound -Action Allow @taskScope | Out-Null}
$taskRule=Get-NetFirewallRule -Name $taskName
$taskPort=$taskRule | Get-NetFirewallPortFilter
$taskAddress=$taskRule | Get-NetFirewallAddressFilter
if([string]$taskRule.Enabled -ne 'True' -or [string]$taskRule.Action -ne 'Allow' -or [string]$taskPort.LocalPort -ne '8766' -or $taskAddress.RemoteAddress -notcontains 'LocalSubnet'){throw 'Firewall rule verification failed.'}
$taskAppliedApp=$taskRule | Get-NetFirewallApplicationFilter
if($taskAppliedApp.Program -ne $taskProgram){throw 'Firewall rule does not match the actual CourseInbox listener executable.'}
$taskOutput=Join-Path $taskRoot 'artifacts\mobile-reminders'
New-Item -ItemType Directory -Path $taskOutput -Force | Out-Null
@{Status='ok';Rule=$taskName;Scope=$taskScope} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $taskOutput 'firewall.json') -Encoding UTF8
Write-Output 'CourseInbox phone reminder TCP 8766 rule verified.'
