# Architecture Research

**Domain:** local long-video highlight clipper (signal-based, library-first)
**Researched:** 2026-11-12
**Confidence:** MEDIUM (design from known ffmpeg/numpy/scipy behaviour; not benchmarked. Items marked VERIFY need a spike.)

## System Overview

```
 CLI (typer/rich)  ─┐                      hosted worker (later) ─┐
                    ▼                                             ▼
        clip_anything.pipeline.run(video, Options, on_event, cancel, cache) -> Report
 ┌────────────────────────────────────────────────────────────────────────────┐
 │ probe → [audio ∥ video] → (speech*) → score → (vision*) → plan → render xN │  * optional, degrade
 └──────┬───────────┬───────────┬──────────────────────────────────┬──────────┘
   Cache protocol (DirCache default)      ffmpeg subprocess pipes     ffmpeg subprocess per clip
   .clipanything/<id>/{probe.json, signals.part-*.npz, signals.npz, speech.json, facecam.json, timings.json}
```

Public API (all pure: inputs in, values out, no globals, no prints, no sys.exit):
`probe(path)->MediaInfo` · `analyze(video, opts, ...)->Signals` · `select(signals, opts, speech=None)->list[Candidate]`
· `render_clip(video, clip_plan, opts)->Path` · `run(...)->Report` (= analyze → select → render).
`rescore(video, opts)` = `run` with warm cache: skips decode, re-runs score+render only.

## Component Boundaries

| Component (module) | Owns | Talks to |
|---|---|---|
| `config.py` | `Options` dataclasses, layered merge, validation, `analysis_fingerprint()` | CLI, pipeline |
| `probe.py` | ffprobe → `MediaInfo`; ffmpeg presence check (`FFmpegMissing`) | pipeline |
| `cache.py` | `Cache` protocol + `DirCache`; content id; atomic writes; segment manifest | every stage |
| `audio_signals.py` | stateful `AudioExtractor.feed(int16 chunk)->rows`; ffmpeg PCM pipe | cache, events |
| `video_signals.py` | `VideoExtractor.feed(gray frames)->rows` (motion, cut, cx/cy, corner variance) | cache, facecam |
| `speech.py` | faster-whisper on candidate spans only; word timestamps; excitement bonus | scoring, captions |
| `scoring.py` | normalise, combine, peaks, windows, snap, dedupe. PURE numpy, no I/O | tests, pipeline |
| `cropplan.py` | cx series → smoothed keyframes (pure) | render |
| `facecam.py` | pick static corner rect from variance map + Haar face check on ~12 sampled frames | render |
| `captions.py` | words → ASS file (clip-relative times) | render |
| `render.py` | build ONE filter graph per clip, run ffmpeg, atomic output, fallback ladder | cropplan, captions, facecam |
| `vision.py` | optional Ollama re-rank (127.0.0.1); returns score+title or `None` | pipeline |
| `events.py` | `Event`, ETA estimator (EMA of media-sec per wall-sec) | CLI, hosted |
| `report.py` | `Report` dataclasses, `to_json()`, schema_version | CLI, hosted |
| `cli.py` | arg parsing, rich progress from events, exit codes 0/2/3 | pipeline only |

Rule: only `probe/audio/video/render/vision/speech` touch subprocess/network; `scoring/cropplan/captions/report/config` are pure and unit-tested with synthetic arrays.

## (a) Bounded-memory streaming

- Audio: `ffmpeg -i V -vn -ac 1 -ar 16000 -f s16le -` read in 30 s chunks (960 KB). Extractor keeps only carry-over state (last partial hop, rolling-baseline deque, previous spectrum). Emits 1 row per 0.5 s hop.
- Video: `ffmpeg -i V -an -vf fps=5,scale=320:-2,format=gray -f rawvideo -` read in 150-frame chunks (~9 MB at 320x180). State: previous frame, previous histogram, Welford mean/M2 of 4 corner patches.
- Both run as two parallel ffmpeg processes in two threads. Full-res is never decoded for analysis.
- Output is tiny: 10 h = 72,000 windows x ~10 float32 signals ≈ 3 MB. Peak RAM ≈ chunk buffers + that. No stage holds the file.
- Decision: signals stored RAW (dB, flux, mean abs diff, normalised cx). Normalising to 0..1 is `scoring`'s job, so changing normalisation or weights never invalidates the cache. `Signals.normalised(opts)` returns the 0..1 view.

