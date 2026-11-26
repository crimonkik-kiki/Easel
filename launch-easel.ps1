param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$url = 'http://localhost:7860/'
$mutex = New-Object System.Threading.Mutex($false, 'Local\EaselWorkbenchLauncher')
$locked = $false
function Test-EaselReady {
    try {
        $response = Invoke-WebRequest -Uri 'http://127.0.0.1:7860/api/settings/bootstrap' -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch { return $false }
}
try {
    $locked = $mutex.WaitOne(120000)
    if (-not $locked) { throw 'Another launch is still in progress. Please try again shortly.' }
    if (-not (Test-EaselReady)) {
        $logDir = Join-Path $PSScriptRoot 'outputs\_install'
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
        $stdout = Join-Path $logDir "launcher-$stamp.log"
        $stderr = Join-Path $logDir "launcher-$stamp.err.log"
        $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $startScript = Join-Path $PSScriptRoot 'start-easel.ps1'
        $process = Start-Process -FilePath $powershell -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"{0}"' -f $startScript)) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
        $deadline = (Get-Date).AddSeconds(120)
        while (-not (Test-EaselReady)) {
            $process.Refresh()
            if ($process.HasExited) { throw "Easel could not start. See log: $stderr" }
            if ((Get-Date) -gt $deadline) { throw "Startup timed out. See log: $stderr" }
            Start-Sleep -Milliseconds 800
        }
    }
    if (-not $NoBrowser) {
        $edge = @(
            "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
            "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
            "$env:LOCALAPPDATA\Microsoft\Edge\Application\msedge.exe"
        ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if (-not $edge) { throw 'Microsoft Edge was not found. Please install Edge and try again.' }
        Start-Process -FilePath $edge -ArgumentList $url
    }
    Write-Output "Easel ready: $url"
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    if (-not $NoBrowser) { Read-Host 'Press Enter to close' | Out-Null }
    exit 1
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
