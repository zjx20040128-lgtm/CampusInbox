$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
$taskConfig=Get-Content -LiteralPath (Join-Path $taskRoot 'artifacts\android-build\build-environment.json') -Raw | ConvertFrom-Json
$taskJar=Join-Path $taskConfig.sdk_root 'platforms\android-35\android.jar'
$taskOutput=Join-Path $taskRoot 'artifacts\android-build\computer-reminder-tests'
New-Item -ItemType Directory -Path $taskOutput -Force | Out-Null
$taskSources=@(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'computer-reminder-tests') -Filter '*.java' -Recurse | ForEach-Object {$_.FullName})
foreach($taskSource in @('ComputerReminderDelivery.java','ComputerReminderProtocol.java','ComputerReminderStore.java','ComputerReminderNotifications.java')){$taskSources+=Join-Path $PSScriptRoot ('app\src\main\java\cn\courseinbox\companion\'+$taskSource)}
& (Join-Path $taskConfig.java_home 'bin\javac.exe') -encoding UTF-8 -cp $taskJar -d $taskOutput @taskSources
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
& (Join-Path $taskConfig.java_home 'bin\java.exe') -cp "$taskOutput;$taskJar" cn.courseinbox.companion.ComputerReminderAndroidTest
exit $LASTEXITCODE
