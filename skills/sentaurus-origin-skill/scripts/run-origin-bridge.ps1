[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$BridgeArgs
)

$ErrorActionPreference = 'Stop'
$skillDir = Split-Path -Parent $PSScriptRoot
$bridge = Join-Path $PSScriptRoot 'origin_bridge.py'
$candidates = New-Object System.Collections.Generic.List[string]

if ($env:SENTAURUS_ORIGIN_PYTHON) {
    $candidates.Add($env:SENTAURUS_ORIGIN_PYTHON)
}

$codexPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$candidates.Add($codexPython)

$pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
if ($pyLauncher) {
    $candidates.Add($pyLauncher.Source)
}

$systemPython = Get-Command python.exe -ErrorAction SilentlyContinue
if ($systemPython) {
    $candidates.Add($systemPython.Source)
}

$python = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not $python) {
    throw "No usable Python interpreter found. Set SENTAURUS_ORIGIN_PYTHON to a Python executable."
}

if ((Split-Path -Leaf $python) -ieq 'py.exe') {
    & $python -3 $bridge @BridgeArgs
} else {
    & $python $bridge @BridgeArgs
}
exit $LASTEXITCODE
