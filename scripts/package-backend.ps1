$ErrorActionPreference = 'Stop'
Set-Location (Join-Path (Split-Path $PSScriptRoot -Parent) 'backend')
python -m uv run --locked pyinstaller --noconfirm --clean --name tg-netdisk-backend --onedir --paths src --collect-submodules tg_netdisk --collect-submodules keyring.backends --hidden-import python_socks.async_.asyncio --hidden-import cryptg --add-data 'migrations;migrations' entry.py
if ($LASTEXITCODE -ne 0) { throw 'Python packaging failed' }
$cryptoCheck = & '.\dist\tg-netdisk-backend\tg-netdisk-backend.exe' --diagnose-crypto
if ($LASTEXITCODE -ne 0) { throw 'Packaged backend diagnostics failed' }
$cryptoInfo = $cryptoCheck | ConvertFrom-Json
if ($cryptoInfo.crypto_backend -ne 'cryptg' -or -not $cryptoInfo.native_crypto) { throw 'Packaged native crypto is missing' }
Write-Output 'Verified packaged cryptg acceleration and bounded upload pipeline.'
