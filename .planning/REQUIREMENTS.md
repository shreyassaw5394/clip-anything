# Requirements: Clip Anything

**Defined:** 2026-11-12
**Core Value:** It finds the ACTION in long gameplay recordings with zero speech required, fully local, one command.

## v1 Requirements

### Input & setup (SETUP)
- [ ] **SETUP-01**: User runs `clip-anything <video>` on an mp4/mkv (H.264 or HEVC, 1–10+ h, VFR allowed) and gets `./clips/` with N vertical clips + `report.json`, with no account and no network
- [ ] **SETUP-02**: On start, the tool checks ffmpeg/ffprobe (≥ 5.0) and prints OS-specific install help if missing (exit 3); it probes for the `ass` filter and warns once if captions can't be burned, pointing at `ffmpeg-full`
- [ ] **SETUP-03**: `uvx clip-anything` and `pipx install clip-anything` work on Python 3.11–3.13; core deps are numpy, scipy, opencv-python-headless, rich only; Whisper is the `[captions]` extra, never imported at startup
- [ ] **SETUP-04**: Memory stays bounded on a 10-hour file: audio and the 320 px / 5 fps proxy stream from ffmpeg pipes in chunks; full-res video is decoded only when rendering a chosen clip

### Detection (DETECT)
- [ ] **DETECT-01**: Audio signals per 0.5 s window: RMS, spectral-flux onsets, loudness vs a rolling median/MAD baseline (60–120 s), each normalised 0..1; a constant music bed or constantly loud game still yields the burst moments
- [ ] **DETECT-02**: Visual signals from the proxy: motion intensity (frame diff), scene cuts (histogram delta that rejects single-frame flashes), flash score
- [ ] **DETECT-03**: Score = weighted combination with an informativeness gate (a flat/silent signal is zeroed) so quiet games fall back to motion and static-but-loud scenes fall back to audio; weights live in a config file (`--config`) with CLI > config > defaults precedence
- [ ] **DETECT-04**: Peaks → windows with build-up (60 % before / 40 % after), snapped to quiet points or cuts, de-duplicated so no two clips show the same moment, clamped to `--min`/`--max` (15–45 s default), top `--count` (10 default)
- [ ] **DETECT-05**: Signals are cached next to the video (`.clipanything/<id>/signals.npz`) so a re-run with new weights or count skips decoding and finishes in seconds; `--no-cache` bypasses
- [ ] **DETECT-06**: Timing uses the stream's real timestamps (VFR-safe): every clip boundary and caption time is correct on OBS variable-frame-rate recordings

### Output (RENDER)
- [ ] **RENDER-01**: Each clip is 1080x1920 9:16, H.264 veryfast CRF 20, yuv420p bt709, AAC, faststart, 0.3 s fade in/out; HDR/10-bit sources are tone-mapped (warn, don't crash, if tone-mapping is unavailable)
- [ ] **RENDER-02**: The crop follows the action: centre of motion mass per frame, median-filtered + One-Euro smoothed, dead-band and pan-speed cap, passed to ffmpeg as one piecewise crop expression; falls back to centre crop when motion is diffuse
- [ ] **RENDER-03**: Renders run in parallel bounded by CPU; one failed clip never kills the run; failures walk a fallback ladder (drop captions → drop facecam → centre crop) and are recorded in report.json
- [ ] **RENDER-04**: `report.json` lists rank, score and per-signal breakdown, start/end, title, file path, warnings; `--dry-run` writes the report without rendering; `--json` prints it to stdout

### Captions & facecam (CAPT)
- [ ] **CAPT-01**: With the `[captions]` extra, speech in the chosen clip windows only (never the whole file) is transcribed with word timestamps; burned-in word-synced ASS captions at 62–70 % height (clear of the HUD), 2–4 words per line; clips without speech get no captions; `--no-captions` skips all of it
- [ ] **CAPT-02**: The Whisper model downloads only after an explicit prompt on a TTY (or `--download-models`), never silently; without the extra, captions are skipped with one clear line
- [ ] **CAPT-03**: Speech excitement (shouts, laughter, exclamation words from config) is a small bonus weight on the top 3N candidates only
- [ ] **CAPT-04**: `--facecam auto` detects a static corner region containing a face on sampled proxy frames and renders facecam above gameplay; low confidence → off; console captures report none

### Polish & launch (LAUNCH)
- [ ] **LAUNCH-01**: Rich progress UI (stderr) with stage names and time estimates: probe → audio → video → score → captions → render N/N
- [ ] **LAUNCH-02**: Optional `--vision` re-rank via local Ollama (score 1–10 + 4–6 word title) that degrades silently when Ollama or a VL model is absent; blended 0.7 action / 0.3 vision
- [ ] **LAUNCH-03**: Synthetic test video generator (bursts, motion bursts, music bed, VFR variant) + unit tests for scoring/peaks + end-to-end test that every injected burst lands in a top clip
- [ ] **LAUNCH-04**: README (hook, one-line install, how it differs from transcript-first clippers, options, config, roadmap, MIT, passion-project line), LICENSE + NOTICE, clean-machine `uvx` test, TestPyPI dry run, tuned on real GTA 5 footage before Sunday

## v2 Requirements
- **HOST-01**: Hosted version: queue worker wraps `run()` with object-store cache; upload → clips
- **OUT-01**: Direct posting to TikTok/Shorts/Reels
- **DETECT-07**: Learned scorer trained on logged candidate features
- **CAPT-05**: Caption styles/themes; speaker diarisation

## Out of Scope
| Feature | Reason |
|---------|--------|
| Per-game profiles / HUD OCR | The wedge is game-agnostic; GTA 6 has no profile on day one |
| GPU requirement | CPU must work on a normal laptop |
| Bundling ffmpeg | LGPL/size; check and guide instead |
| 16:9 or square outputs | 9:16 only for v1 |

## Traceability
| Requirement | Phase | Status |
|-------------|-------|--------|
| CAPT-01 | Phase 3 | Pending |
| CAPT-02 | Phase 3 | Pending |
| CAPT-03 | Phase 3 | Pending |
| CAPT-04 | Phase 3 | Pending |
| DETECT-01 | Phase 1 | Pending |
| DETECT-02 | Phase 2 | Pending |
| DETECT-03 | Phase 2 | Pending |
| DETECT-04 | Phase 1 | Pending |
| DETECT-05 | Phase 1 | Pending |
| DETECT-06 | Phase 2 | Pending |
| LAUNCH-01 | Phase 1 | Pending |
| LAUNCH-02 | Phase 4 | Pending |
| LAUNCH-03 | Phase 1 | Pending |
| LAUNCH-04 | Phase 5 | Pending |
| RENDER-01 | Phase 1 | Pending |
| RENDER-02 | Phase 2 | Pending |
| RENDER-03 | Phase 1 | Pending |
| RENDER-04 | Phase 1 | Pending |
| SETUP-01 | Phase 1 | Pending |
| SETUP-02 | Phase 1 | Pending |
| SETUP-03 | Phase 1 | Pending |
| SETUP-04 | Phase 1 | Pending |

**Coverage:** 22/22 mapped
