[CmdletBinding()]
param([switch]$Apply,[string]$InterfaceAlias='WLAN')
$ErrorActionPreference='Stop'
$env:PYTHONIOENCODING='utf-8'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$OutputEncoding=[Console]::OutputEncoding
$taskRoot=Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'find-python.ps1')
$taskPython=Resolve-CIPython
$taskBase=(& $taskPython -c 'import sys;print(sys._base_executable)').Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $taskBase -PathType Leaf)) {throw 'Python executable verification failed.'}
$taskProgram=$taskBase
$taskExpectedPrograms=@((Resolve-Path -LiteralPath $taskPython).Path,(Resolve-Path -LiteralPath $taskBase).Path)
$taskListener=Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($taskListener) {
    $taskProcess=Get-CimInstance Win32_Process -Filter ('ProcessId={0}' -f $taskListener.OwningProcess)
    if ($taskExpectedPrograms -notcontains $taskProcess.ExecutablePath -or $taskProcess.CommandLine -notlike '*course-inbox*server.py*') {throw 'Port 8765 is not owned by the expected CourseInbox Python process.'}
    $taskProgram=$taskProcess.ExecutablePath
}
$taskAdapter=Get-NetAdapter -Name $InterfaceAlias -ErrorAction Stop
if ($taskAdapter.Status -ne 'Up') {throw 'The selected Wi-Fi interface is not connected.'}
$taskRanges=@('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')
$taskDesired=@(
    @{Name='CourseInbox-Phone-LAN-TCP-8765';Display='CourseInbox phone connection (TCP 8765, local Wi-Fi)';Protocol='TCP';Port=8765;Local=$taskRanges},
    @{Name='CourseInbox-Phone-LAN-UDP-5353';Display='CourseInbox discovery (UDP 5353, local Wi-Fi)';Protocol='UDP';Port=5353;Local=@($taskRanges)+@('224.0.0.251')}
)
if (-not $Apply) {
    @{Mode='Preview';Program=$taskProgram;Interface=$InterfaceAlias;RemoteAddress='LocalSubnet';Profiles=@('Public','Private');Rules=$taskDesired} | ConvertTo-Json -Depth 5
    return
}
$taskPrincipal=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $taskPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {throw 'Run this script with Windows administrator approval to apply the two rules.'}
$taskBefore=@()
foreach ($taskItem in $taskDesired) {
    $taskExisting=Get-NetFirewallRule -Name $taskItem.Name -ErrorAction SilentlyContinue
    if ($taskExisting) {
        $taskPort=$taskExisting | Get-NetFirewallPortFilter
        $taskApp=$taskExisting | Get-NetFirewallApplicationFilter
        $taskAddress=$taskExisting | Get-NetFirewallAddressFilter
        $taskInterface=$taskExisting | Get-NetFirewallInterfaceFilter
        if ($taskExisting.Group -ne 'CourseInbox' -or $taskExisting.DisplayName -ne $taskItem.Display -or
            [string]$taskPort.Protocol -ne $taskItem.Protocol -or [string]$taskPort.LocalPort -ne [string]$taskItem.Port -or
            $taskExpectedPrograms -notcontains $taskApp.Program -or $taskAddress.RemoteAddress -notcontains 'LocalSubnet' -or $taskInterface.InterfaceAlias -notcontains $InterfaceAlias) {
            throw ('Existing rule does not match CourseInbox scope; no rules changed: '+$taskItem.Name)
        }
        $taskBefore+=@{Name=$taskExisting.Name;Program=$taskApp.Program;Local=$taskAddress.LocalAddress;Remote=$taskAddress.RemoteAddress;Profiles=[string]$taskExisting.Profile}
    }
}
$taskAfter=@()
foreach ($taskItem in $taskDesired) {
    $taskOptions=@{Name=$taskItem.Name;Enabled='True';Direction='Inbound';Action='Allow';Profile=@('Public','Private');Program=$taskProgram;
        InterfaceAlias=$InterfaceAlias;Protocol=$taskItem.Protocol;LocalPort=$taskItem.Port;LocalAddress=$taskItem.Local;RemoteAddress='LocalSubnet';EdgeTraversalPolicy='Block'}
    if (Get-NetFirewallRule -Name $taskItem.Name -ErrorAction SilentlyContinue) {Set-NetFirewallRule @taskOptions | Out-Null}
    else {New-NetFirewallRule @taskOptions -DisplayName $taskItem.Display -Group 'CourseInbox' | Out-Null}
    $taskRule=Get-NetFirewallRule -Name $taskItem.Name
    $taskAddress=$taskRule | Get-NetFirewallAddressFilter
    $taskApp=$taskRule | Get-NetFirewallApplicationFilter
    $taskPort=$taskRule | Get-NetFirewallPortFilter
    if ([string]$taskRule.Enabled -ne 'True' -or [string]$taskRule.Action -ne 'Allow' -or $taskApp.Program -ne $taskProgram -or
        $taskAddress.RemoteAddress -notcontains 'LocalSubnet' -or [string]$taskPort.LocalPort -ne [string]$taskItem.Port) {throw 'Firewall rule verification failed.'}
    $taskAfter+=@{Name=$taskRule.Name;Program=$taskApp.Program;Local=$taskAddress.LocalAddress;Remote=$taskAddress.RemoteAddress;Protocol=[string]$taskPort.Protocol;Port=$taskPort.LocalPort;Profiles=[string]$taskRule.Profile}
}
$taskReportDirectory=Join-Path $taskRoot 'artifacts/network'
New-Item -ItemType Directory -Force -Path $taskReportDirectory | Out-Null
@{Status='ok';Verified=$true;Interface=$InterfaceAlias;Before=$taskBefore;After=$taskAfter} | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $taskReportDirectory 'mobile-autodiscovery-firewall.json')
Write-Output 'CourseInbox TCP and discovery rules verified.'
