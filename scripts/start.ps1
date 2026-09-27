[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [ValidateRange(10, 600)]
    [int]$TimeoutSeconds = 120,
    [string]$AppUrl = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path

function Test-DockerEngine {
    # Windows PowerShell превращает stderr native-команды в terminating error при Stop.
    # Недоступный engine здесь является ожидаемым состоянием: ниже мы запускаем Docker Desktop.
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "SilentlyContinue"
        & docker info *> $null
        return $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $previousPreference
    }
}

Push-Location -LiteralPath $repoRoot
try {
    $envFile = Join-Path $repoRoot ".env"
    if (-not (Test-Path -LiteralPath $envFile)) {
        $exampleFile = Join-Path $repoRoot ".env.example"
        if (-not (Test-Path -LiteralPath $exampleFile -PathType Leaf)) {
            throw "Missing .env.example in $repoRoot."
        }
        Copy-Item -LiteralPath $exampleFile -Destination $envFile
        Write-Host "Created .env from .env.example."
    }

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker is not installed or is not in PATH. Install Docker Desktop and run this script again."
    }

    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose v2 is unavailable. Install or update Docker Desktop."
    }

    if (-not (Test-DockerEngine)) {
        if ($env:OS -eq "Windows_NT") {
            Write-Host "Docker Engine is unavailable; starting Docker Desktop..."
            $dockerDesktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
            if (Test-Path -LiteralPath $dockerDesktop -PathType Leaf) {
                Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
            } else {
                # Fallback for non-standard installations. Do not wait on the CLI plugin:
                # some Docker Desktop versions keep `docker desktop start` attached indefinitely.
                Start-Process -FilePath (Get-Command docker).Source `
                    -ArgumentList @("desktop", "start") -WindowStyle Hidden
            }

            $dockerDeadline = (Get-Date).AddSeconds(120)
            while ((Get-Date) -lt $dockerDeadline -and -not (Test-DockerEngine)) {
                Start-Sleep -Seconds 2
            }
        }

        if (-not (Test-DockerEngine)) {
            throw "Docker Engine did not become ready. Start Docker Desktop, wait for it to finish loading, and retry."
        }
    }

    Write-Host "Building and starting Provodnik 400..."
    & docker compose up --build --detach
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose could not start the application. Review the error above."
    }

    if (-not $AppUrl) {
        $published = (& docker compose port app 8000 2>$null | Select-Object -First 1)
        if ($published -and $published -match ":(?<port>[0-9]+)$") {
            $AppUrl = "http://localhost:$($Matches.port)"
        } else {
            $AppUrl = "http://localhost:8000"
        }
    }
    $AppUrl = $AppUrl.TrimEnd("/")
    $readyUrl = "$AppUrl/api/health/ready"
    $readyDeadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $ready = $false

    Write-Host "Waiting for $readyUrl ..."
    while ((Get-Date) -lt $readyDeadline) {
        try {
            $health = Invoke-RestMethod -Uri $readyUrl -TimeoutSec 3
            if ($health.status -eq "ready") {
                $ready = $true
                break
            }
        } catch {
            # The service is still building its database or loading content.
        }
        Start-Sleep -Seconds 2
    }

    if (-not $ready) {
        & docker compose ps
        throw "The application did not become ready within $TimeoutSeconds seconds. Inspect it with: docker compose logs --tail=100 app"
    }

    Write-Host "Provodnik 400 is ready: $AppUrl"
    if (-not $NoBrowser) {
        try {
            Start-Process $AppUrl
        } catch {
            Write-Warning "The browser could not be opened automatically. Open $AppUrl manually."
        }
    }
} finally {
    Pop-Location
}
