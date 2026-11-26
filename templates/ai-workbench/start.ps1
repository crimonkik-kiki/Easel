param([switch]$NoBrowser)
$ErrorActionPreference='Stop'
$root=$PSScriptRoot
Set-Location -LiteralPath $root
$env:PYTHONUTF8='1';$env:PYTHONIOENCODING='utf-8'
$python=Join-Path $root '.venv\Scripts\python.exe'
if(-not (Test-Path -LiteralPath $python)){throw '请先运行 setup.ps1 完成安装'}
$brand=Get-Content -LiteralPath (Join-Path $root 'workbench.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$url='http://127.0.0.1:'+$brand.port
$installation=& $python -c "from pathlib import Path;import hashlib;print(hashlib.sha256(Path.cwd().resolve().as_posix().casefold().encode('utf-8')).hexdigest()[:16])"
if($LASTEXITCODE -ne 0){throw '不能确认工作台安装目录'}
function Read-Health {
  $request=[System.Net.WebRequest]::Create($url+'/api/health')
  $request.Proxy=$null; $request.Timeout=2000; $request.ReadWriteTimeout=2000
  try {
    $response=$request.GetResponse()
    try {$reader=New-Object System.IO.StreamReader($response.GetResponseStream());try{return ($reader.ReadToEnd() | ConvertFrom-Json)}finally{$reader.Dispose()}}finally{$response.Dispose()}
  }catch{return $null}
}
function Test-Port {
  $socket=New-Object System.Net.Sockets.TcpClient
  try {$operation=$socket.ConnectAsync('127.0.0.1',[int]$brand.port);return ($operation.Wait(1000) -and $socket.Connected)}catch{return $false}finally{$socket.Dispose()}
}
$health=Read-Health
if($health -and ($health.instance -ne $brand.id -or $health.installation -ne $installation)){throw '此端口已被其他工作台占用，请修改 workbench.json 的 port'}
if(-not $health){
  if(Test-Port){throw '端口已被其他服务占用，请修改 workbench.json 的 port，不会启动第二个进程'}
  $logs=Join-Path $root 'outputs\_system'
  New-Item -ItemType Directory -Path $logs -Force | Out-Null
  Start-Process -FilePath $python -ArgumentList @('-m','workbench') -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'server.stdout.log') -RedirectStandardError (Join-Path $logs 'server.stderr.log') | Out-Null
  for($i=0;$i -lt 40;$i++){
    Start-Sleep -Milliseconds 250
    $health=Read-Health
    if($health -and $health.instance -eq $brand.id -and $health.installation -eq $installation){break}
  }
  if(-not $health -or $health.instance -ne $brand.id -or $health.installation -ne $installation){throw '工作台没有启动，请检查 outputs\_system\server.stderr.log；可能存在端口占用'}
}
if(-not $NoBrowser){
  $edge=Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'
  if(Test-Path -LiteralPath $edge){Start-Process -FilePath $edge -ArgumentList @($url) | Out-Null}
  else {Start-Process $url | Out-Null}
}
Write-Output $url