## (b) Cache and resume

- Content id: `sha256(size || head 1MiB || middle 1MiB || tail 1MiB || ANALYSIS_SCHEMA)[:16]` — O(1) on a 10 h file; survives rename/move. Dir: `<video_dir>/.clipanything/<id>/` (override `--cache-dir`; `--no-cache` = temp dir).
- Cache key for signals = id + `analysis_fingerprint(opts)` = hash of `{hop_s, proxy_fps, proxy_width, extractor_versions}`. Weights/count/min/max/layout are NOT in it, so new weights re-run in seconds.
- Resume inside a long decode: write a segment every 10 media-minutes: `signals.part-0007.npz` + `manifest.json {done_segments, fingerprint}`. On restart, seek (`-ss <seg_start - 5s>` before `-i`) and warm up extractor state on the 5 s overlap, discard overlap rows. At end merge to `signals.npz` and delete parts. (VERIFY: boundary rows match an uninterrupted run within 1e-4.)
- Per-stage artefacts: `speech.json` keyed by (id, span, model); `facecam.json` by id; render outputs are NOT cached (cheap to redo; skip if `clip.mp4` exists and `--resume` and plan hash equal — plan hash stored in a sidecar `.plan`).
- All writes: temp file + `os.replace`. A corrupted/foreign-fingerprint cache entry = cache miss, never error.
- Decision: cache beside the video (user asked), but `Cache` is a Protocol (`get(key)->bytes|None`, `put(key, bytes)`, `segment(key, i)`) so hosted can swap in object storage.

## Data Contracts (Python dataclasses; JSON-serialisable via `dataclasses.asdict`)

```python
@dataclass(frozen=True)
class MediaInfo:  path: str; duration_s: float; width: int; height: int; fps: float
                  has_audio: bool; has_video: bool; rotation: int; size_bytes: int

@dataclass
class Signals:                       # time axis is implicit, window i = [t0+i*hop_s, t0+(i+1)*hop_s)
    hop_s: float                     # 0.5
    t0: float                        # 0.0
    n: int
    duration_s: float
    arrays: dict[str, np.ndarray]    # float32 shape (n,), RAW values; NaN = not measured
    # names: audio.rms_db, audio.flux, audio.onset, audio.loud_rel (dB over rolling 60 s median),
    #        video.motion, video.cut (0/1), video.cx, video.cy (0..1 centre of motion mass, NaN if still)
    meta: dict                       # {fingerprint, extractor_versions, has_audio, has_video}

@dataclass
class Candidate:
    id: int; peak_t: float; score: float          # 0..1 final
    prominence: float
    components: dict[str, float]                  # {"audio":.8,"motion":.4,"cut":0,"speech":0}  (post-weight)
    start: float; end: float                      # after window+snap+clamp
    snap: dict                                    # {"start":"quiet"|"cut"|"none","end":...,"moved_s":float}
    features: dict[str, float]                    # raw signal values at peak (for future learned model)

@dataclass
class Clip:
    rank: int; candidate_id: int; start: float; end: float; duration_s: float
    title: str | None; vision_score: float | None
    layout: Literal["gameplay","facecam_stack"]; captions: bool
    crop: CropPlan                                # {mode:"follow"|"center", keyframes:[[t_rel,x_norm],...]}
    path: str | None; status: Literal["ok","failed","skipped"]; error: str | None; render_s: float | None
```

`Report` JSON (`schema_version: 1`, additive changes only):
```json
{"schema_version":1,"tool":"clip-anything","version":"0.1.0","created":"ISO8601",
 "input":{"path":"","id":"","duration_s":0,"width":0,"height":0,"fps":0,"has_audio":true},
 "options":{ "...fully resolved Options..." },
 "stages":[{"name":"audio","status":"ok|cached|skipped|failed","wall_s":0.0,"detail":""}],
 "warnings":[{"stage":"facecam","code":"no_face","message":""}],
 "candidates_total":0,
 "clips":[ "...Clip objects..." ],
 "signals":{"cache_path":"","names":[],"hop_s":0.5},
 "timings":{"analyze_s":0,"score_s":0,"render_s":0,"media_x_realtime":0}}
```

## (c) Scoring model — decision: robust-normalised weighted mix with soft-max, hand-tuned; learned deferred

