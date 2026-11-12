#!/bin/sh
# Clip Anything one-paste installer for macOS and Linux:
#   curl -fsSL https://raw.githubusercontent.com/shreyassaw5394/clip-anything/main/scripts/install.sh | sh
# Installs uv (if missing), ffmpeg (brew on macOS, apt/dnf/pacman on Linux, if missing), then
# `uv tool install clip-anything`. Prints what it does; nothing runs with sudo except the
# system package manager when ffmpeg is missing.
set -eu

say() { printf '%s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

if ! have uv; then
  say "Installing uv (Python tool manager)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

if ! have ffmpeg || ! have ffprobe; then
  case "$(uname -s)" in
    Darwin)
      if have brew; then
        say "Installing ffmpeg with Homebrew..."
        brew install ffmpeg
      else
        say "Homebrew is not installed. Install it from https://brew.sh, then run: brew install ffmpeg"
        exit 3
      fi ;;
    Linux)
      if have apt-get; then sudo apt-get update && sudo apt-get install -y ffmpeg
      elif have dnf; then sudo dnf install -y ffmpeg
      elif have pacman; then sudo pacman -S --noconfirm ffmpeg
      else say "Install ffmpeg with your package manager, then re-run this script."; exit 3
      fi ;;
    *) say "Unsupported OS: install ffmpeg from https://ffmpeg.org/download.html"; exit 3 ;;
  esac
fi

say "Installing clip-anything..."
uv tool install --upgrade clip-anything
uv tool update-shell >/dev/null 2>&1 || true
say ""
say "Done. Open a new terminal and run:   clip-anything your-recording.mp4"
say "No terminal? The desktop app is at https://github.com/shreyassaw5394/clip-anything/releases"
