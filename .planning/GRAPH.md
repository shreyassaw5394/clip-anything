# GRAPH — the one file an executor reads (≤ 90 lines; update your node, never rewrite others)

## Product
Clip Anything: free, open-source, fully local CLI. Long gameplay recording in → top N vertical 9:16 highlight clips (15–45 s, burned captions when there's speech) + report.json out. Wedge: picks moments by ACTION (audio bursts + visual motion + cuts), works with zero speech; speech is bonus weight. Ships Sunday 2026-11-15 midnight under Ship at Midnight; GTA 6 launches 2026-11-19. Owner: "as simple and seamless as possible"; "local, free, open source, but we can do a hosted version later" → keep the pipeline a pure library (`clip_anything.pipeline.run(video, options) -> Report`) with the CLI as a thin wrapper, no global state, so a hosted service can import it later. v1 that demos by Saturday 2026-11-14 night beats completeness.

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
- synthetic video: 3 min, testsrc + 6 injected loud bursts + 4 motion bursts → the top-6 clips must contain all 6 audio bursts (test) — PASSING; music-bed + VFR variants also 6/6
- measured 2026-11-12 (M1 Max): audio analysis ≈ 4 s per hour of input (1 h file: audio 3.85 s, score 0.47 s, dry-run 4.4 s); render ≈ 3 s per 17 s clip, 2 workers; synthetic 3 min end to end 10.7 s
- video pass (audio ∥ video, decode-bound): 74 min 854x480@60 → 24 s/hour; 40 min 720p30 → 42 s/hour; 1080p30 → 54 s/hour (target ≤ 60; 1080p60 would miss, ≈ 100); 4K HEVC HDR 101 s → 20 s with videotoolbox (sw 44 s). Crop expression: 90 keyframes cost 0 s (ffmpeg 9.0.2 spike); quiet-audio 4/4 motion bursts, square followed within 8 %

## File ownership right now
- 03-01 executor: speech.py, captions.py, facecam.py (new); render.py (layout: facecam vstack + ass append, append-only), cli.py (--no-captions/--facecam/--yes flags, append-only), pipeline.py (speech+captions+facecam stage calls, append-only), config.py ([speech] section only, append-only), report.py (Clip fields, append-only), probe.py (preflight prefers ffmpeg-full when PATH build lacks libass), tests/test_captions.py, tests/test_facecam.py, tests/test_speech.py. NOT scoring.py / video_signals.py

- 04-01 executor: vision.py (new), README.md, LICENSE, NOTICE, CHANGELOG.md, tests/test_vision.py; the `--vision` flag (cli.py append-only: post-run vision apply until the pipeline hook is wired). NOT scoring/probe/render/pipeline internals

## Phase nodes
- 01-core (steps 1–4) — DONE 2026-11-12, see phases/01-core/01-01-SUMMARY.md (audio-only; `pipeline.run()` + CLI + render work; cache at .clipanything/<id>/signals.npz; Signals.arrays raw, scoring normalises)
- 02-video (steps 5–6) — DONE 2026-11-12, see phases/02-video/02-01-SUMMARY.md (video.motion/cut/flash/cx/cspread in signals.npz; cropplan.py → follow crop expression; HDR tone-map via scale colour management on ffmpeg ≥ 8; --crop follow|center)
- 03-speech-facecam (7–8) —
- 04-vision-readme (9–10) —

## Executor log (one line each)
- 2026-11-12 01-01 executor: steps 1–4 done, 4 commits (b190f21 e403892 3562d30 52534fb), 21 tests green, ruff clean; audio ≈ 4 s/hour; next: 02-video adds video.motion/video.cut/video.cx into Signals.arrays (scoring already consumes video.motion + video.cut)
- 2026-11-12 02-01 executor: steps 5–6 done, 3 commits (d9b3e8b 20e3621 c96f489), 31 tests green, ruff clean; analysis 24–54 s/hour (decode-bound); next: 03-speech-facecam appends `ass=` after scale in render.build_graph and vstack over the follow crop; phase 4 must tune motion saturation + menu/intro false positives seen on real footage
