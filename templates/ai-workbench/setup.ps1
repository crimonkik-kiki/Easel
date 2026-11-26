param([switch]$RebuildUI)
$ErrorActionPreference='Stop'
$root=$PSScriptRoot
Set-Location -LiteralPath $root
$python=Join-Path $root '.venv\Scripts\python.exe'
if(-not (Test-Path -LiteralPath $python)){
  if(Get-Command py -ErrorAction SilentlyContinue){ & py -3 -m venv .venv }
  elseif(Get-Command python -ErrorAction SilentlyContinue){ & python -m venv .venv }
  else {throw '请先安装 Python 3.10+，并添加到 PATH'}
  if($LASTEXITCODE -ne 0){throw '创建 Python 环境失败'}
}
if(Test-Path -LiteralPath (Join-Path $root 'requirements.lock')){
  & $python -m pip install -r requirements.lock
  if($LASTEXITCODE -ne 0){throw '已验证版本的运行依赖安装失败'}
}
& $python -m pip install -e .
if($LASTEXITCODE -ne 0){throw 'Python 依赖安装失败'}
if($RebuildUI -or -not (Test-Path -LiteralPath (Join-Path $root 'frontend\dist\index.html'))){
  if(-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)){throw '构建前端需要 Node.js 22.12+ 与 npm；或使用自带前端的发布包'}
  Push-Location (Join-Path $root 'frontend')
  try {
    & npm.cmd ci
    if($LASTEXITCODE -ne 0){throw '前端依赖安装失败'}
    & npm.cmd run build
    if($LASTEXITCODE -ne 0){throw '前端构建失败'}
  } finally {Pop-Location}
}
Write-Output '安装完成。双击 启动工作台.cmd；在 AI 设置 中配置引擎或模型API。'
