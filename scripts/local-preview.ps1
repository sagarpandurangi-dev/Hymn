param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "status", "restart", "stop", "self-test")]
    [string]$Command = "status"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$RuntimeDir = Join-Path $RepoRoot ".hymn-runtime"
$StatePath = Join-Path $RuntimeDir "preview-state.json"
$WorkerPath = Join-Path $PSScriptRoot "local-preview-worker.ps1"
$PowerShellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$BrowserUrl = "http://localhost:8081"
$BackendUrl = "http://127.0.0.1:8001"

function Get-CurrentBranch {
    $gitMarker = Join-Path $RepoRoot ".git"
    if (Test-Path -LiteralPath $gitMarker -PathType Container) {
        $gitDirectory = $gitMarker
    } elseif (Test-Path -LiteralPath $gitMarker -PathType Leaf) {
        $pointer = (Get-Content -Raw -LiteralPath $gitMarker).Trim()
        if ($pointer -notmatch '^gitdir:\s*(.+)$') {
            throw "The repository .git pointer is invalid."
        }
        $gitDirectory = $matches[1]
        if (-not [IO.Path]::IsPathRooted($gitDirectory)) {
            $gitDirectory = Join-Path $RepoRoot $gitDirectory
        }
    } else {
        throw "This folder is not a Git working tree."
    }

    $headPath = Join-Path $gitDirectory "HEAD"
    if (-not (Test-Path -LiteralPath $headPath)) {
        throw "The repository HEAD file is missing."
    }
    $head = (Get-Content -Raw -LiteralPath $headPath).Trim()
    if ($head -match '^ref:\s+refs/heads/(.+)$') {
        return $matches[1]
    }
    if ($head -match '^[0-9a-fA-F]{40}$') {
        return "detached@$($head.Substring(0, 8))"
    }
    throw "Could not determine the current Git branch."
}

function Read-PreviewState {
    if (-not (Test-Path -LiteralPath $StatePath)) {
        return $null
    }
    try {
        return Get-Content -Raw -LiteralPath $StatePath | ConvertFrom-Json
    } catch {
        Write-Warning "The preview state file is unreadable and will be replaced. No process was stopped."
        Remove-Item -LiteralPath $StatePath -Force
        return $null
    }
}

function Write-PreviewState($State) {
    New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null
    $State | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $StatePath -Encoding UTF8
}

function Get-ProcessCommandLine([int]$ProcessId) {
    try {
        return (Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction Stop).CommandLine
    } catch {
        return $null
    }
}

function Get-ManagedEntryStatus($Entry, [string]$Role) {
    if ($null -eq $Entry -or -not $Entry.pid) {
        return "stopped"
    }
    $process = Get-Process -Id ([int]$Entry.pid) -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return "stale"
    }
    if ($Entry.start_time_utc) {
        $expected = [DateTime]::Parse($Entry.start_time_utc).ToUniversalTime()
        $actual = $process.StartTime.ToUniversalTime()
        if ([Math]::Abs(($actual - $expected).TotalSeconds) -gt 2) {
            return "unowned"
        }
    }
    $commandLine = Get-ProcessCommandLine ([int]$Entry.pid)
    if (
        -not $commandLine -or
        -not $commandLine.Contains($WorkerPath) -or
        -not $commandLine.Contains("-Role $Role") -or
        -not $commandLine.Contains($RepoRoot)
    ) {
        return "unowned"
    }
    return "running"
}

function Get-ListenerPid([int]$Port) {
    foreach ($line in (& netstat -ano -p tcp)) {
        if ($line -match "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$") {
            return [int]$matches[1]
        }
    }
    return $null
}

function Stop-ProcessTree([int]$ProcessId) {
    & cmd.exe /d /c "taskkill.exe /PID $ProcessId /T >nul 2>nul"
    Start-Sleep -Milliseconds 750
    if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
        & cmd.exe /d /c "taskkill.exe /PID $ProcessId /T /F >nul 2>nul"
    }
}

