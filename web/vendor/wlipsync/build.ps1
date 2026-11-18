param([Parameter(Mandatory=$true)][string]$Toolchain)
$ErrorActionPreference = 'Stop'
$src = Join-Path $PSScriptRoot 'src'
$build = Join-Path $PSScriptRoot 'build'
New-Item -ItemType Directory -Force $build | Out-Null
$objects = @()
Get-ChildItem $src -Filter '*.c' -Recurse | Sort-Object FullName | ForEach-Object {
  $relative = $_.FullName.Substring($src.Length + 1).Replace('\', '_').Replace('/', '_')
  $obj = Join-Path $build ($relative + '.o')
  & (Join-Path $Toolchain 'clang.exe') --target=wasm32 -mbulk-memory -nostdlib -O3 -ffast-math -I $src -o $obj -c $_.FullName
  if ($LASTEXITCODE -ne 0) { throw 'clang failed' }
  $objects += $obj
}
& (Join-Path $Toolchain 'wasm-ld.exe') --no-entry --export-dynamic --export-all --lto-O3 --import-memory @objects -o (Join-Path $PSScriptRoot 'wlipsync.wasm')
if ($LASTEXITCODE -ne 0) { throw 'wasm-ld failed' }
