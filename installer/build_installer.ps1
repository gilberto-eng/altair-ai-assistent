$ErrorActionPreference = 'Stop'

Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location ..

# Build AltairInstaller.exe (standalone) via PyInstaller.
#
# Prereqs (na maquina que vai buildar):
#   1) Python instalado (para rodar o build)
#   2) pip install pyinstaller
#   3) Preencher installer/payload/ com o conteudo do payload (ver README).
#
# Output:
#   dist/AltairInstaller.exe

if (-not (Test-Path 'installer/payload')) {
  throw 'Pasta installer/payload nao encontrada. Crie e coloque o conteudo do payload.'
}

Write-Output 'Gerando installer/payload.zip...'
if (Test-Path 'installer/payload.zip') { Remove-Item -Force 'installer/payload.zip' }
Compress-Archive -Path 'installer/payload/*' -DestinationPath 'installer/payload.zip' -Force

Write-Output 'Buildando AltairInstaller.exe...'
python -m PyInstaller --noconfirm --clean `
  --name AltairInstaller `
  --onefile `
  --add-data "installer\payload.zip;." `
  installer/altair_installer.py

Write-Output 'OK: built dist/AltairInstaller.exe'
