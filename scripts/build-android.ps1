param([switch]$Online,[ValidateSet('arm','arm64','universal')][string]$Architecture='arm')
$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
$taskConfigPath=Join-Path $taskRoot 'artifacts\android-build\build-environment.json'
if (-not (Test-Path -LiteralPath $taskConfigPath)) { throw 'Build environment missing. Configure Android SDK 35, JDK 17 and Gradle 8.11.1 first.' }
$taskConfig=Get-Content -LiteralPath $taskConfigPath -Raw | ConvertFrom-Json
$env:JAVA_HOME=$taskConfig.java_home
$env:ANDROID_SDK_ROOT=$taskConfig.sdk_root
$env:GRADLE_USER_HOME=$taskConfig.gradle_cache
$taskSigningKey=Join-Path $taskConfig.profile '.android\debug.keystore'
if (-not (Test-Path -LiteralPath $taskSigningKey)) { throw 'Original debug signing key missing; refusing to export an incompatible upgrade.' }
$taskArchitecture=$Architecture.ToLowerInvariant()
$taskArguments=@('-p',(Join-Path $taskRoot 'android'),'--no-daemon',"-PciDebugKeystore=$taskSigningKey","-PciArchitecture=$taskArchitecture",'assembleDebug')
if (-not $Online) { $taskArguments=@('--offline')+$taskArguments }
& $taskConfig.gradle @taskArguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$taskBuiltApk=Join-Path $taskRoot 'android\app\build\outputs\apk\debug\app-debug.apk'
$taskSigner=Join-Path $taskConfig.sdk_root 'build-tools\35.0.0\apksigner.bat'
$taskSignature=& $taskSigner verify --verbose --print-certs $taskBuiltApk
if ($LASTEXITCODE -ne 0) { throw 'APK signature verification failed.' }
if (($taskSignature -join "`n") -notmatch '9320aa55a9957826a0bd4df0263f72e03730d35f9bcaf9ad794d562406979177') { throw 'APK certificate differs from the existing 0.2.5 app; export cancelled.' }
Write-Output $taskSignature
$taskBadging=& (Join-Path $taskConfig.sdk_root 'build-tools\35.0.0\aapt.exe') dump badging $taskBuiltApk
if ($LASTEXITCODE -ne 0) { throw 'APK metadata verification failed.' }
$taskNativeLine=($taskBadging | Where-Object {$_ -match '^native-code:'}) -join ' '
$taskActualAbis=@([regex]::Matches($taskNativeLine,"'([^']+)'") | ForEach-Object {$_.Groups[1].Value})
$taskExpectedAbis=switch($taskArchitecture){'arm'{@('armeabi-v7a','arm64-v8a')};'arm64'{@('arm64-v8a')};'universal'{@('armeabi-v7a','arm64-v8a','x86','x86_64')}}
if (-not $taskActualAbis.Count -or @(Compare-Object $taskExpectedAbis $taskActualAbis).Count -ne 0) { throw 'APK native libraries differ from the requested architecture; export cancelled.' }
Write-Output $taskNativeLine
$taskOutput=Join-Path $taskRoot 'artifacts\mobile'
New-Item -ItemType Directory -Path $taskOutput -Force | Out-Null
$taskSuffix=if($taskArchitecture -eq 'arm'){''}else{'-'+$taskArchitecture}
$taskPackageLine=($taskBadging | Where-Object {$_ -match '^package:'}) -join ' '
$taskVersionMatch=[regex]::Match($taskPackageLine,"versionName='([0-9]+\.[0-9]+\.[0-9]+)'")
if (-not $taskVersionMatch.Success) { throw 'APK versionName is missing or not a semantic version; export cancelled.' }
$taskApk=Join-Path $taskOutput ('campusinbox-learning-'+$taskVersionMatch.Groups[1].Value+$taskSuffix+'-debug.apk')
Copy-Item -LiteralPath $taskBuiltApk -Destination $taskApk
# Keep the existing download URLs working during the naming transition.
$taskLegacyApk=Join-Path $taskOutput ('courseinbox-learning-'+$taskVersionMatch.Groups[1].Value+$taskSuffix+'-debug.apk')
Copy-Item -LiteralPath $taskBuiltApk -Destination $taskLegacyApk
Write-Output $taskApk
