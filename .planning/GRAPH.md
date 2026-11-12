# GRAPH — the one file an executor reads (≤ 90 lines; update your node, never rewrite others)

## Product
Clip Anything: free, open-source, fully local CLI. Long gameplay recording in → top N vertical 9:16 highlight clips (15–45 s, burned captions when there's speech) + report.json out. Wedge: picks moments by ACTION (audio bursts + visual motion + cuts), works with zero speech; speech is bonus weight. Ships Sunday 2026-11-15 midnight under Ship at Midnight; GTA 6 launches 2026-11-19. Owner: "as simple and seamless as possible". v1 that demos by Saturday 2026-11-14 night beats completeness.

## Rules (non-negotiable)
- Python 3.11+ (use /Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11 + uv). Package `clip-anything`, module `clip_anything`, entry `clip-anything`. `uvx clip-anything` and `pipx install clip-anything` must work. MIT. No telemetry, no network calls except optional local Ollama at 127.0.0.1.
- ffmpeg/ffprobe are external binaries: check at start, print install help (brew/apt/winget) if missing. Never decode the full-res file more than once per rendered clip; analysis on audio 16 kHz mono + a 320px/5fps proxy.
- Lean deps: numpy, scipy, opencv-python-headless, faster-whisper (lazy import, optional), rich, typer (or argparse). No torch at import time. A 1-hour video analyses in minutes on a laptop CPU.
- Commit after each working step with a short neutral message. Test on the synthetic video (scripts/make_test_video.py) after each step. Unit tests: pytest. `ruff` clean.
- Nothing public, no publish, no repo creation: owner/Claude main session does that. No real people/brands in sample assets or copy except naming the games played ("GTA 5 gameplay") factually.
- Commit lock: `mkdir /tmp/clip-anything-commit.lock` → private GIT_INDEX_FILE from HEAD → `git add <your files>` → commit → `rmdir` lock. One executor at a time per plan; sequential plans unless a plan says parallel.

## Layout
clip_anything/{__init__,cli,probe,audio_signals,video_signals,speech,scoring,vision,render,captions,facecam,config,report}.py · tests/ · scripts/make_test_video.py · README.md · pyproject.toml (hatchling) · clip-anything.toml (weights/config, loadable via --config)

## CLI contract
clip-anything <video> [--count 10] [--min 15] [--max 45] [--out ./clips] [--no-captions] [--facecam auto|off] [--vision/--no-vision] [--config file] [--json] [--dry-run (report only, no render)]
Rich progress UI: probe → audio → video → score → (vision) → render N/N. Exit codes: 0 ok, 2 bad input, 3 ffmpeg missing.

## Pipeline (v1 build order; each step ends with a commit + synthetic run)
1. probe + audio signals (RMS, spectral flux onsets, loudness vs rolling baseline) per 0.5 s window, normalised 0..1
2. scoring + peak picking (weighted sum → smooth → peaks → window 60% before / 40% after → snap to quiet/cut → dedupe) + report.json
3. render: plain centre 9:16 crop, fades, H.264 veryfast CRF 20, AAC
4. CLI end to end on the synthetic video
5. visual motion signal (frame diff on proxy) + scene cuts (histogram delta)
6. action-following crop (centre of motion mass, smoothed, no jitter)
7. captions (faster-whisper, word-synced ASS, only when speech) + excitement bonus words
8. facecam detect (static corner region + face) → stack facecam over gameplay
9. vision re-rank via Ollama (optional; degrades silently)
10. README + launch assets (after core works)

## Numbers (update when measured)
- synthetic video: 3 min, testsrc + 6 injected loud bursts + 4 motion bursts → the top-6 clips must contain all 6 audio bursts (test)

## File ownership right now
(none)

## Phase nodes
- 01-core (steps 1–4) —
- 02-video (steps 5–6) —
- 03-speech-facecam (7–8) —
- 04-vision-readme (9–10) —

## Executor log (one line each)
