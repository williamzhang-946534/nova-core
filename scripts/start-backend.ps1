param(
    [string]$PythonPath
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $projectRoot "backend"
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

Set-Location $projectRoot

if (-not (Test-Path -LiteralPath $venvPython)) {
    if ([string]::IsNullOrWhiteSpace($PythonPath)) {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $python -or $python.Source -like "*\WindowsApps\python.exe") {
            throw "未找到可用的 Python 3.11+。请安装 Python 并加入 PATH，或使用 -PythonPath 指定 python.exe。"
        }
        $PythonPath = $python.Source
    }

    & $PythonPath -m venv .venv
}

& $venvPython -c "import alembic, fastapi, pydantic_settings, sqlalchemy, uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) {
    & $venvPython -m pip install -r (Join-Path $backendRoot "requirements-dev.txt")
}

$pythonPath = "$backendRoot$([System.IO.Path]::PathSeparator)$env:PYTHONPATH"
$env:PYTHONPATH = $pythonPath.TrimEnd([System.IO.Path]::PathSeparator)
& $venvPython -m nova_core.persistence init
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
& $venvPython -m nova_core.main
