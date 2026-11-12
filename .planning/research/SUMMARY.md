# Project Research Summary

**Project:** Clip Anything
**Domain:** Local, open-source gameplay/stream highlight clipper (long recording in, vertical clips out)
**Researched:** 2026-11-12
**Confidence:** MEDIUM (stack facts HIGH, verified live; competitor behaviour and detection tuning MEDIUM)

## Executive Summary

Clip Anything sits in a market where every paid clipper is cloud, account and credit based, and every open-source clipper is either transcript-first (ClipsAI, FunClip, SupoClip) or hard-codes per-game HUD/OCR/YOLO detectors (Auto-clipper, VPCLIPS, WatchDog, EZClips). Nothing found combines audio onsets, loudness-vs-rolling-baseline, motion and scene cuts as a game-agnostic, local, one-command CLI. That is the wedge, and it matters most on GTA 6 day one, when no game profile or trained model exists for any competitor. Absence was "not found", not proven; Reddit/Steam/Discord voices were not retrievable.

Recommended approach: a library-first Python pipeline (`pipeline.run()`, thin typer CLI, events instead of prints). It streams a 16 kHz mono audio pipe and a 320 px / 5 fps gray video pipe from ffmpeg and keeps only raw per-0.5 s signals (about 3 MB for 10 h). Scoring is a robust-normalised weighted mix with an informativeness gate and a soft-max, then peak picking, build-up windows (60/40), snapping and NMS. Rendering is one ffmpeg graph per clip with a smoothed action-following crop. Heavy or optional parts (Whisper, Ollama, facecam, captions) degrade; they never block a clip.

Main risks: (1) ffmpeg capability. Homebrew `ffmpeg` 9.0.2 on the owner's own machine has no libass, so captions break on a stock install. (2) Real-footage tuning: constant radio/music (GTA), menus and loading screens, and no GTA 6 footage to test on. (3) Launch-week process: PyPI publish, clean-machine `uvx` test, GTA trademark wording, date uncertainty. Mitigations are in the phase plan below.

## 1. Competitor Gap Table (what Clip Anything owns)

| Gap | Closest competitor | Their shortfall | Clip Anything position |
|-----|--------------------|-----------------|------------------------|
| Action with no speech, any game | Eklipse (cloud, game-aware); clipforge (audio only) | Eklipse: paywall, quality drops off its game list; clipforge: 10 min cap, no motion | **Core wedge** |
| Day-one coverage of a brand-new game | None | Profile/model tools need training or templates | Generic signals, no profile |
| Fully local, no account, one command | Auto-clipper (Flask UI, weights, per-game) | Multi-step install | `uvx clip-anything video.mp4` |
| Hours-long VOD on CPU | Auto-clipper (~28x realtime, pixel rules only) | Needs per-game rules | Target 3-5 min per hour of footage |
| No watermark/expiry/credits | Eklipse, Opus free tiers | Watermark, 720p, 14-day expiry, credits on INPUT minutes | Free by construction |
| Action-following 9:16 crop | None found | ClipsAI/SupoClip follow faces/speakers only | Differentiator, highest risk |
| Facecam stack, automatic | StreamLadder, Auto-clipper | Manual layout presets | Auto-detect, opt-in |
| Explainable scoring | None | Opaque 0-100 "virality" | Per-signal scores + tunable weights in report.json |

What users hate (drives the polish bar): Opus "waits for speech pauses and cuts late, skipping the action"; Eklipse "captures the final kill, misses the buildup", unusable clips, days of waiting; Opus stalls silently; ClipsAI needs HF token + WhisperX + pyannote; SupoClip needs Docker plus AssemblyAI and LLM keys. Athenascope (free, $2.5M seed, 3 games) is defunct; reason unknown, do not cite one.

## 2. "Seamless and Polished" Decisions

