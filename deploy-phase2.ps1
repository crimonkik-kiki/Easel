param([Parameter(Mandatory=$true)][string]$ReleaseDir, [ValidateSet('Deploy','Rollback')][string]$Action='Deploy')
$ErrorActionPreference='Stop'
$projectRoot=$PSScriptRoot
Set-Location -LiteralPath $projectRoot
$release=[IO.Path]::GetFullPath($ReleaseDir)
$allowedPrefix=(Join-Path $projectRoot 'tmp\release-probe-fixed-')
if(-not $release.StartsWith($allowedPrefix,[StringComparison]::OrdinalIgnoreCase)){throw 'Invalid release directory'}
$python=Join-Path $projectRoot '.venv\Scripts\python.exe'
$script:lastGate=$null

function Invoke-Gate([string]$Label,[switch]$Phase2Only,[switch]$Ui) {
    if($Ui){
        $raw=& $python (Join-Path $projectRoot 'scripts\health_ui.py')
    } else {
        $arguments=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',(Join-Path $projectRoot 'health-easel.ps1'),'-WaitSeconds','15')
        if($Phase2Only){$arguments+='-Phase2Only'}
        $raw=& powershell.exe @arguments
    }
    $code=$LASTEXITCODE
    try {
        $result=$raw|ConvertFrom-Json -ErrorAction Stop
        if($null -eq $result -or -not $result.marker){throw 'Missing probe marker'}
    } catch {
        $code=30
        $result=[pscustomobject]@{marker='PROBE_ERROR_MANUAL_REVIEW';requires_human_review=$true;detail='Probe output was not valid structured JSON'}
    }
    $result|ConvertTo-Json -Depth 12|Set-Content -LiteralPath (Join-Path $release "$Label.json") -Encoding UTF8
    $script:lastGate=$result
    if($code -ne 0 -or $result.marker -ne 'HEALTHY'){
        throw "HEALTH_GATE_FAILED:$($result.marker)"
    }
    return $result
}

function Stop-EaselServer {
    $all=@(Get-CimInstance Win32_Process -ErrorAction Stop)
    $listener=@(Get-NetTCPConnection -LocalPort 7860 -State Listen -ErrorAction SilentlyContinue)
    if($listener.Count -eq 0){return}
    if($listener.Count -ne 1){throw 'Cannot identify unique Easel listener'}
    $server=$all|Where-Object {$_.ProcessId -eq $listener[0].OwningProcess}
    if($server.CommandLine -notmatch 'uvicorn web\.app:app.*--port 7860'){throw 'Port owner is not the expected Easel process'}
    $wrapper=$all|Where-Object {$_.ProcessId -eq $server.ParentProcessId -and $_.CommandLine -match 'Easel\\.venv\\Scripts\\python.exe.*uvicorn web\.app:app'}
    Stop-Process -Id $server.ProcessId
    if($wrapper -and (Get-Process -Id $wrapper.ProcessId -ErrorAction SilentlyContinue)){Stop-Process -Id $wrapper.ProcessId}
}

function Start-EaselServer([string]$Label) {
    Start-Process powershell.exe -ArgumentList @('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',(Join-Path $projectRoot 'start-easel.ps1')) -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $release "$Label.log") -RedirectStandardError (Join-Path $release "$Label.err.log")
}

function Restore-Service {
    Stop-EaselServer
    $files=Get-Content -LiteralPath (Join-Path $release 'rollback-files.json') -Raw -Encoding UTF8|ConvertFrom-Json
    foreach($relative in $files){
        Copy-Item -LiteralPath (Join-Path $release "rollback\$relative") -Destination (Join-Path $projectRoot $relative) -Force
    }
    Copy-Item -Path (Join-Path $release 'rollback\dist\*') -Destination (Join-Path $projectRoot 'web\frontend\dist') -Recurse -Force
    Start-EaselServer 'rollback-server'
    $null=Invoke-Gate 'rollback-health' -Phase2Only
}

if($Action -eq 'Rollback'){
    Restore-Service
    @{marker='ROLLED_BACK_TO_PHASE2';release=$release}|ConvertTo-Json -Compress
    exit 0
}

# No service is stopped if occupancy cannot be established.
$null=Invoke-Gate 'preflight-health' -Phase2Only
$occupancy=& $python (Join-Path $projectRoot 'scripts\release_preflight.py')
if($LASTEXITCODE -ne 0){$occupancy|Write-Output;throw 'Account operations or probe uncertainty block deployment'}
$occupancy|Set-Content -LiteralPath (Join-Path $release 'preflight-occupancy.json') -Encoding UTF8
$all=@(Get-CimInstance Win32_Process -ErrorAction Stop)
$workers=@($all|Where-Object {$_.Name -in @('python.exe','pythonw.exe') -and $_.CommandLine -match 'Easel[\\/]skills[\\/]shared[\\/]scripts[\\/](account_browser|account_stats|web_publisher|xhs_publish|douyin_publish|weixin_mp_stats|zhihu_answer|xhs_comment|zhihu_comments_fetch)\.py'})
$browsers=@($all|Where-Object {$_.Name -match '^(msedge|chrome|chromium|headless_shell)\.exe$' -and $_.CommandLine -match '(\.easel-browser-profiles|Easel[\\/]\.easel-channel-profiles)'})
if($workers.Count -or $browsers.Count){throw 'Existing account worker or browser blocks deployment'}
@{workers=$workers.Count;browsers=$browsers.Count}|ConvertTo-Json -Compress|Set-Content -LiteralPath (Join-Path $release 'preflight-processes.json') -Encoding UTF8
$manifest=Get-Content -LiteralPath (Join-Path $release 'source-manifest.json') -Raw -Encoding UTF8|ConvertFrom-Json
foreach($entry in $manifest.PSObject.Properties){
    if((Get-FileHash -LiteralPath (Join-Path $projectRoot $entry.Name) -Algorithm SHA256).Hash.ToLower() -ne $entry.Value){
        throw 'Source changed after candidate snapshot; deployment blocked'
    }
}

# A failed post-deploy gate triggers exactly one rollback, never another deploy.
try {
    Stop-EaselServer
    Copy-Item -Path (Join-Path $release 'candidate\dist\*') -Destination (Join-Path $projectRoot 'web\frontend\dist') -Recurse -Force
    Start-EaselServer 'deployed-server'
    $core=Invoke-Gate 'deployed-core-health'
    $ui=Invoke-Gate 'deployed-ui-health' -Ui
    @{marker='DEPLOYED_HEALTHY';release=$release;core=$core;ui=$ui}|ConvertTo-Json -Depth 12 -Compress
    exit 0
} catch {
    $failure=$_.Exception.Message
    $failedGate=$script:lastGate
    try {
        Restore-Service
        @{marker='DEPLOYMENT_ROLLED_BACK';failure=$failure;failed_gate=$failedGate;requires_human_review=$true;release=$release}|ConvertTo-Json -Depth 12 -Compress
        exit 31
    } catch {
        @{marker='ROLLBACK_UNCONFIRMED_MANUAL_REVIEW';failure=$failure;rollback_error=$_.Exception.Message;requires_human_review=$true;release=$release}|ConvertTo-Json -Depth 12 -Compress
        exit 32
    }
}
