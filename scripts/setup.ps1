$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
npm.cmd ci
if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
python -m uv sync --project backend --group dev --locked
if ($LASTEXITCODE -ne 0) { throw 'uv sync failed' }