Alternatives: raw weighted sum (breaks: loud games drown motion, quiet games score ~0); global z-scores (one explosion skews mean/std); learned model (no labels before Sunday). Decision below, with features logged in `Candidate.features` so a logistic regression can be fit later.

1. **Per-signal robust normalise**, each independently: `z = (x - median) / (1.4826*MAD + eps)` over a rolling 5-min window (local, so a loud level or quiet stretch is judged against itself) blended with global percentiles; then `s = clip(z / z_cap, 0, 1)` with `z_cap = 6`. Audio uses `loud_rel` and `onset`; motion uses `video.motion`; `cut` is a bonus term, not a base.
2. **Informativeness gate (the quiet-games fix)**: per signal compute `spread = p99 - p50` of its raw values; `gate_i = clip(spread / floor_i, 0, 1)` (floor_i in config). A flat/silent/static signal gets gate≈0 so its noise is not amplified by MAD→0, and remaining weights renormalise. A game with no audible peaks falls back to motion; a static-screen loud scene falls back to audio.
3. **Combine**: `base = Σ w_i*gate_i*s_i / Σ w_i*gate_i`; `score = (1-α)*base + α*max_i(gate_i*s_i)`, α = 0.5. The max term lets one strong signal win alone (silent car crash, loud off-screen explosion); the mean term rewards audio+motion agreeing. Cut: `+w_cut` if a cut lies within ±1 s of peak. Speech excitement: `+w_speech * excitement` applied only to top 3N candidates after speech runs (bonus, never required).
4. **Smoothing and peaks**: gaussian smooth σ=1.0 s; `scipy.signal.find_peaks(distance=ceil(min_s/hop), prominence=0.1, height=p90)`.
5. **Windowing (build-up)**: duration `D = clamp(expanded, min, max)` where expanded = span around the peak where smoothed score ≥ 0.35*peak (hysteresis, 2 s gap tolerance) plus lead-in; start = peak − 0.6·D, end = peak + 0.4·D. The 60/40 split is a prior; the span gives variable length.
6. **Snapping**: start snaps to the nearest `video.cut` or local min of `audio.rms_db` within [start−2 s, start+0.5 s] (prefer cut); end snaps within [end−0.5 s, end+2 s] to a quiet point (rms < p30) or cut. Snap must keep `min ≤ D ≤ max` and must not cross the peak; else `snap="none"`.
7. **Dedupe**: sort by score; greedy NMS dropping any candidate whose [start,end] overlaps an accepted clip by >20% of the shorter, or whose peak lies inside it. Take top N. Output ordered by score (rank) but report includes `start` for timeline order.
8. Weights/floors/α/z_cap live in `[scoring]` of the TOML; defaults in code. `--dry-run` prints candidates and exits after step 8.

## (d) Action-following crop

- Source: `video.cx` per 0.5 s window = x-centroid of |frame_t − frame_{t−1}| mass on the 320 px proxy after a 3x3 blur and threshold at p95 of that frame's diff; NaN when total diff < motion floor. Normalised 0..1 across source width.
- `cropplan.make(cx[start:end], hop, src_w, src_h, opts) -> CropPlan` (pure):
  1. Fill NaN by hold-last then hold-next; if >60% NaN → `mode="center"` (x=0.5).
  2. Weight by motion strength; running median (3 s) to kill single-window jumps.
  3. Critically-damped smoother (or One-Euro; pick one: **One-Euro**, min_cutoff=0.4 Hz, beta=0.02) with a deadband of 6% of crop travel and a max pan speed of 25% of source width/s.
  4. Clamp so the crop stays inside the frame: `x ∈ [cw/2, W−cw/2]`.
  5. Decimate to keyframes every 0.5 s (≤ 90 for 45 s) in clip-relative time.
- To ffmpeg: piecewise-linear expression in a filter **script file** (avoids argv/quoting limits):
  `crop=w=ih*{ar}:h=ih:x='{Σ between(t,t_i,t_{i+1})*(x_i+(x_{i+1}-x_i)*(t-t_i)/(t_{i+1}-t_i))}':y=0`
  with x in source pixels. Because input `-ss` is placed before `-i`, filter `t` starts at 0, which equals clip-relative keyframes. VERIFY: expression parse/eval cost at 90 terms (should be negligible), and commas escaped. Fallback if slow: `sendcmd` file at 10 Hz setting crop `x`.

