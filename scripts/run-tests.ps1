param([switch]$Browser)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')
. (Join-Path $PSScriptRoot 'find-python.ps1')
$python = Resolve-CIPython
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONDONTWRITEBYTECODE='1'
& $python -B -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File desktop-app\run-tests.ps1
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($Browser) {
    $runtimeNode = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\node'
    $node = Join-Path $runtimeNode 'bin\node.exe'
    if (-not (Test-Path -LiteralPath $node)) { $node = (Get-Command node -ErrorAction Stop).Source }
    $modules = Join-Path $runtimeNode 'node_modules'
    if (Test-Path -LiteralPath $modules) { $env:NODE_PATH = $modules }
    $env:CI_PYTHON=$python
    & $node --test scripts\test-browser-server.cjs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $browserChecks = @(
        ,@('scripts\test-evaluation-ui.cjs')
        ,@('scripts\test-relative-extension-ui.cjs')
        ,@('scripts\test-notice-media.cjs')
        ,@('scripts\test-desktop-lifecycle.cjs')
        ,@('scripts\test-desktop-chat.cjs')
        ,@('scripts\test-checkin-cards.cjs')
        ,@('scripts\test-checkin-update-ui.cjs')
        ,@('scripts\test-web-push-browser.cjs')
        ,@('scripts\test-wechat-push-ui.cjs')
        ,@('scripts\test-live-capture.cjs')
        ,@('scripts\test-live-worker.cjs')
        ,@('scripts\test-chaoxing-tasks.cjs')
        ,@('scripts\test-task-details.cjs')
        ,@('scripts\test-deadline-references-ui.cjs')
        ,@('scripts\test-task-time-ui.cjs')
        ,@('scripts\test-assignment-content.cjs')
        ,@('scripts\test-attachment-formats.cjs')
        ,@('scripts\test-original-download.cjs')
        ,@('scripts\test-task-attachments-ui.cjs')
        ,@('scripts\test-task-recheck.cjs')
        ,@('scripts\test-platform-check-ui.cjs')
        ,@('scripts\test-desktop-inbox.cjs')
        ,@('scripts\test-sync-summary-ui.cjs')
        ,@('scripts\test-supplements-ui.cjs')
        ,@('scripts\test-message-details-ui.cjs')
        ,@('scripts\test-task-cancel-ui.cjs')
        ,@('scripts\test-identity-review.cjs')
        ,@('scripts\test-task-center-worker.cjs')
        ,@('scripts\test-checkin-verification-worker.cjs')
        ,@('scripts\test-workspace-polish.cjs')
        ,@('scripts\test-chat-import-ui.cjs')
        ,@('scripts\test-task-inventory-worker.cjs')
        ,@('scripts\test-task-inventory-ui.cjs')
        ,@('scripts\test-mobile-reminders-ui.cjs')
        ,@('scripts\test-phone-reminders.cjs')
        ,@('scripts\test-mobile-learning.cjs')
        ,@('scripts\test-mobile-login-ui.cjs')
        ,@('scripts\test-mobile-page-ui.cjs')
        ,@('scripts\test-mobile-images.cjs')
        ,@('scripts\test-desktop-scan.cjs')
        ,@('scripts\browser-check.cjs')
        ,@('scripts\course-notice-check.cjs')
        ,@('scripts\desktop-browser-check.cjs', '--chat')
    )
    foreach ($browserCheck in $browserChecks) {
        & $node @browserCheck
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    exit 0
}
