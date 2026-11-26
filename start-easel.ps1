$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$env:PATH = "D:\Codexspace\Easel-runtime\node-v24.22.0-win-x64;D:\Codexspace\Easel-runtime\node_modules\.bin;D:\Codexspace\Easel-runtime\bin;$PSScriptRoot\.venv\Scripts;$env:PATH"
# Desktop launches do not inherit the Codex app's private CLI directory.
# Discover the current installation on each launch so app updates remain usable.
if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
    $codexInstallRoot = Join-Path $env:USERPROFILE 'AppData\Local\OpenAI\Codex\bin'
    $codexExecutable = Get-ChildItem -Path (Join-Path $codexInstallRoot '*\codex.exe') -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($codexExecutable) {
        $env:PATH = "$($codexExecutable.DirectoryName);$env:PATH"
    }
}
$localResources = Get-Content (Join-Path $PSScriptRoot 'outputs\_install\local-resources.json') -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($resource in $localResources.environment.PSObject.Properties) {
    [Environment]::SetEnvironmentVariable($resource.Name, [string]$resource.Value, 'Process')
}
$env:PYTHONUTF8 = '1'
$env:PLAYWRIGHT_BROWSERS_PATH = 'D:\Codexspace\Easel-runtime\browsers'
& "$PSScriptRoot\.venv\Scripts\python.exe" -m uvicorn web.app:app --host 127.0.0.1 --port 7860 --log-level warning



