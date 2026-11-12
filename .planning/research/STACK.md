# Stack Research

**Domain:** Local Python CLI: action-highlight detection in long gameplay video, vertical clip rendering
**Researched:** 2026-11-12
**Confidence:** HIGH on versions/ffmpeg graphs (checked live against PyPI JSON API and ffmpeg 9.0.2 on the M1 Max), MEDIUM on speed numbers and Ollama tags (web sources, not benchmarked here)

## Findings that change the plan (read first)

1. **Homebrew `ffmpeg` 9.0.2 on this machine has NO libass, NO freetype, NO `subtitles`/`ass`/`drawtext` filter** (checked with `-buildconf` and `-filters`; enabled: x264, x265, svtav1, dav1d, vpx, opus, videotoolbox). Burned ASS captions will fail on a stock `brew install ffmpeg`. Startup check must probe `ffmpeg -filters` for `ass` and pick a caption backend (see Captions). `brew install ffmpeg-full` (keg-only, exists as 9.0.2) is the documented fix. HIGH.
2. **Python 3.11 floor vs latest wheels:** numpy 2.5.4, scipy 1.18.1, librosa 1.0.1, av 19.0.2 all require Python >=3.12. numpy 2.4.x and scipy 1.17.x still support 3.11. Declare loose lower bounds and let the resolver pick; do not pin upper-newest. HIGH.
3. **PySceneDetect 0.7.3 depends on `opencv-python` (non-headless)**. That collides with `opencv-python-headless` (two cv2 packages in one env). Do not use it. Own histogram delta is ~15 lines. HIGH.
4. **ffmpeg >=7 syntax:** `-filter_complex_script` was removed; use `-/filter_complex file.txt` (tested on 9.0.2). Fall back to `-filter_complex_script` if `ffmpeg -version` major < 7. HIGH.
5. **opencv 5.0.0.93 is out (2026-07-02) alongside 4.13.0.92.** Pin `<5` for launch; 5.x is a major with unverified API changes for `FaceDetectorYN`/`calcHist`. MEDIUM.

## Recommended Stack

### Core Technologies

| Technology | Version (PyPI, 2026-11-12) | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | 3.11-3.13 (`requires-python = ">=3.11"`) | Runtime | 3.11 is on the owner machine; wheels exist for all deps on 3.11-3.13 |
| ffmpeg / ffprobe | 7+ (local: 9.0.2) | All decode, proxy, render | External binary; only tool that handles HEVC/10-bit captures at speed; checked at startup |
| numpy | `>=2.0` (resolves 2.4.6 on 3.11, 2.5.4 on 3.12+) | All signal math, rawvideo frames | Zero-copy `np.frombuffer` from the ffmpeg pipe |
| scipy | `>=1.13` (1.17.1 on 3.11, 1.18.1 on 3.12+) | `signal.find_peaks`, `ndimage` smoothing/median filters | Only the two submodules are imported (lazy) to keep start fast |
| opencv-python-headless | `>=4.10,<5` (4.13.0.92; wheels 46 MB mac-arm64, 40 MB win-amd64, ~57-61 MB linux-x86_64) | Gray diff, calcHist, Haar/YuNet faces, flow at render time | Headless = no Qt/GUI deps; abi3 wheel works on 3.11-3.13 |
| rich | `>=13` (15.0.0) | Progress UI, tables, error panels | Pure Python, already needed |
| typer | `>=0.12` (0.29.1) | Thin CLI over `pipeline.run()` | Pulls click only; auto `--help`; `[project.scripts]` target `clip_anything.cli:app`. argparse is acceptable if cold start matters (LOW difference) |
| hatchling | 1.33.0 | Build backend | Matches GRAPH.md; no setup.py |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| faster-whisper | 1.2.1 (last release 2025-10-31; deps: ctranslate2 4.9.0, av, onnxruntime 1.31.1, huggingface-hub, tokenizers; **no torch**) | Word-timestamped transcripts for captions + excitement words | Optional extra `captions`; lazy import inside `speech.py` only |
| Pillow | `>=10` (~4 MB wheel, version not re-verified) | Fallback caption rasteriser when ffmpeg lacks libass | Only imported when `ass` filter missing |
| Ollama (external) | any 0.5+ daemon, HTTP at 127.0.0.1:11434 | Optional VLM re-rank | Call with stdlib `urllib.request`; do NOT add `ollama` pip pkg (0.6.3 exists, pulls httpx+pydantic) |
| pytest | 9.2.0 | Tests | dev |
| ruff | 0.17.5 | Lint/format | dev |

