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
- detector 2026-11-12 (02-02): COD2 40-min match top-10 duds 3 → 1, precision@10 0.30 → 0.70 (19 labelled spans); floor = max(0.2, 0.35·best), extractor v4 (cuts are not motion); Persona 3 RPG opening (no bursty action) still 7/10 duds — file-relative scores, needs an absolute action floor (phase 4). Video extractor 0.26 ms/frame (+still/stroke)

- inputs 2026-11-12 (02-03): 3 h synthetic (320x180 5 fps) dry-run 21 s, peak RSS 384 MiB, no leftovers; 74 min + 40 min as one session 92 s; iPhone 4K HLG 25 s (APAC track skipped); 3014x1568@60 VFR no-audio screen recording 3/3 clips; 15-min analysis checkpoints, resume verified
- speech/facecam (M1 Max, base.en int8): model load 0.9 s once; 20 s clip with speech 1.4 s (≈ 14x realtime), silent 0.05–0.15 s; facecam detect 1.3 s/file; captioned 20 s clip render 7.2 s (1 worker), facecam layout 3.2 s

## File ownership right now
(03-01 released)

- 04-01 executor: vision.py (new), README.md, LICENSE, NOTICE, CHANGELOG.md, tests/test_vision.py; the `--vision` flag (cli.py append-only: post-run vision apply until the pipeline hook is wired). NOT scoring/probe/render/pipeline internals

## Phase nodes
- 01-core (steps 1–4) — DONE 2026-11-12, see phases/01-core/01-01-SUMMARY.md (audio-only; `pipeline.run()` + CLI + render work; cache at .clipanything/<id>/signals.npz; Signals.arrays raw, scoring normalises)
- 02-video (steps 5–6) — DONE 2026-11-12, see phases/02-video/02-01-SUMMARY.md; 02-02 detector quality DONE 2026-11-12, see 02-02-SUMMARY.md (agreement score, soft z, static-card penalty via video.still/stroke, edges, min_score floor = --count is a max; scripts/eval.py + labels outside the repo) (video.motion/cut/flash/cx/cspread in signals.npz; cropplan.py → follow crop expression; HDR tone-map via scale colour management on ffmpeg ≥ 8; --crop follow|center)
- 02-03 inputs — DONE 2026-11-12, see phases/02-video/02-03-SUMMARY.md (inputs.py: file/folder/many → one session, creation-time order, clips never cross a file, ≤ 90 s files ranked as whole files; `--audio-track auto|all|game|mic|N` with amix + roles; no-audio/vertical/4:3/21:9/HDR-untagged/no-index/.ts/webm/av1/prores fixtures; `--resume` from <stage>.partial.npz)
- 03-speech-facecam (7–8) — DONE 2026-11-12, see phases/03-speech-facecam/03-01-SUMMARY.md (speech.py on chosen clips only; captions.py word-synced ASS, sidecar .ass always, burned only with libass; facecam.py static+textured corner + Haar; render ladder full→no captions→no facecam; preflight prefers keg-only ffmpeg-full)
- 04-vision-readme (9–10) — step 9 + README/packaging DONE 2026-11-12, see phases/04-vision-readme/04-01-SUMMARY.md (vision.py stub-tested, real model unverified; `--vision` applied post-run in cli.py until pipeline.py gets the 3-line hook; README tuning numbers = 02-02 placeholders; demo.gif pending)

## Executor log (one line each)
- 2026-11-12 01-01 executor: steps 1–4 done, 4 commits (b190f21 e403892 3562d30 52534fb), 21 tests green, ruff clean; audio ≈ 4 s/hour; next: 02-video adds video.motion/video.cut/video.cx into Signals.arrays (scoring already consumes video.motion + video.cut)
- 2026-11-12 02-01 executor: steps 5–6 done, 3 commits (d9b3e8b 20e3621 c96f489), 31 tests green, ruff clean; analysis 24–54 s/hour (decode-bound); next: 03-speech-facecam appends `ass=` after scale in render.build_graph and vstack over the follow crop; phase 4 must tune motion saturation + menu/intro false positives seen on real footage
- 2026-11-12 02-02 executor: 3 commits (cbe9f49 ef5ecb6 c2166e7), full pytest 80 passed, lobby+agree fixtures, eval harness; COD duds 3→1; Persona unsolved (7/10 duds, cutscenes+menus carry audio×motion agreement); next: phase 4 calibrates an absolute floor across games, round-start text (loud onsets + cuts) still passes
- 2026-11-12 04-01 executor: vision.py + README/NOTICE/CHANGELOG + packaging done, 5 commits (7e97699 ae07807 2b2de1c 8dd6b13 5b42047), 11 vision tests green, wheel from clean HEAD runs the synthetic end to end with stub Ollama (titles, slugs) and without (one warning); next: pipeline.py owner adds the pre-render vision hook (see summary), 02-02 fills README placeholders, main session captures assets/demo.gif
- 2026-11-12 03-01 executor: steps 7–8 done, commits ffb7e05 (+ fixture follow-up), 17 new tests green, ruff clean; brew ffmpeg-full installed (keg-only) and auto-picked; Whisper base.en cached in ~/.cache/huggingface; no real VOD → Whisper/facecam accuracy unverified; pure HEAD fails 5 scoring tests (02-02 floor vs synth truth) — not touched
- 2026-11-12 02-03 executor: inputs done, 2 commits (a651bbd 480f5ca), 18 tests green + opt-in 3 h test, ruff clean; signals bit-identical to HEAD; next: 02-02/phase 4 per-file edge rule in scoring (sessions run with edge_s=0), raw-dB tie-break for whole-file candidates, 3 scoring tests already red under the min_score floor (deferred-items.md)
