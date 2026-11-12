# Clip Anything

## What This Is

A free, open-source, fully local command-line tool that turns a long gameplay recording (PS5/Xbox capture, OBS recording, stream VOD; 1–10+ hours) into the top N vertical 9:16 highlight clips of 15–45 s with burned-in captions, plus a JSON report. Built for gamers and streamers who record hours and post seconds, launching under Ship at Midnight on Sunday 2026-11-15 at midnight, timed for the GTA 6 launch on 2026-11-19.

## Core Value

It finds the ACTION: chases, crashes, explosions, shootouts, near-misses, with zero speech required. Existing open-source clippers pick moments from the transcript; gameplay highlights often have no talking. If everything else fails, `clip-anything video.mp4` must still output clips that contain the loud, fast moments.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] One command: `clip-anything <video>` → `./clips/` with N vertical clips + report.json, no accounts, no network
- [ ] Action detection from audio energy/onsets + loudness vs rolling baseline + visual motion + scene cuts, per 0.5 s window, normalised and weighted (config file for weights)
- [ ] Peak picking → windows with build-up (60% before / 40% after), snapped to quiet points or cuts, de-duplicated, clamped to --min/--max
- [ ] Render: 9:16 crop that follows the action (smoothed centre of motion, no jitter), 0.3 s fades, H.264 veryfast CRF 20, AAC
- [ ] Captions: word-synced burned-in (ASS) only when speech exists; speech excitement as bonus weight only
- [ ] Facecam: detect a static corner region with a face; stack facecam above gameplay
- [ ] Optional local vision re-rank via Ollama (score 1–10 + 4–6 word title); degrades silently without Ollama
- [ ] Works on a normal laptop CPU: a 1-hour video analyses in a few minutes; never decodes full-res more than needed (audio + 320px/5fps proxy)
- [ ] `uvx clip-anything` and `pipx install clip-anything` both work; ffmpeg checked at start with install help
- [ ] Synthetic test video generator + unit tests for scoring/peaks + end-to-end test that injected bursts are picked
- [ ] Library-first: `clip_anything.pipeline.run()` is importable with no global state, so a hosted version can wrap it later
- [ ] Works for every way people record (owner 2026-11-12: "not just GTA 6, everything; cover all cases"): PS5/Xbox/Switch captures (many short clips or one long file, HEVC/HDR), capture cards, OBS mkv/VFR with separate mic+game audio tracks, ShadowPlay/Steam recordings, Twitch/YouTube VOD downloads, phone screen recordings (vertical, HDR), and action/sports footage; a folder of files is one session; one test fixture per source
- [ ] README with hook, install, how it differs from transcript-based clippers, roadmap; MIT

### Out of Scope

- Hosted/web version — later; v1 is local only (owner: "local, free, open source, hosted later")
- Uploading/posting to TikTok/Shorts/Reels — out of v1; users post the files
- GPU requirement — optional only; CPU must work
- Transcript-first moment picking — explicitly the thing we are NOT doing
- Perfect completeness — a demo-able v1 by Saturday night beats features

## Context

- Owner's brand: Ship at Midnight (shipatmidnight.dev), sibling products Mock Anything, Debug Anything, Agent Theatre, Standup Fight. Naming pattern "X Anything". Name checked 2026-11-12: `clip-anything` free on PyPI, npm scope and GitHub.
- Machine: Apple M1 Max, Python 3.11 + uv present, ffmpeg 9 present, Ollama NOT installed (vision step must be optional).
- Owner tests on real GTA 5 footage; GTA 6 not out yet. Weights must be tunable via a config file.
- Draft execution notes already in `.planning/GRAPH.md` (rules, layout, CLI contract, build order) and `.planning/phases/01..04/*-PLAN.md`.

## Constraints

- **Timeline**: demo-able v1 by Saturday 2026-11-14 night; ship Sunday 2026-11-15 midnight — the GTA 6 window is the whole point
- **Tech stack**: Python 3.11+, ffmpeg external binary, lean deps (numpy, scipy, opencv-python-headless, faster-whisper lazy/optional, rich); no torch at import
- **Privacy**: fully local; no telemetry; only optional localhost Ollama
- **Licence**: MIT; "a free, non-commercial passion project by an independent developer"
- **Quality**: synthetic test video + unit tests; commit after each working step

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Action signals, not transcript, are the core | Gameplay highlights have no talking; that's the wedge | — Pending |
| Analysis on 16 kHz mono audio + 320px/5fps proxy | Hours-long inputs must analyse in minutes on CPU | — Pending |
| Library-first pipeline, thin CLI | Hosted version later without a rewrite | — Pending |
| Vision re-rank optional via Ollama | Ollama not on every machine; must degrade silently | — Pending |
| Every recording source is a first-class input | Users record on consoles, cards, OBS, phones; a tool that only takes one clean mp4 fails most people | — Pending |

---
*Last updated: 2026-11-12 after initialization*