function Stop-ManagedEntry($Entry, [string]$Role) {
    $status = Get-ManagedEntryStatus $Entry $Role
    switch ($status) {
        "running" {
            Write-Host "Stopping Hymn $Role..."
            Stop-ProcessTree ([int]$Entry.pid)
        }
        "unowned" {
            Write-Warning "Saved $Role PID $($Entry.pid) belongs to another process. It was not stopped."
        }
        "stale" {
            Write-Host "Discarding stale $Role PID $($Entry.pid)."
        }
    }
}

function Stop-StaleHymnListener([int]$Port, [string]$Role) {
    $listenerPid = Get-ListenerPid $Port
    if ($null -eq $listenerPid) {
        return
    }
    $commandLine = Get-ProcessCommandLine $listenerPid
    $isExactRepo = $commandLine -and $commandLine.Contains($RepoRoot)
    $isHymnRole = if ($Role -eq "backend") {
        $commandLine -and $commandLine.Contains("uvicorn") -and $commandLine.Contains("--port 8001")
    } else {
        $commandLine -and $commandLine.Contains("expo") -and $commandLine.Contains("start --web")
    }
    if ($isExactRepo -and $isHymnRole) {
        Write-Host "Stopping stale Hymn $Role listener on port $Port..."
        Stop-ProcessTree $listenerPid
        Start-Sleep -Milliseconds 750
        return
    }
    throw "Port $Port is used by an unrelated process (PID $listenerPid). Hymn did not stop it."
}

function Get-MongoStatus {
    try {
        $health = (& docker inspect --format "{{.State.Health.Status}}" hymn-local-mongodb 2>$null).Trim()
        if ($LASTEXITCODE -eq 0 -and $health) {
            return $health
        }
    } catch {
        return "stopped"
    }
    return "stopped"
}

function Ensure-MongoReady {
    Write-Host "Starting local MongoDB..."
    & docker compose -f (Join-Path $RepoRoot "compose.yaml") up -d --wait mongodb
    if ($LASTEXITCODE -ne 0) {
        throw "MongoDB could not start. Make sure Docker Desktop is running."
    }
    if ((Get-MongoStatus) -ne "healthy") {
        throw "MongoDB started but did not become healthy."
    }
    Write-Host "MongoDB: healthy on 127.0.0.1:27017"
}

function Start-Worker([string]$Role, [switch]$ClearCache) {
    New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null
    $stdout = Join-Path $RuntimeDir "$Role.out.log"
    $stderr = Join-Path $RuntimeDir "$Role.err.log"
    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$WorkerPath`"",
        "-Role", $Role,
        "-RepoRoot", "`"$RepoRoot`""
    )
    if ($ClearCache) {
        $arguments += "-ClearCache"
    }
    $startArguments = @{
        FilePath = $PowerShellExe
        ArgumentList = $arguments
        WorkingDirectory = $RepoRoot
        WindowStyle = "Hidden"
        RedirectStandardOutput = $stdout
        RedirectStandardError = $stderr
        PassThru = $true
    }
    try {
        $process = Start-Process @startArguments
    } catch {
        if ($_.Exception.Message -notmatch "already been added.*Path") {
            throw
        }
        # Some task runners provide duplicate PATH/Path entries. Remove only
        # the duplicate in this helper process, then retry the same safe launch.
        [Environment]::SetEnvironmentVariable("Path", $null, "Process")
        $process = Start-Process @startArguments
    }
    Start-Sleep -Milliseconds 300
    return [pscustomobject]@{
        pid = $process.Id
        start_time_utc = $process.StartTime.ToUniversalTime().ToString("o")
        stdout = ".hymn-runtime\$Role.out.log"
        stderr = ".hymn-runtime\$Role.err.log"
    }
}

function Show-LogTail([string]$Role) {
    foreach ($suffix in @("err", "out")) {
        $path = Join-Path $RuntimeDir "$Role.$suffix.log"
        if (Test-Path -LiteralPath $path) {
            Write-Host ""
            Write-Host "Last $Role $suffix messages:"
            Get-Content -LiteralPath $path -Tail 30
        }
    }
}

function Test-BackendReady([int]$TimeoutSeconds = 5) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "$BackendUrl/api/" -TimeoutSec $TimeoutSeconds
        return $response.StatusCode -eq 200 -and $response.Content -match "Hymn API"
    } catch {
        return $false
    }
}

