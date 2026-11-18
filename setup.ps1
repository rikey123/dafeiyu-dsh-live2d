param([switch]$SkipSpeech, [switch]$SkipBuild, [switch]$LocalLlm, [switch]$SkipModelDownload)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
function Assert-Exit([string]$Step) { if ($LASTEXITCODE -ne 0) { throw "$Step failed (exit $LASTEXITCODE)." } }
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/' }
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'Install Node.js 22 LTS first: https://nodejs.org/' }
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    uv venv --python 3.12 .venv
    Assert-Exit 'Create Python environment'
}
uv pip install --python .venv/Scripts/python.exe -c requirements-lock.txt -r requirements.txt
Assert-Exit 'Backend dependencies'
if (-not (Test-Path -LiteralPath '.venv-voice\Scripts\python.exe')) {
    uv venv --python 3.12 .venv-voice
    Assert-Exit 'Create Pipecat voice environment'
}
uv pip install --python .venv-voice/Scripts/python.exe -r requirements-voice-lock.txt
Assert-Exit 'Pipecat voice core'
if (-not $SkipSpeech) {
    uv pip install --python .venv/Scripts/python.exe -c requirements-lock.txt -r requirements-speech.txt
    Assert-Exit 'Speech dependencies'
    if (-not $SkipModelDownload) {
        & .venv/Scripts/python.exe -m speech.prepare sensevoice asr openvino tts speaker
        Assert-Exit 'Speech models'
    }
}
if ($LocalLlm) {
    uv pip install --python .venv/Scripts/python.exe -c requirements-lock.txt -r requirements-llm.txt
    Assert-Exit 'Local LLM runtime'
    if (-not $SkipModelDownload) {
        & .venv/Scripts/python.exe scripts/prepare_local_llm.py
        Assert-Exit 'Local LLM model'
    }
}
if (-not $SkipBuild) {
    $avatarName = 'DeepSeek{0}{1}{2}{3}.zip' -f [char]0x514D, [char]0x8D39, [char]0x516C, [char]0x76AE
    $avatarArchive = Join-Path $PSScriptRoot $avatarName
    $avatarManifest = Join-Path $PSScriptRoot 'web\public\models\deepseek\avatar.model3.json'
    if (Test-Path -LiteralPath $avatarArchive -PathType Leaf) {
        & .venv/Scripts/python.exe scripts/import_avatar.py $avatarArchive --output (Join-Path $PSScriptRoot 'web\public\models\deepseek')
        Assert-Exit 'Import DeepSeek avatar'
    } elseif (-not (Test-Path -LiteralPath $avatarManifest -PathType Leaf)) {
        throw "Missing DeepSeek avatar. Place $avatarName in the project root, then run setup.ps1 again. See docs/DEEPSEEK_SKIN.md."
    }
    Push-Location -LiteralPath web
    try {
        npm.cmd ci --no-audit
        Assert-Exit 'Frontend dependencies'
        npm.cmd run setup:avatar -- --core-only
        Assert-Exit 'Live2D assets'
        npm.cmd run build
        Assert-Exit 'Frontend build'
    } finally { Pop-Location }
}
Write-Host 'Setup complete. Start with .\start.ps1' -ForegroundColor Cyan
