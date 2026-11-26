# Always use this project's interpreter; do not inherit another app's python/python3.
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$newsPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $newsPython)) {
    throw "Easel Python is missing: $newsPython. Restore the project's .venv first."
}
$commandName = if ($args.Count) { [string]$args[0] } else { 'fetch' }
[string[]]$scriptArgs = @()
if ($args.Count -gt 1) {
    $scriptArgs = @(for ($index = 1; $index -lt $args.Count; $index++) {
        if ($args[$index] -is [array]) { $args[$index] -join ',' }
        else { [string]$args[$index] }
    })
}
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
if ($commandName -eq 'check') {
    & $newsPython -c 'import sys,json,requests,bs4; print(json.dumps(dict(python=sys.executable,requests=requests.__version__,beautifulsoup4=bs4.__version__)))'
    exit $LASTEXITCODE
}
$scriptName = switch ($commandName) {
    'fetch' { 'fetch_news.py' }
    'briefing' { 'daily_briefing.py' }
    default { throw 'Usage: scripts/news.ps1 fetch|briefing|check [script arguments]' }
}
$scriptPath = Join-Path $projectRoot "skills\builtin\skill-news-intelligence\scripts\$scriptName"
& $newsPython $scriptPath @scriptArgs
exit $LASTEXITCODE
