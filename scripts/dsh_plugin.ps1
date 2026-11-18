param(
    [ValidateSet('Build', 'Prepare', 'Start', 'Install', 'Uninstall')][string]$Action = 'Prepare',
    [ValidatePattern('^[a-zA-Z0-9_-]+$')][string]$Profile = 'web',
    [ValidateRange(1,65535)][int]$Port = 3081,
    [string]$DshBin,
    [string]$DshHome = $env:DSH_HOME
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
if (-not $DshHome) { $DshHome = Join-Path $env:USERPROFILE '.dsh' }
if (-not $DshBin) {
    $versions = Join-Path $env:APPDATA 'dsh-launcher/dsh-runtime/versions'
    $candidates = @(Get-ChildItem -LiteralPath $versions -Directory | ForEach-Object {
        $candidate = Join-Path $_.FullName 'node_modules/@deepseek-ai/dsh/lib/bin.js'
        if (Test-Path -LiteralPath $candidate) { Get-Item -LiteralPath $candidate }
    } | Sort-Object LastWriteTime -Descending)
    if (-not $candidates.Count) { throw 'DSH runtime not found. Specify its actual bin.js with -DshBin.' }
    $DshBin = $candidates[0].FullName
}
$runtime = [IO.Path]::GetFullPath((Join-Path (Split-Path $DshBin -Parent) '../../..'))
$runtimeDir = Join-Path $root '.runtime'
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
$overlay = Join-Path $runtimeDir 'dsh-plugin.patch.yml'
$utf8 = [System.Text.UTF8Encoding]::new($false)
$entry = (Join-Path $root 'plugins/dsh/src/index.mjs').Replace('\','/')
$config = @{projectRoot=$root.Replace('\','/'); workspacePath=$root.Replace('\','/'); runtimeModulesRoot=$runtime.Replace('\','/')}
$block = "- insert:`n    - id: dafeiyu-live2d`n      name: '$($entry.Replace("'","''"))'`n      config: $($config | ConvertTo-Json -Compress)`n"
$begin = '# BEGIN DAFEIYU DSH PLUGIN (managed by scripts/dsh_plugin.ps1)'
$end = '# END DAFEIYU DSH PLUGIN'

if ($Action -eq 'Build') {
    Push-Location (Join-Path $root 'web')
    try { & npm.cmd run build:dsh; if ($LASTEXITCODE) { throw 'DSH frontend build failed' } } finally { Pop-Location }
    & node --test (Join-Path $root 'plugins/dsh/test/*.test.mjs')
    if ($LASTEXITCODE) { throw 'DSH plugin tests failed' }
    return
}
if ($Action -in @('Install', 'Uninstall')) {
    if ($Profile -notmatch '^[a-zA-Z0-9_-]+$') { throw 'Invalid profile name' }
    $patch = Join-Path $DshHome "profiles/$Profile/cordis.patch.yml"
    if (-not (Test-Path -LiteralPath $patch)) { throw 'Profile does not exist. Create it using DSH first. User configuration is not overwritten.' }
    $content = [IO.File]::ReadAllText($patch)
    if ($content.Contains($begin) -xor $content.Contains($end)) { throw 'Incomplete plugin block markers; check the profile manually.' }
    $clean = [regex]::Replace($content, '(?ms)^' + [regex]::Escape($begin) + '.*?^' + [regex]::Escape($end) + '\r?\n?', '')
    $emptyMarker = '# DAFEIYU_ORIGINAL_EMPTY_PATCH: '
    $originalEmpty = [regex]::Match($content, '(?m)^' + [regex]::Escape($emptyMarker) + '([A-Za-z0-9+/=]+)\r?$')
    $emptyNote = ''
    if ($originalEmpty.Success) {
        $emptyNote = $emptyMarker + $originalEmpty.Groups[1].Value + "`n"
        if ($Action -eq 'Uninstall') { $clean = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($originalEmpty.Groups[1].Value)) }
    } elseif (($clean -replace '(?m)^\s*#.*$', '').Trim() -eq '[]') {
        $emptyNote = $emptyMarker + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($clean)) + "`n"
        if ($Action -eq 'Install') { $clean = '' }
    }
    # Preserve unrelated content; represent a previously empty sequence inside our managed block for exact rollback.
    $separator = if ($clean.Length -gt 0 -and -not $clean.EndsWith("`n")) { "`n" } else { '' }
    $updated = if ($Action -eq 'Install') { $clean + $separator + $begin + "`n" + $emptyNote + $block + $end + "`n" } else { $clean }
    if ($updated -ne $content) {
        $backup = Join-Path $runtimeDir ('dsh-profile-patch-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '.yml')
        [IO.File]::WriteAllText($backup, $content, $utf8)
        $temporary = "$patch.dafeiyu.tmp"
        [IO.File]::WriteAllText($temporary, $updated, $utf8)
        Move-Item -LiteralPath $temporary -Destination $patch -Force
    }
    Write-Host "DSH profile '$Profile': $Action complete. Only the managed plugin block was changed. Backup: project .runtime. Restart this profile to activate."
    return
}
[IO.File]::WriteAllText($overlay, $block, $utf8)
if ($Action -eq 'Prepare') {
    Write-Host "Plugin overlay prepared: $overlay"
    Write-Host 'Source remains on the project drive. Existing DSH profile unchanged. No GPU or inference started.'
    return
}
if (-not (Test-Path -LiteralPath (Join-Path $root 'web/dist-dsh/entry.js'))) { throw 'Run -Action Build first.' }
# A persistent installation already contains the same plugin. Applying its
# overlay again would insert duplicate route owners into the Cordis composition.
$profilePatch = Join-Path $DshHome "profiles/$Profile/cordis.patch.yml"
$installed = (Test-Path -LiteralPath $profilePatch) -and [IO.File]::ReadAllText($profilePatch).Contains($begin)
$launchArguments = @($DshBin)
# Launcher options must precede the profile's own app arguments in rc1.
if (-not $installed) { $launchArguments += @('--patch', $overlay) }
$launchArguments += @('--profile', $Profile, '--no-open', '--port', "$Port")
# Leave any existing DSH process untouched; a temporary overlay stays reversible.
$previousHome = $env:DSH_HOME
$launchDirectory = Join-Path $runtimeDir 'dsh-launch'
New-Item -ItemType Directory -Force -Path $launchDirectory | Out-Null
Push-Location $launchDirectory
try {
    $env:DSH_HOME = $DshHome
    & node @launchArguments
    $result = $LASTEXITCODE
} finally { $env:DSH_HOME = $previousHome; Pop-Location }
exit $result