## (1) Audio features: numpy/scipy, not librosa

- **Decode:** one ffmpeg pipe, `ffmpeg -nostdin -v error -i IN -vn -ac 1 -ar 16000 -f s16le -` (int16, 1.15 GB for 10 h if fully loaded; float32 would be 2.3 GB). Do not load it all: read 30-60 s chunks (`proc.stdout.read(960000*2)` for 30 s) in a loop and emit per-0.5 s features; state carried across chunks = the previous magnitude frame (for flux) and a partial-window remainder. Output is ~72k floats per feature for 10 h. Peak RAM < 100 MB. HIGH (arithmetic + standard pattern).
- **Window = 0.5 s = 8000 samples.** Frames: `n_fft=1024, hop=256` via `np.lib.stride_tricks.sliding_window_view` + Hann + `np.fft.rfft` (vectorised per chunk; no per-frame Python loop).
- **Features per window:** `rms_db = 20*log10(rms+1e-6)`; `flux = max over frames of sum(max(0, |X_t| - |X_{t-1}|))` on log-compressed magnitude (`np.log1p(10*mag)`), taking window max (onset sharpness, explosions/gunshots) not mean; optional low-band (<250 Hz) energy ratio for explosion boom.
- **Loudness vs rolling baseline:** `base = scipy.ndimage.median_filter(rms_db, size=120)` (60 s) ; `dev = (rms_db - base) / (1.4826*MAD_rolling + 1.0 dB floor)`; clip to [0, 6] then normalise 0..1 by the 99th percentile (robust to a single clipped scream). Baseline kills constant music/engine hum; bursts stay.
- **Normalisation:** per-signal `clip((x - p50) / (p99 - p50), 0, 1)` over the whole file, not min-max.
- **Why not librosa 1.0.1:** requires >=3.12 (breaks 3.11), drags numba/llvmlite/scikit-learn/soundfile/pooch; numba JIT adds seconds to cold start under `uvx`; we need 3 features. HIGH on the version fact, MEDIUM on dep list (recalled, not re-read).

## (2) Visual motion + scene cuts on a proxy

- **Pipe, no temp files:**
  `ffmpeg -nostdin -v error [-hwaccel auto] -i IN -an -vf "fps=5,scale=320:{H}:flags=area,format=gray" -f rawvideo -pix_fmt gray -`
  where `{H} = round(320*src_h/src_w/2)*2` computed from ffprobe (do not use `-2` so frame size is known). Read `320*H` bytes per frame, `np.frombuffer(buf, np.uint8).reshape(H, 320)`. Run `stderr=subprocess.DEVNULL` (or a drained thread) to avoid a pipe deadlock; always `-nostdin`. Tested: 6 s 1080p HEVC -> 1,728,000 bytes = 30 frames of 320x180 gray. HIGH.
- **Motion = `cv2.absdiff(prev, cur)` mean** (plus fraction of pixels > 25). ~0.1 ms/frame; 10 h @5 fps = 180k frames, decode-bound not compute-bound. Aggregate to 0.5 s windows by max-of-mean.
- **Optical flow (Farneback ~3-6 ms/frame at 320x180, estimate) is NOT worth it for detection** (adds ~10-15 min at 10 h). Use it only for crop targeting inside the N selected clips if frame-diff centroid is poor. MEDIUM.
- **Scene cuts:** 32-bin gray histogram (`cv2.calcHist`, normalise) per frame; cut score = `0.5*cv2.compareHist(h0,h1,cv2.HISTCMP_BHATTACHARYYA)`-style distance; a cut is `delta > max(0.35, median + 6*MAD)` AND the diff spike is single-frame (next-frame delta small), which distinguishes cuts from explosion flashes. Cut count per window feeds score and snap points.
- **Decode speed:** the proxy decodes every source frame (`fps=5` filter drops after decode). `-hwaccel auto` helps 4K HEVC (macOS `videotoolbox`, Windows `d3d11va`/`cuda`, Linux `vaapi`/`cuda`; `ffmpeg -hwaccels` lists them; local shows `videotoolbox`). Software HEVC 1080p on M1 is well above realtime so default OFF for analysis, add `--hwdec` flag. Never use HW *encode* for output (quality/CRF semantics differ). MEDIUM.
- **Single decode pass:** run video proxy and audio extraction as two ffmpeg processes in parallel threads (audio is cheap). Do not demux twice sequentially for 10 h files.

