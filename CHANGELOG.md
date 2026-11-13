# Changelog

All notable changes to Clip Anything. Dates are the day the change landed.

## 0.2.0 — 2026-11-13

- Desktop app for Windows and Mac (download, open, drop a recording in); Windows supported and tested in CI
- `clip-anything setup`: installs ffmpeg, captions and an optional local AI model if missing, skips what is there
- `--ai` mode: better picks, titles and a hook line from a local Ollama model, or your own OpenAI/Anthropic key
- Plain-language README with step-by-step scenarios; Claude Code and Cursor skills; `npx clip-anything` launcher
- Logo and images; feedback issue template

## 0.1.0 — 2026-11-12

First release, built in the open for the Ship at Midnight launch.

- One command: `uvx clip-anything gameplay.mp4` turns a long recording into the top N vertical 9:16 clips plus `report.json`
- Action-first scoring with no speech required: audio onsets, loudness over a rolling baseline, visual motion, scene cuts, and an audio-and-motion agreement term; static cards (menus, lobbies, loading screens) penalised
- Build-up windows (60 % before the peak, 40 % after) snapped to quiet points and cuts, de-duplicated; `--count` is a maximum, never padded
- Streamed analysis on 16 kHz mono audio and a 320 px / 5 fps proxy; signal cache in `.clipanything/` for second-run tweaks in seconds
- Action-following 9:16 crop (smoothed, dead-band, pan cap) with centre fallback; HDR tone-mapped on ffmpeg 8+
- Robust inputs: VFR (OBS), HEVC, HDR, rotated sources; ffmpeg preflight with install help and clear exit codes
- Optional captions via faster-whisper (word-synced, burned in when libass is available, sidecar `.ass` otherwise) and excitement-word bonus; `--speech-rank` re-rank
- Optional facecam detection, stacked above the gameplay
- Optional `--vision` re-rank and titles with a local Ollama vision model; degrades silently when Ollama is absent
- Advanced `--ai` mode: re-rank of the top 3N candidates, titles, post hooks and a featured spoken line via a local Ollama or your own OpenAI/Anthropic key (`--ai-provider`, `--ai-model`, `--ai-vision-model`, `--ai-key`); AI text marked `ai_generated`; degrades to the action-only order with one warning (`docs/ai-mode.md`)
- One-shot `clip-anything setup`: checks ffmpeg, Python, the captions extra, the Whisper model and optional Ollama; installs only after `--yes` or confirmation; idempotent
- Library-first design: `clip_anything.pipeline.run()` with progress events, thin typer CLI, TOML config with every weight exposed
- No telemetry, no accounts, no uploads
- Repository: CI (ruff and pytest on macOS and Ubuntu, Python 3.11 and 3.13), Dependabot, security policy, third-party licence list, `uv.lock`