**Postable without editing (table stakes):**
- 1080x1920 H.264 yuv420p + AAC, `+faststart`, even dimensions (plays on phones/QuickTime, not just VLC).
- Clip starts BEFORE the moment (60/40 split, snapped to quiet point or cut, fades added after snap) and ends on the decay plus about 1.5 s. This directly fixes the top Eklipse/Opus complaint.
- No near-duplicates (NMS, min 30 s gap between peaks); return fewer than N rather than pad.
- Crop that never jitters: median + One-Euro + 6% deadband + pan-speed cap; fall back to centre crop when confidence is low or motion is global (camera turn). A plain centre crop beats a jittery follow crop.
- Captions only when speech exists, positioned about 62-70% height so they never cover the HUD or facecam. Silent gameplay gets none, by design.
- Deterministic names `<stem>_01_<mm-ss>.mp4`, no overwrite without `--force`, atomic writes (`.part` then rename) so a crash never leaves a half clip that looks valid.

**Zero-setup install:**
- Core deps only: numpy, scipy, opencv-python-headless, rich, typer. No torch, no librosa, no PySceneDetect, no moviepy. About 100-130 MB first `uvx` run, cached after. `--help` and the ffmpeg check must run without importing scipy/cv2.
- Whisper is an extra; Ollama is called with stdlib `urllib`; both lazy and optional.
- ffmpeg is the one external requirement: preflight checks binary, version (>=5, syntax switch at 7), `libx264`, `aac`, and the `ass` filter, then prints platform install help and exits 3. On macOS also look in `/opt/homebrew/opt/ffmpeg-full/bin` automatically.