## (3) Peak picking

Signal at 2 Hz (0.5 s windows), score = weighted sum, then `scipy.ndimage.gaussian_filter1d(score, sigma=2)` (1 s).

```python
peaks, props = find_peaks(s,
    height=np.percentile(s, 90),          # absolute floor
    prominence=0.15,                      # on 0..1 scale; raise to 0.25 if too many
    distance=int(min_gap_s / 0.5),        # min_gap_s = max(--min, 20) -> 40+ samples
    wlen=240)                             # 120 s window: bounds prominence cost on 72k-sample arrays
```
Then rank by `prominence * height`, take top N after dedupe by window overlap (>30% IoU drop the lower). Window = peak - 0.6*L .. peak + 0.4*L with L = clamp(burst width from `peak_widths(rel_height=0.5)` + 8 s, min, max). Snap start to lowest-energy sample within ±1.5 s or nearest cut. HIGH on API (scipy docs); parameter values are starting points to tune on real GTA footage (MEDIUM).

## (4) ffmpeg rendering

- **Accurate seek:** `-ss START -t DUR` placed BEFORE `-i` (fast keyframe seek, then frame-accurate decode from there since re-encoding; accurate since ffmpeg 2.1). Add `-accurate_seek` implicitly default. Do not use `-c copy`. HIGH.
- **Moving 9:16 crop: use `crop` with a time expression**, x as nested piecewise-linear lerp over keyframes sampled ~1 per second from the smoothed centre-of-motion track. Alternatives rejected: `sendcmd` steps (stepped, needs 10 Hz keyframes to look smooth, extra file); `zoompan` (designed for still images, resamples, slow, jitter on video). `crop` x/y are evaluated per frame; `out_w/out_h` are not (keep them constant). Tested on 9.0.2 (output h264 1080x1920 OK):

```
[0:v]crop=w=ih*9/16:h=ih:x='(iw-ow)*clip(if(lt(t,2),0.2+0.3*t/2,if(lt(t,4),0.5+0.4*(t-2)/2,0.9)),0,1)':y=0,
 scale=1080:1920:flags=lanczos,setsar=1,fade=t=in:st=0:d=0.3,fade=t=out:st=5.7:d=0.3[v];
[0:a]afade=t=in:st=0:d=0.3,afade=t=out:st=5.7:d=0.3[a]
```
Generated from numpy: keyframes `(t_i, cx_i)` where cx is fraction 0..1 of travel; emit `if(lt(t,t1),lerp(c0,c1,(t-t0)/(t1-t0)),if(lt(t,t2),...,c_last))` nested, ~3 KB for 45 keyframes. Pass via `-/filter_complex graph.txt` (ffmpeg >=7) or `-filter_complex_script` (older) to dodge Windows ~32k command-line and quoting limits. Note `t` restarts at 0 for each seeked clip, and fade-out `st = DUR - 0.3`. HIGH (executed).
- **Smoothing (numpy, before expression):** centroid per proxy frame -> median filter (size 9) -> `gaussian_filter1d(sigma=~1.5 s of frames)` -> deadband (hold x until |target - x| > 6% of travel) -> max pan speed clamp (~25% of travel/s) -> resample to 1 Hz keyframes. This removes jitter; linear interpolation between 1 s keys is invisible. Default to centre (0.5) when motion confidence is low.
- **Encode:** `-c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p -c:a aac -b:a 160k -movflags +faststart`; yuv420p is required for phone/TikTok playback. Tested. HDR/10-bit sources: add `format=yuv420p` after scale and, for HDR PQ/HLG, `zscale`/`tonemap` is out of scope for v1 (warn). 
- **HEVC input:** any ffmpeg decodes it (libavcodec native `hevc`); tagging irrelevant on input. Tested HEVC `hvc1` in -> H.264 out. 
- **Captions backends (choose at startup by `ffmpeg -hide_banner -filters | grep -w ass`):**
  1. libass present: append `,ass=captions.ass` AFTER `scale` (script resolution 1080x1920 so font sizes are absolute). Write the .ass into the temp working dir and run ffmpeg with `cwd=tmp` so the filter arg is a bare filename; this sidesteps Windows `C\:/` escaping. Word-sync via `{\k<cs>}` karaoke tags; style: Bold, outline 4, MarginV ~ 320 px, font from `fontsdir=` only if shipping a font.
  2. libass missing (stock Homebrew now): either print "brew install ffmpeg-full" help and still render without captions, or rasterise phrases with Pillow into transparent PNGs and chain `overlay=enable='between(t,a,b)'` (cap at ~25 phrase PNGs per clip to keep the graph small; per-word highlight is not practical this way). Recommend: v1 ships backend 1 + warning for missing libass; Pillow overlay as stretch. 
  - Where libass exists: winget `Gyan.FFmpeg` (full build, MEDIUM: package id recalled), apt `ffmpeg` (Debian/Ubuntu builds enable libass, MEDIUM), brew `ffmpeg-full` (HIGH, listed as 9.0.2 keg-only; user must put `$(brew --prefix ffmpeg-full)/bin` on PATH or the CLI must check that path too).
