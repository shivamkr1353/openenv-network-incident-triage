param(
    [Parameter(Mandatory = $true)]
    [string]$PingUrl,
    [string]$RepoDir = "."
)

$ErrorActionPreference = "Stop"

function Write-Log {
    param([string]$Message)
    $timestamp = (Get-Date).ToUniversalTime().ToString("HH:mm:ss")
    Write-Host "[$timestamp] $Message"
}

function Fail-Step {
    param(
        [string]$Step,
        [string]$Message
    )
    Write-Log "FAILED -- $Message"
    throw "Validation stopped at $Step."
}

$resolvedRepo = Resolve-Path -LiteralPath $RepoDir
$PingUrl = $PingUrl.TrimEnd("/")

Write-Host ""
Write-Host "========================================"
Write-Host "  OpenEnv Submission Validator"
Write-Host "========================================"
Write-Log "Repo:     $resolvedRepo"
Write-Log "Ping URL: $PingUrl"
Write-Host ""

Write-Log "Step 1/4: Pinging HF Space ($PingUrl/reset) ..."
if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
    Fail-Step "Step 1" "curl.exe not found"
}

try {
    $statusCode = & curl.exe -s -o NUL -w "%{http_code}" -X POST -H "Content-Type: application/json" -d "{}" "$PingUrl/reset" --max-time 30
    if ("$statusCode".Trim() -ne "200") {
        Fail-Step "Step 1" "HF Space /reset returned HTTP $statusCode"
    }
    Write-Log "PASSED -- HF Space is live and responds to /reset"
}
catch {
    $errorText = ($_ | Out-String).Trim()
    Fail-Step "Step 1" "HF Space not reachable or /reset failed. $errorText"
}

Write-Log "Step 2/4: Running docker build ..."
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail-Step "Step 2" "docker command not found"
}

$dockerfilePath = Join-Path $resolvedRepo "Dockerfile"
if (-not (Test-Path -LiteralPath $dockerfilePath)) {
    Fail-Step "Step 2" "No Dockerfile found in repo root"
}

docker build $resolvedRepo | Out-Host
if ($LASTEXITCODE -ne 0) {
    Fail-Step "Step 2" "Docker build failed"
}
Write-Log "PASSED -- Docker build succeeded"

Write-Log "Step 3/4: Running openenv validate ..."
if (-not (Get-Command openenv -ErrorAction SilentlyContinue)) {
    Fail-Step "Step 3" "openenv command not found"
}

Push-Location $resolvedRepo
try {
    openenv validate | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Fail-Step "Step 3" "openenv validate failed"
    }
}
finally {
    Pop-Location
}
Write-Log "PASSED -- openenv validate passed"

Write-Log "Step 4/4: Verifying inference stdout format ..."
Push-Location $resolvedRepo
try {
    $output = python inference.py --offline
    if ($LASTEXITCODE -ne 0) {
        Fail-Step "Step 4" "python inference.py --offline failed"
    }
}
finally {
    Pop-Location
}

$startCount = @($output | Where-Object { $_ -match '^\[START\] task=' }).Count
$stepCount = @($output | Where-Object { $_ -match '^\[STEP\] step=' }).Count
$endCount = @($output | Where-Object { $_ -match '^\[END\] success=' }).Count

if ($startCount -lt 3 -or $stepCount -lt 3 -or $endCount -lt 3) {
    $output | Out-Host
    Fail-Step "Step 4" "inference.py did not emit the expected structured logs for all tasks"
}

Write-Log "PASSED -- inference.py emits structured [START]/[STEP]/[END] logs"

Write-Host ""
Write-Host "========================================"
Write-Host "  All 4/4 checks passed!"
Write-Host "  Your submission is ready for pre-submit review."
Write-Host "========================================"
Write-Host ""