## (e) One filter graph per clip (captions + facecam + fades)

```
ffmpeg -ss S -t D -i V -/filter_complex graph.txt -map [v] -map [a] -c:v libx264 -preset veryfast -crf 20
       -pix_fmt yuv420p -c:a aac -b:a 160k -movflags +faststart -threads T out.part.mp4 && mv
graph (facecam_stack):                        graph (gameplay only: drop split/fc/vstack, crop to 1080x1920)
 [0:v]split=2[g][f];
 [g]crop=w=ih*1080/1312:h=ih:x='<expr>':y=0,scale=1080:1312[gv];
 [f]crop=fw:fh:fx:fy,scale=1080:608[fv];
 [fv][gv]vstack=inputs=2[st];
 [st]ass=cap.ass,fade=t=in:d=0.3,fade=t=out:st=D-0.3:d=0.3,format=yuv420p[v];
 [0:a]afade=t=in:d=0.3,afade=t=out:st=D-0.3:d=0.3[a]
```
- Canvas 1080x1920; facecam band 608 px on top, gameplay 1312 below; captions anchored in the lower third of the gameplay band (ASS `MarginV` set per layout) so they never cover the face.
- Facecam excluded from the gameplay crop is not removed (it stays in the gameplay band too); acceptable v1 trade-off.
- ASS lives in a temp dir with clip-relative times; the `ass=` path is escaped. Fonts: bundle one OFL font and pass `fontsdir=`.
- Fallback ladder on non-zero exit: (1) full graph → (2) drop captions → (3) drop facecam → (4) centre crop, no ass. Each step adds a `warnings[]` entry; only after (4) fails is the clip `status="failed"`.

## Concurrency and errors

- Analysis: 2 threads (audio, video), each one ffmpeg process. Whisper/vision run after scoring, only on top 3N spans (never the whole 10 h).
- Render: `ThreadPoolExecutor(workers = max(1, cpu//4))`, each ffmpeg gets `-threads cpu//workers` (x264 is already multithreaded; more workers than ~3 only adds contention). Workers are threads wrapping subprocesses, so no pickling. `cancel: threading.Event` → terminate children.
- Error classes: `InputError`(→exit 2), `FFmpegMissing`(→3), `StageError(stage)`. Policy: probe failure and both-signals-failed are fatal. Optional stages (speech, facecam, vision) catch everything, append a warning, continue. One clip failing sets that Clip `failed`; others proceed; `run` returns a Report, exit code 0 if ≥1 clip ok else 1.
- Stdout stays clean for `--json` (report to stdout, progress to stderr).

## Config precedence

CLI > config file > defaults. `Options.from_layers(defaults, file_dict, cli_dict)` deep-merges; CLI flags default to `None` (sentinel) so only explicitly-passed flags override. Unknown keys/sections → `InputError` with the key path. Order for file lookup: `--config` > `./clip-anything.toml` > `~/.config/clip-anything/config.toml`. Resolved Options are embedded in the Report (reproducible reruns). Sections: `[analysis]` (cache-affecting), `[scoring]`, `[clips]`, `[render]`, `[speech]`, `[vision]`.

## Progress and ETA

`on_event(Event{stage, kind: "start|progress|done|cached|skipped|warn", done, total, unit, eta_s, message})`. Analysis unit = media seconds; render unit = clips. ETA = remaining / EMA(throughput), throughput seeded from `timings.json` of the last run on this machine (so ETA is useful from second 1), else a default of 60x realtime audio / 25x video. CLI maps events to a rich `Progress` on stderr (one bar per stage: probe → audio ∥ video → score → (vision) → render n/N). The library never imports rich.

## Testing seams

- `scoring`, `cropplan`, `captions`, `config`, `report`: unit tests on hand-built `Signals` (flat noise + injected spikes; all-NaN motion; silent audio; two peaks 5 s apart for dedupe; peak at t=0 and t=end for clamping). No ffmpeg.
- Extractors: feed synthetic int16 sine bursts / numpy frames in chunk sizes 1, 777, and whole; outputs must be identical (chunk-size invariance = streaming correctness).
- End to end on `scripts/make_test_video.py` (3 min, 6 audio bursts, 4 motion bursts): top-6 contain all audio bursts; a quiet variant (audio flat) must still pick the 4 motion bursts.

## Hosted wrapper (no library change)