- **Facecam stack:** `[0:v]split[a][b];[a]crop=fw:fh:fx:fy,scale=1080:-2[face];[b]crop=...(moving crop)...,scale=1080:1344[game];[face][game]vstack` with face band ~ 1080x540 over gameplay 1080x1380 (sum to 1920). Gameplay crop width then = ih*(1080/1380)... compute from the target band aspect, not 9/16.

## (5) faster-whisper on CPU (optional, lazy)

- `WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=os.cpu_count()//2)`; ctranslate2 has no Metal backend, so Apple Silicon runs CPU/Accelerate: fine for this scale. Use `word_timestamps=True, vad_filter=True, beam_size=1`. 
- **Cost control (key design point):** transcribe ONLY the audio of the N selected clip windows (e.g. 10 x 30 s = 5 min audio), never the whole 10 h. Even at ~10-15x realtime (small, int8, 8 threads, MEDIUM from project benchmarks, not measured here) that is under a minute. Speech presence is gated first by a cheap energy/VAD check on the 16 kHz audio; no speech -> skip model load entirely.
- Models: `tiny.en` (~75 MB) fast/poor, `base.en` (~145 MB) default for English, `small` (~480 MB) better, `large-v3` too slow on CPU. Sizes are approximate (MEDIUM). Default `base.en`/`small`; flag `--whisper-model`.
- **Download UX:** first use downloads from Hugging Face to `~/.cache/huggingface`. Before the first load, check cache (`huggingface_hub.try_to_load_from_cache` / try `local_files_only=True`); if absent, print size and ask "Download base.en (145 MB) for captions? [Y/n]" (auto-yes with `--yes`, skip with `--no-captions`). This is the only network use besides localhost; document it. No telemetry. 
- **Optional:** `[project.optional-dependencies] captions = ["faster-whisper>=1.1"]`; `speech.py` imports inside the function and catches `ImportError` -> prints `pip install "clip-anything[captions]"` (or `uvx --with faster-whisper clip-anything ...`). Excitement bonus = short-window loudness + exclamation keyword list on the same transcript, weight only.

## (6) Faces / facecam

Use **OpenCV Haar** (`cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")`, ships inside the wheel, zero download) on a handful of full-res corner crops sampled ~20 times across the video, `scaleFactor=1.1, minNeighbors=5, minSize=(40,40)`. Facecam is an upright, static, well-lit corner overlay, which is Haar's best case. Static-region test first: per-corner pixel std-dev across the sampled frames is low (< ~12) while the gameplay region varies. Upgrade path: **YuNet** via `cv2.FaceDetectorYN.create(model.onnx, "", (w,h))` (~230 KB ONNX from opencv_zoo, more robust to angle/occlusion) but it needs bundling the file and relies on OpenCV 4.5.4+ API (confirmed API exists in 4.x; 5.x unverified). Decision: Haar for v1, YuNet only if Haar misses on real footage. MEDIUM.

## (7) Ollama local VLM (optional)

