param([switch]$NoBrowser, [switch]$Dev, [switch]$NoSpeech, [switch]$LocalLlm, [switch]$NoLocalLlm)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) { throw 'Run .\setup.ps1 first.' }
$launchArgs = @('scripts/run.py')
if (-not $NoBrowser) { $launchArgs += '--open' }
if ($Dev) { $launchArgs += '--dev' }
if ($NoSpeech) { $launchArgs += '--no-speech' }
if ($LocalLlm) { $launchArgs += '--local-llm' }
if ($NoLocalLlm) { $launchArgs += '--no-local-llm' }
& $projectPython @launchArgs
exit $LASTEXITCODE