```
API ─ POST /jobs {video_uri, options_json} ─▶ queue (SQS/Redis) ─▶ worker:
   download object → scratch/V ; cache = ObjectStoreCache(bucket, prefix=f"cache/{id}") ;
   report = run(scratch/V, Options.from_dict(job.options), on_event=publish(job.id), cancel=job.cancel_flag, cache=cache)
   upload clips/*.mp4 + report.json → object store ; mark done
```
- Everything crossing the boundary is JSON (`Options`, `Event`, `Report`) or a local path. Re-weighting an old job = new job, same `id`, warm cache → seconds, no decode.
- Content id is already path-independent, so two users uploading the same file share analysis (only if product wants it; key by tenant otherwise).
- Library stays single-process per job; scale = more workers. Per-job ffmpeg limits via `Options.render.workers/threads`; wall-clock timeout via `cancel`.

## Build Order (each step: commit + synthetic run + the VERIFY)

1. `config`, `probe`, `cache`, `events`, `report` skeletons + `make_test_video.py`. Verify: probe JSON on the synthetic file; ffmpeg-missing → exit 3; Options layering unit test.
2. `audio_signals` streaming + segment cache. Verify: chunk-size invariance; 10 h of silence+tone stub analysed with RSS < 300 MB; kill mid-run and resume gives identical npz.
3. `scoring` (audio only) + `--dry-run` report. Verify: 6/6 bursts in top 6; weights change re-run uses cache (0 decode).
4. `render` centre crop + fades + CLI end to end. Verify: ffprobe 1080x1920, duration within ±0.1 s, bad clip injected → others ok.
5. `video_signals` (motion, cut) into scoring. Verify: quiet variant picks motion bursts; gate logic unit tests.
6. `cropplan` + expression crop. Verify: crop never leaves frame, max pan speed respected, visual check of a moving-object clip.
7. `speech` + `captions` (top-3N spans only). Verify: no-speech video → no whisper import, `captions:false`; word timing offsets correct after `-ss`.
8. `facecam`. Verify: synthetic corner patch with a face image stacks; no-face → warning, gameplay layout.
9. `vision` (Ollama absent → silent skip). Verify: unreachable port handled in <2 s.
10. README, perf numbers into GRAPH.md "Numbers" (media-x-realtime on M1 Max, 1 h and 10 h).

## Anti-Patterns

- **Decoding full-res to analyse** — 10 h at 1080p is hours of CPU. Use the 320 px/5 fps proxy and audio-only PCM.
- **Normalising before caching** — bakes scoring choices into the cache; store raw.
- **Whisper over the whole file** — dominates runtime. Transcribe candidate spans only; speech stays a bonus.
- **Global mean/std scoring** — one explosion distorts it; use rolling median/MAD plus the informativeness gate.
- **Per-frame crop from raw centroid** — jitter. Median + One-Euro + deadband + speed cap.
- **`print`/`sys.exit`/global logger config in the library** — breaks hosted use; events and exceptions only.
- **Several ffmpeg passes per clip** (crop, then captions, then facecam) — re-encodes; one graph, one encode.
- **Unbounded render parallelism** — x264 already threads; cap workers.

## Integration Points

| Service | Pattern | Notes |
|---|---|---|
| ffmpeg/ffprobe | subprocess, `-nostdin -hide_banner -loglevel error`, argv lists never shell strings | file paths with spaces/unicode; Windows path escaping inside `ass=` |
| faster-whisper | lazy import in `speech.py` | extra `clip-anything[speech]`; model download is the one network use, so gate it behind explicit opt-in/flag |
| Ollama | HTTP 127.0.0.1:11434, 2 s connect timeout | keyframe JPEGs base64; on any failure → `None` |
| OpenCV | `cv2.data.haarcascades` for facecam | ships with headless wheel (VERIFY) |

## Sources

- Project constraints: `.planning/PROJECT.md`, `.planning/GRAPH.md`
- ffmpeg filter docs (crop expression variables `t`/`n`, `-filter_complex_script`, `sendcmd`, `ass`) — from training knowledge; VERIFY crop `x` per-frame evaluation on the installed ffmpeg 9
- scipy.signal.find_peaks, One-Euro filter (Casiez et al. 2012) — training knowledge, MEDIUM

---
*Architecture research for: local highlight-clipping pipeline*
*Researched: 2026-11-12*