- **API:** `POST http://127.0.0.1:11434/api/chat` JSON `{"model": "...", "stream": false, "format": {JSON schema}, "options": {"temperature": 0}, "messages":[{"role":"user","content":"...","images":["<base64 jpeg>", ...]}]}`. `images` is a list of raw base64 (no data: prefix). Reply `message.content` is JSON when `format` given. Probe `GET /api/tags` (200 + model present) with 0.5 s timeout to decide whether to run; any error -> silently skip (no Ollama on owner machine). Use stdlib `urllib`. HIGH on API shape (stable since 2024).
- **Frames:** 4-6 frames evenly spaced across the clip window, JPEG ~512 px long side q=80, via the same ffmpeg (`-vf fps=...,scale=512:-2`). Prompt asks for `{"score":1-10,"title":"4-6 words"}`; cap calls at N x 1 and a 30-60 s timeout each; blend as `final = 0.7*action + 0.3*score/10` (rerank, never filter out).
- **Models available (Nov 2026 per search; verify on ollama.com/library before hard-coding):** `qwen3-vl` tags 2b/4b/8b/30b/32b/235b; `gemma3` 4b/12b/27b are multimodal (270m/1b text-only); `minicpm-v` 8B (~5.5 GB; newer 4.5/4.6 tags reported, 1B ~1.6 GB); `moondream` ~1.8B ~1.7 GB; `gemma4:e4b` ~6.6 GB reported by one blog (LOW). Default suggestion `qwen3-vl:4b`, fallback `gemma3:4b`, tiny `moondream`. Auto-pick: first of a preference list present in `/api/tags`; `--vision-model` overrides. MEDIUM/LOW on exact sizes.

## (8) Packaging

```toml
[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"
[project]
name = "clip-anything"
requires-python = ">=3.11"
dependencies = ["numpy>=2.0", "scipy>=1.13", "opencv-python-headless>=4.10,<5", "rich>=13", "typer>=0.12"]
[project.optional-dependencies]
captions = ["faster-whisper>=1.1"]
dev = ["pytest>=8", "ruff"]
[project.scripts]
clip-anything = "clip_anything.cli:app"
[tool.hatch.build.targets.wheel]
packages = ["clip_anything"]
```
- Script name == package name, so `uvx clip-anything video.mp4` and `pipx install clip-anything` both resolve the entry point. Test with `uv build && uvx --from dist/*.whl clip-anything --help` before publishing.
- Install weight: numpy ~12 MB + scipy ~29 MB (mac-arm64) + opencv ~46 MB (mac) / 40 MB (win) / ~60 MB (linux) -> roughly 100-130 MB first `uvx` run, cached after. faster-whisper extra adds ctranslate2 + onnxruntime (~21 MB) + av (~19 MB).
- **Cold start:** `import clip_anything` and `--help` must not import scipy/cv2/faster-whisper (import inside stage functions) so help and the ffmpeg check are instant.
- **Windows:** `winget install Gyan.FFmpeg` (restart shell for PATH); use `pathlib`, `subprocess.run([...], list)` never `shell=True`; avoid colons in filter args (cwd trick above, `-/filter_complex file`); `os.fspath` on all paths; output names sanitised (no `:`); run ffmpeg with `creationflags=subprocess.CREATE_NO_WINDOW`; UTF-8 for ASS (`BOM` not required). Console: rich handles Windows Terminal; legacy cmd gets plain output. MEDIUM (not tested here).
- ffmpeg check: `shutil.which("ffmpeg")` + `ffprobe`; parse `-version`; also check `/opt/homebrew/opt/ffmpeg-full/bin` on macOS. Exit code 3 with brew/apt/winget help.

## (9) Rich progress for multi-stage pipelines

