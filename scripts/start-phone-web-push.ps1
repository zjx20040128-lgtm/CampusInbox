$ErrorActionPreference='Stop'
try {
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
Write-Host '正在启动手机后台提醒…'
$root=Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root
$directory=Join-Path $root 'artifacts\web-push'
New-Item -ItemType Directory -Force -Path $directory | Out-Null
$python=Join-Path $root '.venv\Scripts\python.exe'
Write-Host '[1/4] 检查推送组件…'
& $python -c 'import pywebpush' 2>$null
if($LASTEXITCODE -ne 0){& $python -m pip install -r requirements-web-push.txt;if($LASTEXITCODE -ne 0){throw 'Web Push dependencies could not be installed'}}
$headers=@{Authorization=('Bearer '+(Get-Content -LiteralPath data/access-token.txt -Raw).Trim())}
Write-Host '[2/4] 检查电脑提醒服务…'
$status=Invoke-RestMethod http://127.0.0.1:8765/api/mobile-reminders/status -Headers $headers -TimeoutSec 5
if(-not $status.enabled){Invoke-RestMethod http://127.0.0.1:8765/api/mobile-reminders/settings -Method Post -Headers $headers -ContentType application/json -Body '{"enabled":true}' | Out-Null}
$binary=Join-Path $directory 'cloudflared.exe'
if(-not(Test-Path -LiteralPath $binary)){
    Write-Host '[3/4] 下载并校验 HTTPS 隧道组件，首次启动可能较慢…'
    try{
        $release=Invoke-RestMethod 'https://api.github.com/repos/cloudflare/cloudflared/releases/latest' -TimeoutSec 30
        $asset=$release.assets | Where-Object name -eq 'cloudflared-windows-amd64.exe' | Select-Object -First 1
    }catch{
        $asset=[pscustomobject]@{digest='sha256:76b2805253d0d6ffacb092a7acfbee99e7af6917835c0c5410e23f3ef5052da2';browser_download_url='https://github.com/cloudflare/cloudflared/releases/download/2026.10.3/cloudflared-windows-amd64.exe'}
    }
    if(-not $asset -or $asset.digest -notmatch '^sha256:[a-f0-9]{64}$'){throw 'Official release SHA256 is unavailable; refusing an unchecked binary'}
    $temporary=Join-Path $directory 'cloudflared.download'
    Invoke-WebRequest $asset.browser_download_url -OutFile $temporary -TimeoutSec 120
    if((Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash.ToLower() -ne $asset.digest.Substring(7)){throw 'Cloudflared checksum mismatch'}
    Move-Item -LiteralPath $temporary -Destination $binary
}
Write-Host '[3/4] HTTPS 隧道组件已就绪。'
function Test-PhoneHTTPS($address){
    $result=& $python (Join-Path $PSScriptRoot 'check-phone-https.py') $address $status.server_id
    return ($result | ConvertFrom-Json).ok
}
$stateFile=Join-Path $directory 'tunnel.json'
if(Test-Path -LiteralPath $stateFile){
    $old=Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
    $existing=Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$old.pid)"
    if($existing.ExecutablePath -eq $binary -and $existing.CommandLine.Contains('127.0.0.1:8766')){
        if(Test-PhoneHTTPS $old.origin){Write-Output $old.origin;exit 0}
        Write-Host '原 HTTPS 隧道已失联，正在重新建立连接…'
        Stop-Process -Id $existing.ProcessId
        $originFile=Join-Path $root 'data\phone-public-origin.json'
        if(Test-Path -LiteralPath $originFile){
            $saved=Get-Content -LiteralPath $originFile -Raw | ConvertFrom-Json
            if($saved.origin -eq $old.origin){Remove-Item -LiteralPath $originFile}
        }
    }
}
$log=Join-Path $directory ('tunnel-'+(Get-Date -Format yyyyMMdd-HHmmss)+'.log')
$process=Start-Process -FilePath $binary -ArgumentList @('tunnel','--url','http://127.0.0.1:8766','--no-autoupdate','--protocol','auto','--logfile',$log) -WindowStyle Hidden -PassThru
Write-Host '[4/4] 正在连接 HTTPS 隧道，最多等待约 45 秒…'
$origin=$null
for($i=0;$i -lt 90;$i++){
    if($i -gt 0 -and $i % 10 -eq 0){Write-Host ('仍在连接网络… 已等待约 '+($i/2)+' 秒')}
    Start-Sleep -Milliseconds 500
    if(Test-Path -LiteralPath $log){$raw=Get-Content -LiteralPath $log -Raw;if($raw -match 'https://[a-z0-9-]+\.trycloudflare\.com'){$origin=$Matches[0]};if($origin -and $raw.Contains('Registered tunnel connection')){break}}
    if($process.HasExited){break}
}
if(-not $origin -or -not $raw.Contains('Registered tunnel connection')){
    if(-not $process.HasExited){Stop-Process -Id $process.Id}
    throw 'HTTPS 隧道连接失败，尚未生成可用地址。现有局域网提醒不受影响。'
}
$config=Join-Path $root 'data\phone-public-origin.json'
$oldConfig=if(Test-Path -LiteralPath $config){Get-Content -LiteralPath $config -Raw}else{$null}
@{origin=$origin}|ConvertTo-Json|Set-Content -LiteralPath $config -Encoding UTF8
try{
    if(-not (Test-PhoneHTTPS $origin)){throw 'Wrong or unreachable HTTPS service'}
}catch{
    if($null -ne $oldConfig){[IO.File]::WriteAllText($config,$oldConfig)}else{Remove-Item -LiteralPath $config}
    if(-not $process.HasExited){Stop-Process -Id $process.Id}
    throw 'HTTPS health check failed; no address published'
}
@{origin=$origin;pid=$process.Id;log=$log}|ConvertTo-Json|Set-Content -LiteralPath $stateFile -Encoding UTF8
Write-Output ('HTTPS phone address: '+$origin+'/')
Write-Output 'Pair on this address, then tap Enable background reminders and allow notifications.'
Write-Output 'This test address changes when the tunnel restarts. A stable HTTPS domain is needed for long-term subscriptions.'
} catch {
    Write-Host ('启动失败：'+$_.Exception.Message) -ForegroundColor Red
    Write-Host '如果提示隧道连接失败，请检查当前网络或代理；不需要重新登录学习通。'
    if($log){Write-Host ('诊断日志：'+$log)}
    exit 1
}
