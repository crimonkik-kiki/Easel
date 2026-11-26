$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ($projectRoot -ne 'D:\Codexspace\Easel') { throw 'Unexpected project directory' }
Set-Location -LiteralPath $projectRoot
$releasePath = (Get-Content -LiteralPath 'tmp/operations-current-release.txt' -Raw).Trim()
if (-not $releasePath.StartsWith("$projectRoot\tmp\operations-release-")) { throw 'Invalid release path' }
$manifest = Get-Content -LiteralPath (Join-Path $releasePath 'manifest.json') -Raw | ConvertFrom-Json
foreach ($entry in $manifest.tested_sha256.PSObject.Properties) {
    if ((Get-FileHash -LiteralPath (Join-Path $projectRoot $entry.Name) -Algorithm SHA256).Hash.ToLower() -ne $entry.Value) {
        throw "Candidate changed after verification: $($entry.Name)"
    }
}

function Assert-Idle {
    $rows = Get-CimInstance Win32_Process
    $active = @($rows | Where-Object {
        $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -notmatch 'pytest|verify_operations_ui' -and
        $_.CommandLine -match 'account_stats\.py|account_browser\.py|web_publisher\.py|douyin_publish\.py|xhs_publish\.py|weixin_mp_stats\.py|bili_login\.py|weixin_mp_login\.py'
    })
    $browsers = @($rows | Where-Object {
        $_.Name -match 'msedge|chrome|chromium' -and $_.CommandLine -match 'easel.*profiles|Easel.*browser'
    })
    if ($active.Count -or $browsers.Count) { throw 'Account task or profile browser is active; restart refused' }
}

function Stop-OwnedService {
    $rows = Get-CimInstance Win32_Process
    $wrappers = @($rows | Where-Object {
        $_.ExecutablePath -eq "$projectRoot\.venv\Scripts\python.exe" -and
        $_.CommandLine -match '-m uvicorn web.app:app --host 127.0.0.1 --port 7860'
    })
    foreach ($wrapper in $wrappers) {
        foreach ($child in @($rows | Where-Object {
            $_.ParentProcessId -eq $wrapper.ProcessId -and $_.Name -eq 'python.exe' -and
            $_.CommandLine -match '-m uvicorn web.app:app --host 127.0.0.1 --port 7860'
        })) { Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue }
        Stop-Process -Id $wrapper.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Start-ServiceHidden([string]$label) {
    $shellPath = (Get-Process -Id $PID).Path
    Start-Process -FilePath $shellPath -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "$projectRoot\start-easel.ps1") -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $releasePath "$label.stdout.log") -RedirectStandardError (Join-Path $releasePath "$label.stderr.log") | Out-Null
}

function Copy-Dist([string]$source) {
    $targetRoot = Join-Path $projectRoot 'web\frontend\dist'
    # Copy the index last; retain old hashed assets for already open browser tabs.
    foreach ($file in Get-ChildItem -LiteralPath $source -File -Recurse | Where-Object Name -ne 'index.html') {
        $relative = [IO.Path]::GetRelativePath($source, $file.FullName)
        $target = [IO.Path]::GetFullPath((Join-Path $targetRoot $relative))
        if (-not $target.StartsWith("$targetRoot\")) { throw 'Copy target escaped dist' }
        New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($target)) -Force | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $target -Force
    }
    Copy-Item -LiteralPath (Join-Path $source 'index.html') -Destination (Join-Path $targetRoot 'index.html') -Force
}

Assert-Idle
$deploymentStarted = $false
try {
    $deploymentStarted = $true
    Stop-OwnedService
    Copy-Dist (Join-Path $projectRoot 'tmp\operations-ui-dist')
    Start-ServiceHidden 'candidate'
    & "$projectRoot\.venv\Scripts\python.exe" 'scripts/operations_release_health.py' '--wait' '20' | Tee-Object -FilePath (Join-Path $releasePath 'health.json')
    if ($LASTEXITCODE -ne 0) { throw "Health check failed with exit $LASTEXITCODE" }
    Write-Output "DEPLOYED $releasePath"
} catch {
    if ($deploymentStarted) {
        Stop-OwnedService
        foreach ($relative in $manifest.rollback_paths) {
            $target = [IO.Path]::GetFullPath((Join-Path $projectRoot $relative))
            if (-not $target.StartsWith("$projectRoot\")) { throw 'Rollback target escaped project' }
            Copy-Item -LiteralPath (Join-Path "$releasePath\rollback" $relative) -Destination $target -Force
        }
        Copy-Dist (Join-Path $releasePath 'rollback\dist')
        Start-ServiceHidden 'rollback'
        Write-Output 'ROLLED_BACK; STOPPED; MANUAL_REVIEW_REQUIRED'
    }
    throw
}
