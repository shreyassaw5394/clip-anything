# 06-01 Summary: Windows support + desktop app (2026-11-12)

PR: https://github.com/shreyassaw5394/clip-anything/pull/7 (branch `desktop`), CI run 43329997654 green on all 6 jobs incl. both Windows. Commits 46a24dd 6ccc2ac c870f54 786d136 + docs.

## Done
- CI matrix now ubuntu/macos/**windows-latest** x py3.11/3.13 (ffmpeg via `choco install ffmpeg-full`, fallback `ffmpeg`). New required checks: `test (windows-latest, py3.11)`, `test (windows-latest, py3.13)`.
- Portability: UTF-8 console on Windows (cli), `creationflags` on every ffmpeg call (vision.py was missing it), `os.path.basename` in the summary table, fixture generator raises `EncoderMissing` -> tests skip with the reason, `resource`/symlink/`SYSTEMROOT` guards in tests.
- `clip_anything/gui.py` (stdlib tkinter): pickers, count/captions/facecam/crop, progress bar + stage label from `pipeline.run(on_event=)` in a worker thread, Cancel, clip list, Open clips folder, plain-language errors. `Controller`/`ProgressModel`/`JobSettings` have no tkinter and are tested (tests/test_gui.py, 6 tests); `--selftest` exits 0 without a display; `--run <video> --out <dir> [--captions]` is a headless smoke mode. Entry `clip-anything-gui`, `python -m clip_anything.gui`.
- `probe.preflight()` looks for bundled ffmpeg/ffprobe first (`CLIP_ANYTHING_FFMPEG_DIR`, exe dir, `_internal/ffmpeg`, .app Frameworks/Resources).
- `packaging/`: `fetch_ffmpeg.py` (URL + SHA-256 pins: BtbN autobuild-2026-11-12 win64 **gpl-shared** because the LGPL build has no libx264; ffmpeg-static b6.1.1 macOS arm64/x64, GPL), `clip_anything.spec`, `launcher.py`, `build.py` (zip + dmg), `THIRD_PARTY_NOTICE.txt`. `release.yml` on `v*` tags: windows-latest + macos-latest (arm64) + macos-15-intel (optional), `contents: write` only on the upload job, pinned actions, draft release + SHA256SUMS. Not triggered.
- Captions bundled by default (`CLIP_ANYTHING_BUNDLE_CAPTIONS=0` to drop): measured macOS arm64 without 270 MiB / 108 MiB zip; with 418 MiB / 161 MiB zip / 179 MiB dmg (< 350 MiB bar).
- Fix found by the bundle test: faster-whisper's Silero VAD asset was not collected (spec now `collect_data_files`), and a transcription exception failed the whole run -> now one warning, captions skipped (test added).
- `docs/desktop.md` (macOS Open Anyway / Windows SmartScreen steps, usage, build-it-yourself), `scripts/install.sh`, `scripts/install.ps1`. README not touched (coordinator: separate PR).

## Verified
Local macOS arm64 bundle: `--version`, `--selftest`, and `--run` on an uncached copy of synth.mp4 with `PATH=/usr/bin:/bin` (no system ffmpeg): all stages ok, 3/3 clips, analysis 1.4 s; speech fixture: `speech ok 1/1`, captions burned + sidecar. Full pytest 95 passed locally, ruff clean.

## Not verified / open
- Windows GUI and Windows bundle never run by a human (CI only, and the release workflow only runs on a tag). No signing/notarisation. No window screenshot: `screencapture` is denied for this session (owner: `clip-anything-gui tests/fixtures/synth.mp4 --autostart`, then screenshot into docs/desktop.md).
- Icons: spec references `assets/icon.icns`/`.ico`, GUI uses `assets/icon.png` when present; files come with the `brand` branch (not on `desktop`).
- Shared-checkout incident: another agent had `readme-simple` checked out in ~/clip-anything, so my first four commits also sit on that branch (f0cd0be..f4c60d5 on top of 909ec24); `desktop` was rebuilt in the worktree ~/clip-anything-desktop. Whoever owns `readme-simple` should `git branch -f readme-simple 909ec24` when their tree is clean.
