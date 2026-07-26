$ErrorActionPreference = "Stop"
$ScriptsDir = $PSScriptRoot
$targets = @(
    (Join-Path $ScriptsDir "local.ps1"),
    (Join-Path $ScriptsDir "local-preview.ps1"),
    (Join-Path $ScriptsDir "local-preview-worker.ps1"),
    $PSCommandPath
)

foreach ($target in $targets) {
    $tokens = $null
    $errors = $null
    [void][Management.Automation.Language.Parser]::ParseFile(
        $target,
        [ref]$tokens,
        [ref]$errors
    )
    if ($errors.Count -gt 0) {
        $messages = $errors | ForEach-Object { $_.Message }
        throw "PowerShell syntax failed for $target`: $($messages -join '; ')"
    }
}

& (Join-Path $ScriptsDir "local-preview.ps1") self-test
if (-not $?) {
    throw "Local preview safety self-test failed."
}

Write-Host "Local preview PowerShell checks passed."
