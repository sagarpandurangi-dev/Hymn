param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "status", "restart", "stop", "setup-env", "db-start", "db-stop", "db-status", "backend", "backend-test", "frontend", "test", "lint", "reset-db")]
    [string]$Command = "db-status"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$LocalExpo = Join-Path $FrontendDir "node_modules\.bin\expo.cmd"
$PreviewHelper = Join-Path $PSScriptRoot "local-preview.ps1"

function Assert-LocalUrl([string]$Url) {
    $uri = [Uri]$Url
    if ($uri.Scheme -ne "http" -or $uri.Host -notin @("127.0.0.1", "localhost")) {
        throw "Refusing non-local backend URL: $Url"
    }
}

function Assert-LocalDatabase([string]$Url, [string]$Name, [string]$ExpectedName) {
    $uri = [Uri]$Url
    if ($uri.Host -notin @("127.0.0.1", "localhost")) {
        throw "Refusing non-local MongoDB URL: $Url"
    }
    if ($Name -ne $ExpectedName) {
        throw "Refusing database '$Name'; expected '$ExpectedName'."
    }
}

function Assert-RuntimeMode([string]$Mode, [string]$ExpectedMode) {
    if ($Mode -ne $ExpectedMode) {
        throw "Refusing runtime mode '$Mode'; expected '$ExpectedMode'."
    }
}

function Load-DotEnv([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Missing $Path. Run '.\scripts\local.ps1 setup-env' first."
    }
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^\s*([^#][^=]*)=(.*)$') {
            [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
        }
    }
}

Push-Location $RepoRoot
try {
    switch ($Command) {
        { $_ -in @("start", "status", "restart", "stop") } {
            & $PreviewHelper $Command
            if (-not $?) {
                exit 1
            }
        }
        "setup-env" {
            foreach ($pair in @(
                @("backend\.env.example", "backend\.env"),
                @("backend\.env.test.example", "backend\.env.test"),
                @("frontend\.env.example", "frontend\.env")
            )) {
                if (Test-Path -LiteralPath $pair[1]) {
                    Write-Host "$($pair[1]) already exists; left unchanged."
                } else {
                    Copy-Item -LiteralPath $pair[0] -Destination $pair[1]
                    Write-Host "Created $($pair[1]) from its safe example."
                }
            }
        }
        "db-start" { docker compose up -d --wait mongodb }
        "db-stop" { docker compose stop mongodb }
        "db-status" { docker compose ps }
        "backend" {
            Load-DotEnv (Join-Path $BackendDir ".env")
            Assert-LocalDatabase $env:MONGO_URL $env:DB_NAME "hymn_local"
            Assert-RuntimeMode $env:HYMN_RUNTIME_MODE "local"
            & $VenvPython -m uvicorn server:app --app-dir $BackendDir --host 127.0.0.1 --port 8001
        }
        "backend-test" {
            Load-DotEnv (Join-Path $BackendDir ".env.test")
            Assert-LocalUrl $env:EXPO_PUBLIC_BACKEND_URL
            Assert-LocalDatabase $env:MONGO_URL $env:DB_NAME "hymn_test"
            Assert-RuntimeMode $env:HYMN_RUNTIME_MODE "test"
            & $VenvPython -m uvicorn server:app --app-dir $BackendDir --host 127.0.0.1 --port 8001
        }
        "frontend" {
            Load-DotEnv (Join-Path $FrontendDir ".env")
            Assert-LocalUrl $env:EXPO_PUBLIC_BACKEND_URL
            if (-not (Test-Path -LiteralPath $LocalExpo)) {
                throw "Frontend dependencies are missing. Run 'corepack yarn install --frozen-lockfile' inside frontend."
            }
            $env:EXPO_PUBLIC_BACKEND_URL = "http://127.0.0.1:8001"
            $env:EXPO_OFFLINE = "1"
            Push-Location $FrontendDir
            try { & $LocalExpo start --web --localhost --port 8081 } finally { Pop-Location }
        }
        "test" {
            Load-DotEnv (Join-Path $BackendDir ".env.test")
            Assert-LocalUrl $env:EXPO_PUBLIC_BACKEND_URL
            Assert-LocalDatabase $env:MONGO_URL $env:DB_NAME "hymn_test"
            Assert-RuntimeMode $env:HYMN_RUNTIME_MODE "test"
            $env:PYTHONDONTWRITEBYTECODE = "1"
            & $VenvPython -m pytest backend\tests -p no:cacheprovider
        }
        "lint" {
            if (-not (Test-Path -LiteralPath $LocalExpo)) {
                throw "Frontend dependencies are missing. Run 'corepack yarn install --frozen-lockfile' inside frontend."
            }
            Push-Location $FrontendDir
            try { & $LocalExpo lint } finally { Pop-Location }
        }
        "reset-db" {
            Write-Warning "This deletes only Docker volume 'hymn-local-mongodb-data'."
            $answer = Read-Host "Type RESET LOCAL HYMN to continue"
            if ($answer -ne "RESET LOCAL HYMN") { throw "Reset cancelled." }
            docker compose down --volumes
            docker compose up -d --wait mongodb
        }
    }
} finally {
    Pop-Location
}
