# 01-01 Summary — Core: probe + audio signals → scoring → render → CLI (steps 1–4) — DONE 2026-11-12

Commits: b190f21 scaffold/probe/synthetic video · e403892 audio signals + cache · 3562d30 scoring/report/dry-run CLI · 52534fb render + CLI end to end.

Built: `clip_anything/{errors,events,config,probe,cache,audio_signals,scoring,report,render,pipeline,cli,ui}.py`, `scripts/make_test_video.py` (base / music-bed / VFR variants + synth.json truth), `clip-anything.toml`, README, 21 pytest tests (ruff clean).
- Library-first: `pipeline.run(video, Options, on_event, cancel) -> Report`; CLI is the only module that prints/exits. `--help` imports no numpy/scipy/cv2 (tested).
- Audio: streamed s16le 16 kHz pipe in 30 s chunks, 0.5 s hop, 1 s RMS window; rms_db / flux / onset / loud_rel (dB over rolling 60 s median). Chunk-size invariant (tested at 1 sample, 777, whole). Raw signals cached at `.clipanything/<id>/signals.npz` (id = size + 3×1 MiB samples), `--no-cache` bypasses.
- Scoring: rolling median/MAD normalise → informativeness gate (mean of top 1% − median, rare-event safe; p99 missed 4-of-600 spikes) → mean/max blend → gaussian smooth → find_peaks (30 s distance, prominence 0.1) → active span + 60/40 padding → snap to quiet → NMS (20 % overlap / peak-inside).
- Render: `-ss` before `-i`, one graph per clip via `-/filter_complex file` (cwd=tmp), centre 9:16 crop with pad fallback, 1080x1920 yuv420p bt709 (setparams), fades, libx264 veryfast CRF 20, AAC 160k, faststart, `.part` → rename, workers = cpu//4, failed clip → warning + exit 1 only if none ok. Existing file → skipped unless `--force`.
- Preflight: ffmpeg ≥ 5, `ass` filter → `caps.captions` (False on this Mac), `-/filter_complex` on ≥ 7, ffmpeg-full path lookup, exit 3 + brew/apt/winget help.

Measured (M1 Max, Python 3.11): synthetic 3 min → audio 0.34 s, 6/6 clips rendered in 10.0 s (2 workers, ~3 s/clip), total 10.7 s. 1-hour file → audio 3.85 s, score 0.47 s, dry-run 4.4 s (≈ 4 s per hour of input, 925× realtime); 3/3 bursts found at ±0.25 s.
Synthetic run: `clip-anything tests/fixtures/synth.mp4 --count 6 --out clips` → 6/6 clips, every burst inside a clip ≥ 3 s after its start; music-bed and VFR variants also 6/6.

Weak / unverified: no real footage yet; weights are guesses; clips are mostly 16–18 s (bursts are short, so pad = 10 s + span) — real games will want longer; no segment-resume for interrupted 10 h decodes (cache is all-or-nothing); Windows untested; `media_x_realtime` is 0 when cached. The informativeness gate floors (6 dB, 0.3 onset) are untuned. `uv build` + `uvx --from wheel clip-anything --help` verified locally; nothing published.