- Library emits events, never prints: `pipeline.run(video, opts, on_event: Callable[[Event], None] | None)` with `Event(stage, done, total, msg)`; CLI maps events to rich. Keeps the hosted version free of rich. 
- One `Progress(SpinnerColumn(), TextColumn("{task.description}"), BarColumn(), MofNCompleteColumn(), TimeElapsedColumn(), TimeRemainingColumn(), console=Console(stderr=True))`. Pre-add a task per stage (probe, audio, video, score, vision, render) with `total=None` (spinner) until the total is known, then `progress.update(task, total=n)`. Render is `N/N` clips; analysis stages use seconds-of-media as units (`total=duration_s`) so ETA is real.
- Progress to **stderr**; stdout only the final summary table or `--json` payload. `--json` disables progress. Rich auto-disables animation when not a TTY. Finish with a `rich.table.Table` of clips (time range, score, title) and the output folder path. Errors via `console.print(Panel(..., style="red"))` and mapped exit codes (2 bad input, 3 ffmpeg missing).
- Parallelism: run audio and video analysis in two threads (each mostly waiting on its ffmpeg pipe); rich Progress is thread-safe.

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| numpy FFT features | librosa 1.0.1 | Only if >=3.12-only is acceptable and cold start/numba is irrelevant (hosted service) |
| Own histogram cut detector | PySceneDetect 0.7.3 | Never with headless cv2 (hard dep on `opencv-python`); possible in a hosted venv |
| `crop` time expression | `sendcmd`, `zoompan` | `sendcmd` if keyframes >300 and the expression gets unwieldy; `zoompan` never |
| Haar | YuNet ONNX | Haar false-negatives on real facecams |
| stdlib urllib to Ollama | `ollama` pip 0.6.3 | If streaming/tool features are needed later |
| faster-whisper | whisper.cpp / mlx-whisper | Mac-only speed (Metal/ANE); not cross-platform, extra install burden |
| typer | argparse | If cold start/dep count matters more than pretty help |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| torch / torchaudio / transformers at import | 200 MB-2 GB install, 2-5 s import, breaks `uvx` snappiness; faster-whisper does not need it (ctranslate2) | numpy/scipy; faster-whisper lazily |
| moviepy | Re-decodes via per-frame Python, slow on hours of video, hides ffmpeg errors, pulls imageio/imageio-ffmpeg (bundles a second ffmpeg), pillow | direct `subprocess` + ffmpeg filter graphs |
| pydub | Loads whole file into RAM (10 h = GBs), shells ffmpeg anyway, unmaintained-ish | ffmpeg pipe + chunked numpy |
| ffmpeg-python (0.2.0, 2019) | Abandoned, no ffmpeg 7+ option support, obscures graph strings we need to control | build arg lists by hand |
| `opencv-python` (non-headless) | Qt/GUI deps, conflicts with headless | `opencv-python-headless` |
| librosa, PySceneDetect | see findings 2-3 | numpy/scipy/own code |
| HW *encode* (videotoolbox/nvenc) for output | CRF not supported the same way, quality/size inconsistent | libx264 veryfast CRF 20 |
| Optical flow over the full file | ~10-15 min extra at 10 h for little detection gain | frame diff; flow only inside selected clips if needed |
| `-c copy` for clips | Cannot crop/fade/burn; cuts on keyframes only | re-encode |

## Stack Patterns by Variant

**If ffmpeg lacks libass (stock Homebrew):** warn, render without captions (or Pillow overlay), tell user `brew install ffmpeg-full`. Do not crash.
**If no speech detected in a clip:** skip whisper entirely, no caption track, still emit clip.
**If Python 3.12+:** nothing changes; resolver picks newest numpy/scipy.
**If source is ultrawide/4:3:** crop width = `ih*9/16` can exceed `iw` on portrait sources; clamp and pad (`pad` or scale-to-fit) instead of failing.

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| numpy 2.5.x / scipy 1.18.x | Python >=3.12 only | On 3.11 resolver backs off to numpy 2.4.x / scipy 1.17.x |
| faster-whisper 1.2.1 | ctranslate2 >=4,<5; av >=11; onnxruntime <2 | `av` 19 needs >=3.12, older av wheels used on 3.11; no torch |
| opencv-python-headless 4.13 | numpy 2.x | abi3 wheel (cp37-abi3) so Python-version independent |
| scenedetect 0.7.3 | requires `opencv-python` | conflicts with headless: excluded |
| ffmpeg <7 | `-filter_complex_script` | >=7 uses `-/filter_complex` |

## Sources

- PyPI JSON API (queried 2026-11-12): numpy 2.5.4, scipy 1.18.1, librosa 1.0.1, opencv-python-headless 5.0.0.93 / 4.13.0.92, scenedetect 0.7.3, faster-whisper 1.2.1, ctranslate2 4.9.0, onnxruntime 1.31.1, av 19.0.2, rich 15.0.0, typer 0.29.1, hatchling 1.33.0, pytest 9.2.0, ruff 0.17.5, ollama 0.6.3; `requires_python`, `requires_dist`, wheel sizes -- HIGH
- Local ffmpeg 9.0.2 (`-buildconf`, `-filters`, `-hwaccels`, executed filter graphs, rawvideo/f32le pipes, `brew info ffmpeg-full`) -- HIGH
- Ollama library listings via web search (ollama.com/library/qwen3-vl; promptquorum, localaimaster, NVIDIA live-vlm-webui lists) -- MEDIUM/LOW; re-check tags at build time
- faster-whisper speed/size figures, winget package id, apt libass, YuNet file size, Farneback timing: training knowledge, not verified this session -- LOW/MEDIUM
- Context7 was not available in this session.

---
*Stack research for: local gameplay highlight clipper*
*Researched: 2026-11-12*