**Must never fail silently or late:**
- Every capability problem is caught in preflight, not 20 minutes into analysis, and each degradation is a visible one-line message plus a `warnings[]` entry in report.json.
- Render fallback ladder: full graph, then drop captions, then drop facecam, then centre crop. A clip is `failed` only after all four. One bad clip never kills the run; exit 0 if at least one clip is ok.
- Progress to stderr with real ETA (seeded from last run's timings), JSON to stdout, no traceback for expected errors (exit 2 bad input, 3 ffmpeg missing).
- No implicit network use. Whisper model download is the only non-localhost network step: prompt once on a TTY, never in `--json` or non-interactive runs (skip captions with one clear line), `--yes` to accept. Resolves a conflict between STACK (prompt) and PITFALLS (never implicit): prompt on TTY only.
- Report shows what was decided and why: facecam off/on with confidence, HDR warning, audio-flat fallback to motion, snap moves.

## 3. Stack and Architecture Decisions

**Stack (HIGH, versions checked against PyPI and local ffmpeg 9.0.2):**
- Python `>=3.11`; ffmpeg/ffprobe external, never bundled (bundling a GPL build would pull GPL obligations).
- numpy `>=2.0`, scipy `>=1.13` (only `signal` and `ndimage`, lazy), opencv-python-headless `>=4.10,<5` (5.0 shipped 2026-07-02, API unverified; launch on 4.x), rich, typer, hatchling.
- Audio features via numpy FFT (flux, rms_db, low-band ratio), not librosa 1.0.1 (needs Python >=3.12, drags numba). Scene cuts via own 32-bin histogram delta, not PySceneDetect (hard-depends on non-headless opencv, collides).
- Motion = `absdiff` on the proxy; no optical flow over the full file.
- Crop: `crop` with a nested piecewise-linear `t` expression, passed via `-/filter_complex file` (ffmpeg >=7) or `-filter_complex_script` (older). Not `zoompan`, not `sendcmd` unless over 300 keyframes.
- Facecam: Haar (ships in wheel, zero download); YuNet only if Haar misses on real footage.
- Captions: libass `ass` filter with `cwd=tmp` bare-filename trick (kills Windows escaping). Whisper `base.en` int8 CPU on candidate spans only.
- Extras: pick ONE name, `captions` (STACK) vs `speech` (ARCHITECTURE) conflict. Decision: `clip-anything[captions]`.

**Architecture (MEDIUM, design sound, not benchmarked):**
1. `config`/`probe`/`cache`/`events`/`report`: layered Options (CLI > file > defaults), ffprobe, content-id cache, event stream, schema-versioned Report.
2. `audio_signals` and `video_signals`: stateful chunk extractors, two ffmpeg pipes in two threads, raw signals stored (normalisation happens in scoring, so re-weighting never invalidates cache).
3. `scoring`: pure numpy. Rolling median/MAD normalisation, informativeness gate (quiet-game fix), mean+max mix, find_peaks, windowing, snap, NMS.
4. `cropplan`, `facecam`, `captions`, `render`: one graph, one encode per clip, fallback ladder.
5. `speech`, `vision`: optional, candidate spans only (top 3N), bonus/re-rank only, never filter.
6. `cli`: only module that prints or exits.
- Cache beside the video in `.clipanything/<id>/` with 10-media-minute segments for resume; `Cache` is a Protocol so a hosted wrapper swaps in object storage. Rule: only probe/audio/video/render/vision/speech touch subprocess or network.

## 4. Pitfalls Mapped to Phases

Phase key: 1 core, 2 video + crop, 3 speech/captions/facecam, 4 vision + README, L launch.

| # | Pitfall | Prevention | Phase |
|---|---------|------------|-------|
| P1 | Constant radio/music flattens audio | Rolling-baseline deviation, spectral flux, informativeness gate; music-bed + bursts synthetic test | 1, 2 |
| P2 | VFR OBS files drift | PTS-based time via constant-rate proxy; VFR fixture, peak within 0.25 s | 1, 2 |
| P3 | Ten clips of one moment | NMS, 30 s min gap, return fewer | 1 |
| P4 | Memory on 10 h files | Stream chunks, keep features only, rolling normalisation | 1, 2 |
| P5 | HEVC/10-bit/HDR grey output | Probe transfer, analyse via proxy, warn if no tone-map | 1, 2 |
| P6 | ffmpeg missing/old/no libass | Preflight on filters/encoders/version, ffmpeg-full path, degrade | 1, 3 |
| P8 | Crop jitter / follows HUD | Mask edges, smooth, deadband, centre fallback | 2 |
| P9 | Menus, loading, alerts score high | Two-signal agreement rule, fade detection, vision re-rank safety net | 2, 4 |
| P10 | Clip starts at the peak | 60/40, snap, fades after snap | 1, 2 |
| P11 | Facecam false positive | Static + face in 50% of 30 samples, default off below confidence | 3 |
| P14 | Silent Whisper download | TTY prompt only | 3 |
| L1 | GTA 6 date (2026-11-19, PS5/Xbox) unconfirmed this week | Check Rockstar channels 11-14 and 11-15; copy survives a slip | L |
| L2 | Console formats untested | README claims only what was tested | L, 4 |
| L3 | Trademark | Nominative use, disclaimer, no GTA in names/logos | L, 4 |
| L6 | PyPI/trusted-publishing, clean-machine | TestPyPI Friday, fresh-venv `uvx` test, GitHub wheel fallback | L |

## Implications for Roadmap

Keep the four drafted phases (matches `.planning/phases/01..04`) plus a launch gate. Build order inside phases follows ARCHITECTURE steps 1-10.

### Phase 1: Core engine, audio path, centre-crop render
**Rationale:** Smallest slice that satisfies the Core Value ("loud fast moments in a clip") and is demo-able end to end.
**Delivers:** config/probe/cache/events/report, streaming audio signals, scoring + peaks + windows + NMS, `--dry-run`, centre-crop render with fades, preflight, CLI, synthetic video generator.
**Addresses:** one command, JSON report, config weights, no-duplicates, build-up windows.
**Avoids:** P1, P2 (proxy), P3, P4 (audio), P6 (preflight), P10, P12, P15, P16, P21.

### Phase 2: Video signals and action-following crop
**Rationale:** Motion fixes quiet games and false positives (agreement rule); crop depends on `video.cx`.
**Delivers:** motion/cut/cx extraction, informativeness gate, `cropplan` + expression crop, HDR tone-map or warning, VFR fixture.
**Avoids:** P5, P8, P9, P19.

### Phase 3: Captions, facecam
**Rationale:** Optional layers; only after the base is solid. Captions matter least for silent gameplay.
**Delivers:** speech on top-3N spans, ASS captions, libass fallback, facecam auto-detect + stack, Whisper consent flow.
**Avoids:** P6 (caption fallback), P7, P11, P14.

### Phase 4: Vision re-rank, README, tuning
**Delivers:** Ollama re-rank + titles (silent skip), tuning pass on real GTA 5 footage, README with measured speed, NOTICE/THIRD_PARTY, disclaimer.
**Avoids:** P18, L2, L3, L5.

### Phase L: Launch gate (Sat 11-14 night to Sun 11-15 midnight)
Clean-machine `uvx` test with and without ffmpeg, TestPyPI dry run, demo recorded from tagged commit, GTA date recheck, update shipatmidnight.dev same day.

### Phase Ordering Rationale
Audio before video because audio alone gives the demo (clipforge claims about 80%); crop and facecam are the riskiest and are placed after a working centre-crop baseline so a cut at Saturday night still ships. If time runs out, cut order: Ollama, facecam, captions, then follow-crop (ship centre crop).

### Research Flags
Need deeper research or a spike during planning:
- **Phase 2:** crop expression cost at 90 terms and per-frame `x` evaluation on ffmpeg 9; centroid quality on GTA footage; tone-map availability.
- **Phase 3:** libass fallback decision (Pillow overlay vs warn-only); Haar on real facecams.
- **Phase L:** Rockstar/Take-Two content policy page.

Standard patterns (skip research-phase): Phase 1 (streaming pipes, find_peaks, argv-list subprocess), Phase 4 (HTTP to Ollama, README).

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Versions and ffmpeg graphs checked live; speed numbers and Ollama tags are not |
| Features | MEDIUM | Open-source READMEs fetched; vendor claims biased; no Reddit/Steam voices |
| Architecture | MEDIUM | Sound design, not benchmarked; several VERIFY items |
| Pitfalls | MEDIUM | Wheel/licence facts live; detection and ffmpeg behaviour from practice |

**Overall confidence:** MEDIUM

## Open Items to Verify

- Stock `brew ffmpeg` lacks libass: confirm `ffmpeg-full` works on this machine and the auto-path lookup picks it up. Decide the no-libass caption path (recommend warn + uncaptioned for v1, Pillow overlay stretch).
- Segment-resume boundary match (1e-4) versus an uninterrupted run.
- Crop `x` expression: per-frame evaluation, comma escaping, parse cost at about 90 terms (fallback `sendcmd` 10 Hz).
- opencv: Haar cascade ships in the headless wheel; pin `<5`; PyAV on 3.11 resolves an older version.
- Speed target (3-5 min per hour) is unmeasured: benchmark 1 h and 10 h on the M1 Max and write numbers into GRAPH.md.
- Real OBS VFR file, real PS5/Xbox capture formats and HDR, multi-track audio: none tested; claim only what is tested.
- Windows: untested, list as best effort; unit-test the path escaper.
- Pricing/competitor facts conflict across sources (Eklipse, Medal, Opus); do not quote prices in launch copy without checking live pages. Manual Reddit/Discord pass before final positioning copy.
- GTA 6 date and content policy re-check on 11-14 and 11-15.
- Weights are starting points; tune on real GTA 5 footage (synthetic test proves plumbing, not taste).

## Sources

Primary (HIGH): PyPI JSON API 2026-11-12 (versions, licences, wheels); local ffmpeg 9.0.2 (`-buildconf`, `-filters`, executed filter graphs); GitHub READMEs for ClipsAI, FunClip, SupoClip, Auto-clipper, VPCLIPS.
Secondary (MEDIUM): Eklipse engineering blog, twoaveragegamers Opus review, dev.to clipforge post, Yahoo Finance Athenascope launch, tomsguide/gamesradar/pcgamesn on GTA 6.
Tertiary (LOW): Trustpilot-derived summaries, Medal/ShadowPlay/PS5 snippets, Ollama tag lists, faster-whisper speed figures. Full lists in the four research files.

---
*Research completed: 2026-11-12*
*Ready for roadmap: yes*
