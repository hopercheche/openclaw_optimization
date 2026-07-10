$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python executable not found: $Python"
}

Push-Location $RepoRoot
try {
    & $Python -m agentscope_aliyuncs_cli.run_evalscope
}
finally {
    Pop-Location
}
