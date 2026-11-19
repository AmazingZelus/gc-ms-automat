# Smoke test of the portable ZIP on Windows (run by GitHub Actions).
# Extracts the ZIP into a folder with spaces, diacritics and parentheses,
# blocks the default port, starts spustit.bat and checks that:
#   - the app starts and reports the expected version,
#   - the scientific libraries work (known-result calculation),
#   - "Export test" writes a CSV with name, version and date/time header,
#   - the server stops: (a) after the tab says goodbye, (b) via the Quit button,
#     (c) by itself when no browser connects.
param(
    [Parameter(Mandatory = $true)] [string] $ZipPath,
    [Parameter(Mandatory = $true)] [string] $ExpectedVersion
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Fail([string] $message) { Write-Host "SMOKE TEST FAILED: $message"; exit 1 }

# ---- This extracts the ZIP into a deliberately "difficult" folder name ----
$base = Join-Path $env:RUNNER_TEMP "Zkouška s mezerou (1) ěščřžýáíé"
if (Test-Path -LiteralPath $base) { Remove-Item -LiteralPath $base -Recurse -Force }
# Like Windows "Extract all": into a folder named after the ZIP (ZIP has no top folder).
$appDir = Join-Path $base ([System.IO.Path]::GetFileNameWithoutExtension($ZipPath))
Expand-Archive -LiteralPath $ZipPath -DestinationPath $appDir
$bat = Join-Path $appDir "spustit.bat"
$python = Join-Path $appDir "python\python.exe"
Write-Host "App folder: $appDir"
if (-not (Test-Path -LiteralPath $bat)) { Fail "spustit.bat missing" }

# ---- This checks the libraries with calculations whose result is known exactly ----
$check = @"
import numpy as np, scipy, scipy.stats, scipy.signal, pandas as pd, sklearn, flask, waitress
import statsmodels.api as sm
from sklearn.linear_model import LinearRegression
x = np.arange(10.0); y = 2.0 * x + 1.0                      # y = 2x + 1
slope, intercept = np.polyfit(x, y, 1)
assert abs(slope - 2) < 1e-9 and abs(intercept - 1) < 1e-9, (slope, intercept)
fit = sm.OLS(y, sm.add_constant(x)).fit()
assert np.allclose(fit.params, [1.0, 2.0])
assert np.isclose(LinearRegression().fit(x.reshape(-1, 1), y).coef_[0], 2.0)
assert np.isclose(scipy.stats.norm.cdf(0.0), 0.5)
print('libraries OK', np.__version__, scipy.__version__, pd.__version__, sklearn.__version__)
"@
& $python -c $check
if ($LASTEXITCODE -ne 0) { Fail "library check failed" }

# ---- Helper: is any python.exe from our folder still running? ----
function Get-AppProcesses {
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($appDir, [System.StringComparison]::OrdinalIgnoreCase) }
}

