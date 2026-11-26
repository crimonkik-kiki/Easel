param([switch]$Phase2Only, [int]$WaitSeconds=0)
$ErrorActionPreference='Stop'
try {
    Set-Location -LiteralPath $PSScriptRoot
    $probeArgs=@('-m','web.health_probe','--wait-seconds',[string]$WaitSeconds)
    if($Phase2Only){$probeArgs+='--phase2-only'}
    $raw=& (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') @probeArgs
    $probeExit=$LASTEXITCODE
    $result=$raw | ConvertFrom-Json -ErrorAction Stop
    $expected=@{0='HEALTHY';20='SERVICE_UNAVAILABLE';21='SERVICE_UNHEALTHY';30='PROBE_ERROR_MANUAL_REVIEW'}
    if(-not $expected.ContainsKey($probeExit) -or $null -eq $result -or $result.marker -ne $expected[$probeExit]){
        throw 'Invalid or inconsistent probe result'
    }
    $raw | Write-Output
    exit $probeExit
} catch {
    @{marker='PROBE_ERROR_MANUAL_REVIEW';requires_human_review=$true;detail=$_.Exception.Message} | ConvertTo-Json -Compress
    exit 30
}
