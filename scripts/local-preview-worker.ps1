param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("backend", "frontend")]
    [string]$Role,

    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,

    [switch]$ClearCache
)

$ErrorActionPreference = "Stop"
$BackendDir = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$LocalExpo = Join-Path $FrontendDir "node_modules\.bin\expo.cmd"

function Load-DotEnv([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Missing $Path. Run '.\scripts\local.cmd setup-env' first."
    }
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^\s*([^#][^=]*)=(.*)$') {
            [Environment]::SetEnvironmentVariable(
                $matches[1].Trim(),
                $matches[2].Trim(),
                "Process"
            )
        }
    }
}

function Assert-LocalUrl([string]$Url) {
    $uri = [Uri]$Url
    if ($uri.Scheme -ne "http" -or $uri.Host -notin @("127.0.0.1", "localhost")) {
        throw "Refusing non-local backend URL: $Url"
    }
}

function Assert-LocalDatabase([string]$Url, [string]$Name) {
    $uri = [Uri]$Url
    if ($uri.Host -notin @("127.0.0.1", "localhost")) {
        throw "Refusing non-local MongoDB URL: $Url"
    }
    if ($Name -ne "hymn_local") {
        throw "Refusing database '$Name'; the preview requires 'hymn_local'."
    }
}

Set-Location -LiteralPath $RepoRoot

if ($Role -eq "backend") {
    Load-DotEnv (Join-Path $BackendDir ".env")
    Assert-LocalDatabase $env:MONGO_URL $env:DB_NAME
    if ($env:HYMN_RUNTIME_MODE -ne "local") {
        throw "Refusing runtime mode '$($env:HYMN_RUNTIME_MODE)'; expected 'local'."
    }
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        throw "Python environment missing at $VenvPython"
    }
    & $VenvPython -m uvicorn server:app --app-dir $BackendDir --host 127.0.0.1 --port 8001
    exit $LASTEXITCODE
}

Load-DotEnv (Join-Path $FrontendDir ".env")
Assert-LocalUrl $env:EXPO_PUBLIC_BACKEND_URL
if (-not (Test-Path -LiteralPath $LocalExpo)) {
    throw "Frontend dependencies are missing. Run 'corepack yarn install --frozen-lockfile' inside frontend."
}

# These values are intentionally explicit so a saved environment file cannot
# split the browser origin or send the preview to another backend.
$env:EXPO_PUBLIC_BACKEND_URL = "http://127.0.0.1:8001"
$env:EXPO_OFFLINE = "1"
$arguments = @("start", "--web", "--localhost", "--port", "8081")
if ($ClearCache) {
    $arguments += "--clear"
}

Set-Location -LiteralPath $FrontendDir
& $LocalExpo @arguments
exit $LASTEXITCODE
