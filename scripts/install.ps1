# Clip Anything one-paste installer for Windows (PowerShell):
#   irm https://raw.githubusercontent.com/shreyassaw5394/clip-anything/main/scripts/install.ps1 | iex
# Installs uv and ffmpeg with winget when missing, then `uv tool install clip-anything`.
$ErrorActionPreference = "Stop"

function Have($name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

if (-not (Have "winget")) {
  Write-Host "winget is not available. Install 'App Installer' from the Microsoft Store, then re-run."
  exit 3
}
if (-not (Have "uv")) {
  Write-Host "Installing uv (Python tool manager)..."
  winget install --id astral-sh.uv -e --accept-source-agreements --accept-package-agreements
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
}
if (-not (Have "ffmpeg") -or -not (Have "ffprobe")) {
  Write-Host "Installing ffmpeg..."
  winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
}
Write-Host "Installing clip-anything..."
uv tool install --upgrade clip-anything
Write-Host ""
Write-Host "Done. Open a new terminal and run:   clip-anything your-recording.mp4"
Write-Host "No terminal? The desktop app is at https://github.com/shreyassaw5394/clip-anything/releases"
