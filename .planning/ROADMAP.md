# Roadmap: Clip Anything

## Overview
Hard deadline: demo Sat 2026-11-14 night, ship Sun 2026-11-15 midnight (GTA 6 launches 2026-11-19). Audio-first core gives a demo-able product by end of Phase 1; every later phase is a layer that can be cut. Cut order if time runs short: Ollama, facecam, captions, follow-crop (ship centre crop).

## Phases
- [ ] **Phase 1: Core engine** - One command turns a video into centre-crop vertical clips picked by audio action, plus report.json
- [ ] **Phase 2: Video signals + follow crop** - Motion and cuts join the score; crop follows the action
- [ ] **Phase 3: Captions + facecam** - Word-synced captions when speech exists; auto facecam stack
- [ ] **Phase 4: Vision re-rank + tuning** - Optional Ollama re-rank and titles; tuned on real GTA 5 footage; README drafted
- [ ] **Phase 5: Launch gate** - Clean-machine install, TestPyPI dry run, final README/LICENSE, demo from tagged commit

## Phase Details

### Phase 1: Core engine
**Goal**: A user runs `clip-anything video.mp4` and gets postable vertical clips of the loudest, fastest moments with a JSON report, fully local.
**Depends on**: Nothing (first phase)
**Requirements**: SETUP-01, SETUP-02, SETUP-03, SETUP-04, DETECT-01, DETECT-04, DETECT-05, RENDER-01, RENDER-03, RENDER-04, LAUNCH-01, LAUNCH-03
**Success Criteria** (what must be TRUE):
  1. `clip-anything synthetic.mp4` writes `./clips/` with N 1080x1920 mp4s and `report.json`, with no network
  2. Every injected audio burst in the synthetic video lands in a top clip, with a music bed present, and no two clips show the same moment (e2e test passes)
  3. With ffmpeg missing or too old, the tool exits 3 with install help before any analysis; a missing `ass` filter yields one warning
  4. Re-running with a different `--count` or weights finishes in seconds from cache; `--dry-run` writes the report without rendering; one failing clip does not stop the others
  5. A progress UI shows probe, audio, score, render N/N stages on stderr; memory stays flat on a long input (chunked pipes)
**Research handled**: P1 rolling-baseline + flux, P2 proxy timing, P3 NMS/min gap, P4 streaming, P6 preflight, P10 60/40 + snap + fades after snap; benchmark speed on 1 h file and record in GRAPH.md
**Plans**: TBD

### Phase 2: Video signals + follow crop
**Goal**: Quiet games and non-audio action are detected, and the 9:16 crop follows the action without jitter.
**Depends on**: Phase 1
**Requirements**: DETECT-02, DETECT-03, DETECT-06, RENDER-02
**Success Criteria** (what must be TRUE):
  1. A synthetic video with motion bursts but no loud audio still yields clips of those bursts; a loud static scene still yields audio clips
  2. Weights set in `--config` change the ranking, with CLI > config > defaults precedence
  3. On a VFR variant, clip boundaries land within 0.25 s of the injected bursts
  4. Rendered crop visibly tracks the action smoothly (no jitter), and falls back to centre crop when motion is diffuse
**Research handled**: spike crop expression cost at about 90 terms and per-frame x evaluation on ffmpeg 9 (fallback sendcmd); P5 HDR tone-map or warning; P8 edge masking/deadband; P9 two-signal agreement for menus/loading
**Plans**: TBD

### Phase 3: Captions + facecam
**Goal**: Clips with speech get readable burned-in captions, and streamer facecams are stacked above gameplay automatically.
**Depends on**: Phase 2
**Requirements**: CAPT-01, CAPT-02, CAPT-03, CAPT-04
**Success Criteria** (what must be TRUE):
  1. With the `[captions]` extra, a clip with speech shows word-synced captions at 62-70 % height; clips without speech have none; `--no-captions` skips all of it
  2. The Whisper model downloads only after an explicit TTY prompt or `--download-models`; without the extra, one clear line explains captions are skipped
  3. Loud/excited speech nudges candidate ranking without filtering any clip
  4. `--facecam auto` stacks a detected corner facecam above gameplay; console captures or low confidence leave it off, recorded in report.json
**Research handled**: P6 libass fallback (warn + uncaptioned for v1; ffmpeg-full path lookup), P7 captions on spans only, P11 facecam false positives (static + face in 50 % of 30 samples), P14 no silent download; spike Haar on real facecams
**Plans**: TBD

### Phase 4: Vision re-rank + tuning
**Goal**: Optionally better ranking and titles via local Ollama, and weights tuned so real GTA 5 footage yields good clips.
**Depends on**: Phase 3
**Requirements**: LAUNCH-02
**Success Criteria** (what must be TRUE):
  1. With Ollama and a VL model, `--vision` re-ranks (0.7 action / 0.3 vision) and adds 4-6 word titles to the report
  2. Without Ollama, `--vision` degrades silently and output is unchanged
  3. On real GTA 5 footage, the top clips contain the action; tuned default weights committed
  4. README draft, measured speed numbers, NOTICE and disclaimer exist (feeds LAUNCH-04)
**Research handled**: P9 safety-net re-rank, P18, L2 claim only what was tested, L3 nominative GTA use + disclaimer; Ollama via stdlib urllib on 127.0.0.1
**Plans**: TBD

### Phase 5: Launch gate
**Goal**: A stranger can install and run it from a clean machine, and the demo is recorded from a tagged commit.
**Depends on**: Phase 4
**Requirements**: LAUNCH-04
**Success Criteria** (what must be TRUE):
  1. `uvx clip-anything video.mp4` works in a fresh venv, with and without ffmpeg (clear help when missing)
  2. TestPyPI dry run installs and runs; GitHub wheel fallback exists if trusted publishing fails
  3. README, LICENSE (MIT), NOTICE and passion-project line are final and claim only tested formats
  4. GTA 6 date re-checked on 11-14 and 11-15; demo recorded; shipatmidnight.dev updated the same day
**Research handled**: L1 date, L3 content policy page, L6 PyPI/clean-machine
**Plans**: TBD

## Progress
| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Core engine | 0/1 | Not started | - |
| 2. Video signals + follow crop | 0/1 | Not started | - |
| 3. Captions + facecam | 0/1 | Not started | - |
| 4. Vision re-rank + tuning | 0/1 | Not started | - |
| 5. Launch gate | 0/0 | Not started | - |