# ---- Helper: start spustit.bat (from another working dir) and wait for server.json ----
$serverJson = Join-Path $appDir "runtime\server.json"
$emptyInput = Join-Path $env:RUNNER_TEMP "empty-stdin.txt"
Set-Content -LiteralPath $emptyInput -Value "" -NoNewline
function Start-App([string] $label) {
    if (Test-Path -LiteralPath $serverJson) { Remove-Item -LiteralPath $serverJson }
    $out = Join-Path $env:RUNNER_TEMP "app-$label.out.txt"
    $err = Join-Path $env:RUNNER_TEMP "app-$label.err.txt"
    $proc = Start-Process -FilePath $bat -WorkingDirectory $env:RUNNER_TEMP -PassThru `
        -RedirectStandardOutput $out -RedirectStandardError $err -RedirectStandardInput $emptyInput
    $null = $proc.Handle  # keeps the exit code readable after the process ends
    for ($i = 0; $i -lt 120; $i++) {
        if (Test-Path -LiteralPath $serverJson) { break }
        if ($proc.HasExited) { Get-Content -LiteralPath $out, $err; Fail "[$label] app exited early" }
        Start-Sleep -Milliseconds 500
    }
    if (-not (Test-Path -LiteralPath $serverJson)) { Get-Content -LiteralPath $out, $err; Fail "[$label] server.json not created" }
    Start-Sleep -Milliseconds 300
    return @{ Proc = $proc; Info = (Get-Content -LiteralPath $serverJson -Raw | ConvertFrom-Json); Out = $out }
}

# ---- Helper: wait until the app process has ended ----
function Wait-Stopped($app, [string] $label, [int] $seconds) {
    if (-not $app.Proc.WaitForExit($seconds * 1000)) { Fail "[$label] app did not stop within $seconds s" }
    Start-Sleep -Seconds 1
    if (Get-AppProcesses) { Fail "[$label] python.exe still running after stop" }
    if ($app.Proc.ExitCode -ne 0) { Get-Content -LiteralPath $app.Out; Fail "[$label] exit code $($app.Proc.ExitCode)" }
    Write-Host "[$label] stopped OK"
}

$env:GCMS_NO_BROWSER = "1"

# ---- Run 1: default port is busy; version, export, then 'tab closed' ----
$blocker = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 8765)
$blocker.Start()
try {
    $app = Start-App "run1"
    $port = $app.Info.port
    $headers = @{ "X-App-Token" = $app.Info.token }
    $api = "http://127.0.0.1:$port/api"
    if ($port -eq 8765) { Fail "busy port 8765 was not avoided" }
    # This proves the "is python still running?" check can actually see our process.
    if (-not (Get-AppProcesses)) { Fail "running app process not detected (process check is broken)" }
    Write-Host "Started on fallback port $port"

    # This checks that the packaged UI files are served (and contain no internet links).
    foreach ($page in @("/", "/static/app.js", "/static/style.css")) {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$port$page" -UseBasicParsing
        if ($resp.StatusCode -ne 200) { Fail "$page returned $($resp.StatusCode)" }
        if ($resp.Content -match "https?://") { Fail "$page contains an http(s) link" }
        if (-not ($resp.Headers["Content-Security-Policy"] -match "default-src 'self'")) { Fail "$page missing CSP" }
    }

    $info = Invoke-RestMethod -Uri "$api/info" -Headers $headers
    if ($info.version -ne $ExpectedVersion) { Fail "version $($info.version) != $ExpectedVersion" }

    # This checks the token protection: no token -> 403.
    try { Invoke-RestMethod -Uri "$api/info" | Out-Null; Fail "API answered without token" }
    catch { if ($_.Exception.Response.StatusCode.value__ -ne 403) { throw } }

    $body = @{ csv_format = "intl" } | ConvertTo-Json
    $res = Invoke-RestMethod -Method Post -Uri "$api/export-test" -Headers $headers -Body $body -ContentType "application/json"
    if (-not $res.ok) { Fail "export failed" }
    $exportFile = Join-Path (Join-Path $appDir "exporty") $res.filename
    if (-not (Test-Path -LiteralPath $exportFile)) { Fail "export file not in app folder: $exportFile" }
    $lines = Get-Content -LiteralPath $exportFile -Encoding UTF8
    if ($lines[0] -ne "# app: GC-MS Automat") { Fail "header line 1: $($lines[0])" }
    if ($lines[1] -ne "# version: $ExpectedVersion") { Fail "header line 2: $($lines[1])" }
    if ($lines[2] -notmatch '^# processed_at: \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$') { Fail "header line 3: $($lines[2])" }
    if (-not ($lines -contains "3,9,1.5")) { Fail "known values missing (3,9,1.5)" }
    Write-Host "Export OK: $exportFile"

    # This simulates a browser tab that opens and then closes.
    $hb = @{ cid = "smoke-tab" } | ConvertTo-Json
    Invoke-RestMethod -Method Post -Uri "$api/heartbeat" -Headers $headers -Body $hb -ContentType "application/json" | Out-Null
    Invoke-RestMethod -Method Post -Uri "$api/closing?token=$($app.Info.token)&cid=smoke-tab" | Out-Null
    Wait-Stopped $app "run1-tab-closed" 30
}
finally { $blocker.Stop() }

# ---- Run 2: the 'Ukončit' button ----
$app = Start-App "run2"
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$($app.Info.port)/api/shutdown" -Headers @{ "X-App-Token" = $app.Info.token } | Out-Null
Wait-Stopped $app "run2-quit-button" 20

# ---- Run 3: no browser ever connects -> stops by itself ----
$env:GCMS_STARTUP_TIMEOUT = "5"
$app = Start-App "run3"
Wait-Stopped $app "run3-no-browser" 30
Remove-Item Env:GCMS_STARTUP_TIMEOUT

# ---- This checks that server.json was cleaned up ----
if (Test-Path -LiteralPath $serverJson) { Fail "runtime\server.json left behind" }
Write-Host "SMOKE TEST PASSED"
