param([string]$DshBin)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$installer = Join-Path $PSScriptRoot 'dsh_plugin.ps1'
if (-not $DshBin) {
    $versions = Join-Path $env:APPDATA 'dsh-launcher/dsh-runtime/versions'
    $DshBin = @(Get-ChildItem -LiteralPath $versions -Directory | ForEach-Object {
        $candidate = Join-Path $_.FullName 'node_modules/@deepseek-ai/dsh/lib/bin.js'
        if (Test-Path -LiteralPath $candidate) { Get-Item -LiteralPath $candidate }
    } | Sort-Object LastWriteTime -Descending)[0].FullName
}
$parent = [IO.Path]::GetFullPath((Join-Path $root '.runtime/tests'))
$fixture = [IO.Path]::GetFullPath((Join-Path $parent ('installer-' + [guid]::NewGuid().ToString('N'))))
$profile = Join-Path $fixture 'profiles/fixture'
New-Item -ItemType Directory -Force -Path $profile | Out-Null
$patch = Join-Path $profile 'cordis.patch.yml'
$utf8 = [Text.UTF8Encoding]::new($false)
$captured = [Collections.Generic.List[string]]::new()
# A lexical command shim tests argument selection without launching another DSH,
# making model requests, touching credentials, or changing the user's profile.
function node {
    $captured.Clear()
    foreach ($argument in $args) { $captured.Add([string]$argument) }
    $global:LASTEXITCODE = 0
}
function Assert-True([bool]$Value, [string]$Message) {
    if (-not $Value) { throw $Message }
}
$previousHome = $env:DSH_HOME
try {
    foreach ($original in @("- select: example`r`n  options: {userSetting: preserved}`r`n", "[]`r`n")) {
        [IO.File]::WriteAllText($patch, $original, $utf8)
        & $installer -Action Install -Profile fixture -DshHome $fixture -DshBin $DshBin
        $once = [IO.File]::ReadAllText($patch)
        & $installer -Action Install -Profile fixture -DshHome $fixture -DshBin $DshBin
        Assert-True ([IO.File]::ReadAllText($patch) -ceq $once) 'Install must be idempotent'
        & $installer -Action Start -Profile fixture -DshHome $fixture -DshBin $DshBin -Port 3089
        Assert-True (-not $captured.Contains('--patch')) 'Installed profiles must not receive duplicate overlays'
        Assert-True ($captured.Contains('3089')) 'Explicit port must be forwarded'
        Assert-True ($env:DSH_HOME -ceq $previousHome) 'Start must restore the caller environment'
        & $installer -Action Uninstall -Profile fixture -DshHome $fixture -DshBin $DshBin
        Assert-True ([IO.File]::ReadAllText($patch) -ceq $original) 'Uninstall must restore unrelated content exactly'
        & $installer -Action Start -Profile fixture -DshHome $fixture -DshBin $DshBin
        Assert-True ($captured.Contains('--patch')) 'Uninstalled profiles must use the temporary overlay'
    }
    Write-Host 'PASS: preserved profile, idempotent install, exact uninstall, single composition, restored environment.'
} finally {
    $env:DSH_HOME = $previousHome
    # Resolve and fence the exact generated fixture before recursive deletion.
    $resolved = [IO.Path]::GetFullPath($fixture)
    if (-not $resolved.StartsWith($parent + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Refusing cleanup outside the installer fixture parent'
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
