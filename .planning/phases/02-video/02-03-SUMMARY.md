# 02-03 Summary — Inputs: every way people record (folders, tracks, geometry, containers, long files) — DONE 2026-11-12

Commits: a651bbd (inputs.py, probe, pipeline sessions + resume, 14 fixtures, 18 tests) · 480f5ca (undecodable tracks, deferred notes). test_inputs.py 18/18 green (+ gated 3 h test), ruff clean. Pipeline signals bit-identical to HEAD on the synthetic (verified per array).

Built: `inputs.py` — `discover()` (file / folder / several paths; mp4 mkv mov m4v ts m2ts mts webm avi flv wmv; friendly errors incl. a Steam raw-recording hint), order by `creation_time` tag → mtime → natural name, `build_session()` (hop-aligned per-file offsets), `clamp_to_source()` (a clip never crosses a file), `audio_roles()` (first 120 s per track: silent / undecodable / mic / game) + `choose_track()` (`--audio-track auto|all|game|mic|N`; auto = amix of all live tracks). `probe.py` — `audio_streams`, `creation_time`, `container`, `measure_duration()` copy-pass when the container has none, untagged 10-bit bt2020 → assumed PQ + warning, `-ss`/`-t` before `-i` in both pipes, `audio_map_args`. `pipeline.py` — `run()` accepts a path, a folder or a list; `_run_many()` analyses per file (cache per file, progress on the session timeline), ranks once over the whole pool, speech/facecam/render per file; all files ≤ 90 s → each file is one candidate (`_whole_file_candidates`, whole file or trimmed to the peak); analysis runs in 15-min segments with `<stage>.partial.npz` checkpoints, auto-resume (`--resume/--no-resume`), partials removed on completion; slow-decode / AV1 / no-audio / no-index warnings. Clip gains `source`, `source_index`, `session_start/end`; report.input gains `sources`, `audio_tracks`.

| Source (SOURCES.md) | Fixture (scripts/make_input_fixtures.py) | Status |
|---|---|---|
| PS5/Xbox/Switch/Medal 30 s clip folders | `short_clips/` 6×30 s, reversed creation_time | PASS: order by tag, whole-file candidates, loud 3 on top, quiet 2 last |
| Chapters / split recordings (GoPro, Game Bar) | `session/` 100 s + 80 s | PASS: no clip crosses a file, local + session times, 2 caches |
| OBS multi-track (mic separate) | `two_tracks.mkv` Game/Mic titles | PASS: roles game/mic, mix finds game + mic bursts, `1`/`game`/bad N |
| Muted capture / Switch docked | `no_audio.mp4` | PASS: video-only scoring, warning, rendered `-an` 1080x1920 |
| Phone vertical, 4:3 retro, 21:9 | `vertical.mp4` 540x960, `four_three.mp4`, `ultrawide.mp4` | PASS: 1080x1920 out; portrait = centre/pad |
| Elgato / console HDR (HEVC 10-bit HLG) | `hdr_hlg.mp4` | PASS: is_hdr, tone-mapped, bt709 yuv420p out |
| PS5 WebM HDR, metadata lost on remux | `hdr_notag.webm` VP9 10-bit bt2020, no trc | PASS: `hdr_assumed`, warned, rendered |
| Phone/editor ProRes, PS5 VP9+Opus, AV1 (ShadowPlay/Elgato), Twitch .ts | `prores.mov`, `vp9_opus.webm`, `av1.mkv`, `chunk.ts` | PASS: decode + render each |
| Interrupted OBS mkv (no duration/cues) | `truncated.mkv` (`-live 1`, cut at 60 %) | PASS: duration measured 23.9 s, `no_index` warning, rendered |
| iPhone VFR screen recording | existing `synth_vfr.mp4` (test_render) + real file (3014x1568@60 VFR, no audio) | PASS: 3/3 clips rendered, 61 s |
| Kill mid-analysis | synthetic, SEGMENT_S=20, abort at 50 s | PASS: "resumed at 40s", clips == clean run |
| 1–10 h files | `long_3h.mp4` (320x180 5 fps, bursts every 10 min; CLIP_ANYTHING_LONG=1) | PASS: 21 s dry-run, peak RSS 384 MiB (< 1 GB), 5/5 bursts, no leftovers |
| Real: iPhone 4K HEVC HLG (2 tracks: aac + Apple APAC) | local only | PASS: APAC marked undecodable, track 0 used, tone-map, 25 s analysis |
| Real: 74 min + 40 min gameplay as one session | local only | PASS: 92 s analysis, clips from both files, times local |
| Steam background recordings | folder with `.m4s` → error text | PASS (message only; format unreadable by design) |

Weak / unverified: no real PS5/Xbox/OBS-multitrack/GoPro file was probed — roles come from synthetic tracks (mic = lowest high-band ratio or title match); amix default normalisation halves a lone track; sessions turn the intro/outro edge rule off (per-file edges belong in scoring); short-clip order among saturated bursts is noise-driven (deferred-items.md); resume glitch = one window at the boundary (fresh extractor state); AV1 "slow" warning only when decode < real time; `--audio-track` is per run, not per file; the 3 h test is opt-in; Windows untested. Commits include the then-uncommitted hunks of 02-02/03-01 in shared files (pipeline/probe/cli/config/report) — no separation possible in a shared tree.
