param(
    [string]$PythonPath = "",
    [string]$PnpmPath = "pnpm"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
}

if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python not found: $PythonPath"
}

Push-Location (Join-Path $ProjectRoot "backend")
try {
    & $PythonPath -m ruff check .
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    & $PythonPath -m ruff format --check .
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    & $PythonPath -m pytest -q
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    & $PythonPath -m compileall -q arvuno_core alembic
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    & $PythonPath -m pip check
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}

Push-Location (Join-Path $ProjectRoot "frontend")
try {
    & $PnpmPath typecheck
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    & $PnpmPath format:check
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    & $PnpmPath test
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    & $PnpmPath build
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}
