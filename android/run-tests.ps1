$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
$taskConfig=Get-Content -LiteralPath (Join-Path $taskRoot 'artifacts\android-build\build-environment.json') -Raw | ConvertFrom-Json
$taskJava=Join-Path $taskConfig.java_home 'bin\java.exe'
$taskJavac=Join-Path $taskConfig.java_home 'bin\javac.exe'
$taskClasses=Join-Path $PSScriptRoot 'app\build\intermediates\javac\debug\compileDebugJavaWithJavac\classes'
if (-not (Test-Path -LiteralPath $taskClasses)) { throw 'Build the Android app before running protocol tests.' }
$taskSdkJar=Join-Path $taskConfig.sdk_root 'platforms\android-35\android.jar'
$taskOutput=Join-Path $taskRoot 'artifacts\android-build\protocol-tests'
New-Item -ItemType Directory -Path $taskOutput -Force | Out-Null
$taskTests=Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'protocol-tests') -Filter '*Test.java'
$taskSources=@($taskTests | ForEach-Object {$_.FullName})
$taskClasspath="$taskClasses;$taskSdkJar"
& $taskJavac -encoding UTF-8 -cp $taskClasspath -d $taskOutput @taskSources
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
foreach ($taskTest in $taskTests) {
    & $taskJava -cp "$taskOutput;$taskClasspath" $taskTest.BaseName
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'run-notification-tests.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'run-computer-reminder-tests.ps1')
exit $LASTEXITCODE
