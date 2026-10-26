param(
    [string]$PackageManagerPath
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $projectRoot "frontend"

if (-not [string]::IsNullOrWhiteSpace($PackageManagerPath)) {
    $packageManager = $PackageManagerPath
} else {
    $npmCommand = Get-Command npm -ErrorAction SilentlyContinue
    $pnpmCommand = Get-Command pnpm -ErrorAction SilentlyContinue

    if ($null -ne $npmCommand) {
        $packageManager = $npmCommand.Source
    } elseif ($null -ne $pnpmCommand) {
        $packageManager = $pnpmCommand.Source
    } else {
        throw "npm 或 pnpm 不在 PATH 中，请先安装 Node.js，或使用 -PackageManagerPath 指定。"
    }
}

Set-Location $frontendRoot

if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot "node_modules"))) {
    & $packageManager install
}

& $packageManager run dev
