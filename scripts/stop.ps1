[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path

Push-Location -LiteralPath $repoRoot
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker is not installed or is not in PATH."
    }

    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose v2 is unavailable. Install or update Docker Desktop."
    }

    & docker compose down --remove-orphans
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose could not stop the application. Review the error above."
    }
    Write-Host "Provodnik 400 stopped. Named data volumes were preserved."
} finally {
    Pop-Location
}
