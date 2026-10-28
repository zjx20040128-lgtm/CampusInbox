function Resolve-CIPython {
    $candidates = @()
    if ($env:CI_PYTHON) { $candidates += $env:CI_PYTHON }
    $candidates += (Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe')
    $candidates += (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe')
    $systemPython = Get-Command python -ErrorAction SilentlyContinue
    if ($systemPython) { $candidates += $systemPython.Source }
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        & $candidate -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) { return (Resolve-Path -LiteralPath $candidate).Path }
    }
    throw 'Python 3.10+ not found. Install Python or set CI_PYTHON to its executable path.'
}
