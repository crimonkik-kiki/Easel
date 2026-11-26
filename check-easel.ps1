$env:PATH = "D:\Codexspace\Easel-runtime\node-v24.22.0-win-x64;D:\Codexspace\Easel-runtime\node_modules\.bin;D:\Codexspace\Easel-runtime\bin;$env:PATH"
$env:PLAYWRIGHT_BROWSERS_PATH = 'D:\Codexspace\Easel-runtime\browsers'
$localResources = Get-Content (Join-Path $PSScriptRoot 'outputs\_install\local-resources.json') -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($resource in $localResources.environment.PSObject.Properties) {
    [Environment]::SetEnvironmentVariable($resource.Name, [string]$resource.Value, 'Process')
}
$env:PYTHONUTF8 = '1'
Set-Location $PSScriptRoot
& "$PSScriptRoot\.venv\Scripts\easel.exe" doctor


