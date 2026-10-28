$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
$taskConfig=Get-Content -LiteralPath (Join-Path $taskRoot 'artifacts\android-build\build-environment.json') -Raw | ConvertFrom-Json
$taskJar=Join-Path $taskConfig.sdk_root 'platforms\android-35\android.jar'
$taskOutput=Join-Path $taskRoot 'artifacts\android-build\notification-tests'
New-Item -ItemType Directory -Path $taskOutput -Force | Out-Null
$taskSources=@(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'notification-tests') -Filter '*.java' -Recurse | ForEach-Object {$_.FullName})
$taskSources+=Join-Path $PSScriptRoot 'app\src\main\java\cn\courseinbox\companion\CourseNotificationService.java'
$taskSources+=Join-Path $PSScriptRoot 'app\src\main\java\cn\courseinbox\companion\ListenerRecoveryReceiver.java'
$taskSources+=Join-Path $PSScriptRoot 'app\src\main\java\cn\courseinbox\companion\ListenerRecoverySchedule.java'
$taskSources+=Join-Path $PSScriptRoot 'app\src\main\java\cn\courseinbox\companion\NotificationText.java'
$taskSources+=Join-Path $PSScriptRoot 'app\src\main\java\cn\courseinbox\companion\ListenerDiagnostics.java'
& (Join-Path $taskConfig.java_home 'bin\javac.exe') -encoding UTF-8 -cp $taskJar -d $taskOutput @taskSources
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
& (Join-Path $taskConfig.java_home 'bin\java.exe') -cp "$taskOutput;$taskJar" NotificationConnectionTest
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
& (Join-Path $taskConfig.java_home 'bin\java.exe') -cp "$taskOutput;$taskJar" ListenerUpgradeRecoveryTest
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
& (Join-Path $taskConfig.java_home 'bin\java.exe') -cp "$taskOutput;$taskJar" ListenerScheduleFailureTest
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
& (Join-Path $taskConfig.java_home 'bin\java.exe') -cp "$taskOutput;$taskJar" ListenerDiagnosticsTest
exit $LASTEXITCODE