function Wait-BackendReady([int]$TimeoutSeconds = 45) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if (Test-BackendReady 2) {
            Write-Host "Backend: ready on 127.0.0.1:8001"
            return
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    Show-LogTail "backend"
    throw "Backend did not become ready within $TimeoutSeconds seconds."
}

function Get-FrontendHtml([int]$TimeoutSeconds = 10) {
    return Invoke-WebRequest -UseBasicParsing -Uri $BrowserUrl -TimeoutSec $TimeoutSeconds
}

function Test-FrontendReady([int]$TimeoutSeconds = 5) {
    try {
        $response = Get-FrontendHtml $TimeoutSeconds
        return $response.StatusCode -eq 200 -and $response.Content -match "entry\.bundle"
    } catch {
        return $false
    }
}

function Wait-FrontendReady([int]$TimeoutSeconds = 180) {
    $deadline = (Get-Date).AddSeconds(60)
    $html = $null
    do {
        try {
            $html = Get-FrontendHtml 5
        } catch {
            $html = $null
        }
        if ($html -and $html.StatusCode -eq 200 -and $html.Content -match "entry\.bundle") {
            break
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    if (-not $html) {
        Show-LogTail "frontend"
        throw "Frontend HTML did not become ready within 60 seconds."
    }
    if ($html.Content -notmatch '<script[^>]+src="([^"]+entry\.bundle[^"]*)"') {
        Show-LogTail "frontend"
        throw "Frontend HTML did not contain the Expo bundle URL."
    }
    $bundlePath = [Net.WebUtility]::HtmlDecode($matches[1])
    $bundleUri = [Uri]::new([Uri]$BrowserUrl, $bundlePath)
    try {
        $bundle = Invoke-WebRequest -UseBasicParsing -Uri $bundleUri.AbsoluteUri -TimeoutSec $TimeoutSeconds
    } catch {
        Show-LogTail "frontend"
        throw "Expo did not produce a usable web bundle within $TimeoutSeconds seconds: $($_.Exception.Message)"
    }
    if (
        $bundle.StatusCode -ne 200 -or
        $bundle.RawContentLength -lt 100000 -or
        $bundle.Content -notmatch [Regex]::Escape($BackendUrl)
    ) {
        Show-LogTail "frontend"
        throw "Expo returned an incomplete bundle or a bundle without the local backend URL."
    }
    Write-Host "Frontend: HTML and bundle ready"
}

function Stop-Preview([switch]$StopMongo) {
    $state = Read-PreviewState
    if ($state) {
        Stop-ManagedEntry $state.frontend "frontend"
        Stop-ManagedEntry $state.backend "backend"
    } else {
        Write-Host "No managed Hymn preview processes are recorded."
    }
    if (Test-Path -LiteralPath $StatePath) {
        Remove-Item -LiteralPath $StatePath -Force
    }
    if ($StopMongo) {
        Write-Host "Stopping local MongoDB (data is preserved)..."
        & docker compose -f (Join-Path $RepoRoot "compose.yaml") stop mongodb
        if ($LASTEXITCODE -ne 0) {
            throw "MongoDB could not be stopped cleanly."
        }
    }
}

function Show-PreviewStatus {
    $state = Read-PreviewState
    $branch = Get-CurrentBranch
    $mongo = Get-MongoStatus
    $backendStatus = if ($state) { Get-ManagedEntryStatus $state.backend "backend" } else { "stopped" }
    $frontendStatus = if ($state) { Get-ManagedEntryStatus $state.frontend "frontend" } else { "stopped" }
    $backendReady = $backendStatus -eq "running" -and (Test-BackendReady)
    $frontendReady = $frontendStatus -eq "running" -and (Test-FrontendReady)
    $branchStatus = if ($state -and $state.branch -ne $branch) {
        "mismatch (started on $($state.branch), current $branch)"
    } else {
        $branch
    }

    Write-Host "Branch:   $branchStatus"
    Write-Host "MongoDB:  $mongo"
    Write-Host "Backend:  $backendStatus$(if ($backendReady) { ' and responding' } elseif ($backendStatus -eq 'running') { ' but not responding' })"
    Write-Host "Frontend: $frontendStatus$(if ($frontendReady) { ' and responding' } elseif ($frontendStatus -eq 'running') { ' but not responding' })"
    Write-Host "Logs:     .hymn-runtime\"
    if ($mongo -eq "healthy" -and $backendReady -and $frontendReady -and $branchStatus -eq $branch) {
        Write-Host ""
        Write-Host "Hymn is ready: $BrowserUrl"
        return $true
    }
    Write-Host ""
    Write-Host "Hymn is not fully ready. Run: .\scripts\local.cmd restart"
    return $false
}

function Start-Preview {
    $branch = Get-CurrentBranch
    $existing = Read-PreviewState
    if ($existing) {
        $sameBranch = $existing.branch -eq $branch
        $backendRunning = (Get-ManagedEntryStatus $existing.backend "backend") -eq "running"
        $frontendRunning = (Get-ManagedEntryStatus $existing.frontend "frontend") -eq "running"
        if ($sameBranch -and $backendRunning -and $frontendRunning -and (Test-BackendReady) -and (Test-FrontendReady)) {
            Write-Host "Hymn is already ready: $BrowserUrl"
            return
        }
        Stop-Preview
    }

    Stop-StaleHymnListener 8001 "backend"
    Stop-StaleHymnListener 8081 "frontend"
    Ensure-MongoReady

    $state = [pscustomobject]@{
        version = 1
        repo_root = $RepoRoot
        branch = $branch
        started_at_utc = [DateTime]::UtcNow.ToString("o")
        backend = $null
        frontend = $null
    }

    Write-Host "Starting local backend..."
    $state.backend = Start-Worker "backend"
    Write-PreviewState $state
    try {
        Wait-BackendReady

        Write-Host "Starting local web preview..."
        $state.frontend = Start-Worker "frontend"
        Write-PreviewState $state
        try {
            Wait-FrontendReady
        } catch {
            Write-Warning "The first Expo bundle attempt failed. Retrying once with a clean Metro cache."
            Stop-ManagedEntry $state.frontend "frontend"
            Stop-StaleHymnListener 8081 "frontend"
            $state.frontend = Start-Worker "frontend" -ClearCache
            Write-PreviewState $state
            Wait-FrontendReady
        }
    } catch {
        $failureMessage = $_.Exception.Message
        Show-LogTail "backend"
        Show-LogTail "frontend"
        Write-Warning "Preview startup failed; stopping only the managed partial preview."
        try {
            Stop-Preview
        } catch {
            Write-Warning "Partial preview cleanup also reported: $($_.Exception.Message)"
        }
        throw $failureMessage
    }

    Write-Host ""
    Write-Host "Hymn is ready."
    Write-Host "Open exactly: $BrowserUrl"
    Write-Host "If that page was already open, press Ctrl+Shift+R once."
}

function Invoke-SelfTest {
    $missing = [pscustomobject]@{
        pid = 2147483000
        start_time_utc = [DateTime]::UtcNow.ToString("o")
    }
    if ((Get-ManagedEntryStatus $missing "backend") -ne "stale") {
        throw "Stale PID test failed."
    }
    $current = Get-Process -Id $PID
    $unrelated = [pscustomobject]@{
        pid = $PID
        start_time_utc = $current.StartTime.ToUniversalTime().ToString("o")
    }
    if ((Get-ManagedEntryStatus $unrelated "backend") -ne "unowned") {
        throw "Unrelated PID protection test failed."
    }
    if ($BrowserUrl -ne "http://localhost:8081" -or $BackendUrl -ne "http://127.0.0.1:8001") {
        throw "Canonical URL test failed."
    }
    if (-not (Get-CurrentBranch)) {
        throw "Git HEAD branch detection test failed."
    }
    Write-Host "Local preview safety self-test passed."
}

Set-Location -LiteralPath $RepoRoot
switch ($Command) {
    "start" { Start-Preview }
    "status" { [void](Show-PreviewStatus) }
    "restart" {
        Stop-Preview
        Start-Preview
    }
    "stop" { Stop-Preview -StopMongo }
    "self-test" { Invoke-SelfTest }
}
