$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& .venv/Scripts/python.exe scripts/run.py --stop
exit $LASTEXITCODE
