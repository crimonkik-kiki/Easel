$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$python=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$brand=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'workbench.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$installation=& $python -c "from pathlib import Path;import hashlib;print(hashlib.sha256(Path.cwd().resolve().as_posix().casefold().encode('utf-8')).hexdigest()[:16])"
if($LASTEXITCODE -ne 0){throw '不能确认当前工作台目录'}
$url='http://127.0.0.1:'+$brand.port
function Call-Local([string]$path,[string]$method){
  $request=[System.Net.WebRequest]::Create($url+$path);$request.Proxy=$null;$request.Timeout=3000;$request.ReadWriteTimeout=3000;$request.Method=$method
  if($method -eq 'POST'){$request.ContentLength=0}
  $response=$request.GetResponse()
  try{$reader=New-Object System.IO.StreamReader($response.GetResponseStream());try{return ($reader.ReadToEnd() | ConvertFrom-Json)}finally{$reader.Dispose()}}finally{$response.Dispose()}
}
$health=Call-Local '/api/health' 'GET'
if($health.instance -ne $brand.id -or $health.installation -ne $installation){throw '此端口不是当前目录的工作台，拒绝停止其他实例'}
$null=Call-Local '/api/admin/stop' 'POST'
Write-Output '工作台正在安全退出。不会停止其他Python进程。'
