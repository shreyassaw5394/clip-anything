# Setup notes for the installer scripts (merge follow-up)

`scripts/install.sh` and `scripts/install.ps1` live on the `desktop` branch (PR #7), so this
branch does not create them. After both branches are on `main`, add one step to each so a fresh
install ends with the one-shot environment check (captions extra, Whisper model, optional local
AI), instead of stopping at the bare tool.

## `scripts/install.sh`

Replace the final block

```sh
say "Installing clip-anything..."
uv tool install --upgrade clip-anything
uv tool update-shell >/dev/null 2>&1 || true
```

with

```sh
say "Installing clip-anything..."
uv tool install --upgrade clip-anything
uv tool update-shell >/dev/null 2>&1 || true
export PATH="$HOME/.local/bin:$PATH"
say "Checking captions and local AI (installs only with your consent; --yes accepts all)..."
clip-anything setup --yes --no-ai || true
say "For AI titles and smarter picks later:   clip-anything setup   (adds Ollama), then --ai"
```

`--no-ai` keeps the installer from pulling a multi-GB model unprompted; `|| true` keeps a
declined or failed optional step from aborting an otherwise good install (ffmpeg was already
handled above, so `setup` cannot exit 3 here).

## `scripts/install.ps1`

Replace

```powershell
Write-Host "Installing clip-anything..."
uv tool install --upgrade clip-anything
```

with

```powershell
Write-Host "Installing clip-anything..."
uv tool install --upgrade clip-anything
$env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
Write-Host "Checking captions and local AI (installs only with your consent)..."
clip-anything setup --yes --no-ai
Write-Host "For AI titles and smarter picks later:   clip-anything setup   (adds Ollama), then --ai"
```

(`$ErrorActionPreference = "Stop"` does not trip on a non-zero exit code from a native command,
so a declined optional step does not abort the script.)

## Desktop build (`docs/desktop.md`, PR #7)

The packaged app bundles ffmpeg; `clip-anything setup` reports `(frozen)` for the captions
extra and prints a note instead of a pip command. Nothing to add there beyond a sentence that
the AI mode is a CLI feature for now.
