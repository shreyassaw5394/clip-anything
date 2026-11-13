# Clip Anything reference

Everything the [README](../README.md) leaves out: install variants, every option, the config file, how the pipeline works, library use, known limits and the roadmap. Measured numbers live in [benchmark.md](benchmark.md).

## Install

Needs Python 3.11+ and `ffmpeg` + `ffprobe` on your PATH. `uvx` (from [uv](https://docs.astral.sh/uv/)) fetches Python for you if needed.

| | |
|---|---|
| Run without installing | `uvx clip-anything gameplay.mp4` |
| Install as a tool | `pipx install clip-anything` or `uv tool install clip-anything` |
| With captions (faster-whisper) | `pipx install 'clip-anything[captions]'` or `uvx --from 'clip-anything[captions]' clip-anything ...` |
| From GitHub (before the PyPI release) | `uvx --from git+https://github.com/shreyassaw5394/clip-anything clip-anything gameplay.mp4` |
| npm launcher | `npx clip-anything gameplay.mp4` runs `uvx clip-anything` for you (see [`npm/`](../npm/)) |
| uv | macOS `brew install uv`, Windows `winget install astral-sh.uv`, Linux `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| ffmpeg | macOS `brew install ffmpeg`, Debian/Ubuntu `sudo apt install ffmpeg`, Windows `winget install Gyan.FFmpeg` |

If ffmpeg is missing the tool exits with code 3 and prints the install line for your OS.

macOS note: the stock Homebrew `ffmpeg` formula has no `libass`, which burned-in captions need. Clip Anything looks for an `ffmpeg-full` build on your PATH and prefers it; without one, captions are still written as a sidecar `.ass` file next to each clip and everything else works.

## All options

```
clip-anything <video or folder> [more videos] [options]
```

| Option | Default | What it does |
|---|---|---|
| `--count, -n` | 10 | Maximum clips to produce. Fewer come back when fewer moments clear the bar; there are no filler clips |
| `--min` / `--max` | 15 / 45 | Clip length bounds in seconds |
| `--out, -o` | `./clips` | Output folder |
| `--crop` | `follow` | `follow` pans the 9:16 crop with the action; `center` is a static centre crop |
| `--facecam` | `auto` | Detect a static webcam corner and stack it above the gameplay; `off` disables |
| `--no-captions` | | Never burn captions (captions are on by default when speech is found and the `captions` extra is installed) |
| `--whisper-model` | `base.en` | Whisper size for captions: `tiny.en` (75 MB), `base.en` (145 MB), `small` (480 MB), ... |
| `--yes, -y` | | Allow the one-time Whisper model download without the prompt (`--download-models` is the same) |
| `--speech-rank` | | Transcribe the top 3N candidates and let excitement words re-rank them (slower) |
| `--audio-track` | `auto` | Which audio stream to analyse: `auto`, `all`, `game`, `mic`, or a stream number. Useful for OBS recordings with separate game and mic tracks |
| `--vision` | off | Re-rank the top clips and give them titles with a local Ollama vision model (see below) |
| `--min-score` | 0.5 | Action bar 0..1 that every clip must clear (audio and motion measured against fixed real-footage levels); `0` ranks the file against itself |
| `--config` | | TOML file with weights and settings (see below) |
| `--dry-run` | | Write `report.json` only: what would be clipped and why, no rendering |
| `--json` | | Print the report to stdout (progress goes to stderr) |
| `--no-cache` | | Ignore the cached analysis signals |
| `--resume` / `--no-resume` | resume | Continue an interrupted analysis from where it stopped |
| `--force` | | Overwrite clips that already exist |
| `--workers` | cores / 4 | Parallel renders |
| `--version` | | Print the version |

Exit codes: `0` ok, `1` nothing rendered, `2` bad input, `3` ffmpeg missing.

### Inputs

Supported extensions: `.mp4 .mkv .mov .m4v .ts .m2ts .mts .webm .avi .flv .wmv`. A folder is read non-recursively and treated as one session, files ordered by creation time. When every file in the input is 90 seconds or shorter (console clips), each file is one candidate and the tool ranks the files instead of searching inside them. A raw Steam background-recording folder is recognised and rejected with a message: export a clip from Steam as MP4 first.

### Output

`clips/<stem>_01_<mm-ss>.mp4` ... (1080x1920 H.264 + AAC, faststart) and `clips/report.json` with each clip's start, end, score, per-signal breakdown, crop keyframes, captions and every warning the run produced. Analysis signals are cached next to the video in `.clipanything/<id>/`, so a re-run with different weights or counts takes seconds.

## Config file

Every weight and threshold lives in a TOML file. Copy [`clip-anything.toml`](../clip-anything.toml) (the defaults, commented), edit, and pass `--config my.toml`. Command line flags override the file; the file overrides the built-in defaults.

```toml
[clips]
count = 10
min_s = 15.0
max_s = 45.0

[scoring]
w_loud = 1.0      # loudness above the rolling 60 s baseline
w_onset = 0.8     # spectral-flux onset sharpness (gunshots, explosions)
w_motion = 0.8    # visual motion on the proxy
w_agree = 0.4     # audio AND motion rising together
w_card = 0.8      # penalty for static cards (lobby, menu, loading)
min_score = 0.2     # relative floor: nothing below max(this, 0.35 x best) is returned
min_evidence = 0.5  # absolute action bar (--min-score): audio AND motion vs real-footage levels
lead_frac = 0.6   # share of the clip before the peak (build-up)

[layout]
crop = "follow"   # or "center"
facecam = "auto"  # or "off"

[speech]
captions = true
model = "base.en"

[vision]
enabled = false
```

How these defaults were chosen, and what they score on real footage, is in [benchmark.md](benchmark.md).

## How it works

1. **Probe.** ffprobe reads the file; variable frame rate, HEVC, HDR and rotated sources are handled. The full-resolution file is decoded exactly once per rendered clip; analysis runs on a 16 kHz mono audio stream and a 320 px / 5 fps grey proxy, both streamed from ffmpeg without writing temp files.
2. **Audio signals** per 0.5 s: RMS, spectral-flux onsets (gunshots, explosions, hits), and loudness against a rolling 60 s baseline, so constant music, radio or engine noise does not flatten the signal.
3. **Visual signals** per 0.5 s: motion energy, scene cuts, flashes, and the centre of motion mass that the crop will follow. Static cards (lobby, menu, loading screen) are detected and penalised.
4. **Scoring.** Signals are robust-normalised (rolling median / MAD), gated for informativeness, then mixed: a weighted mean, the strongest single signal, and an agreement term that rewards audio and motion rising together, so a lone loud menu sound cannot win alone. Peaks are picked, each becomes a 15-45 s window with the build-up before the peak (60 / 40), snapped to a quiet point or a cut, and overlapping windows are de-duplicated.
5. **Speech (optional).** If the `captions` extra is installed and speech is present, faster-whisper transcribes the chosen clips, excitement words add a bonus, and word-synced captions are burned in. Recordings with no speech skip this entirely. Captions are automatic speech recognition output: they can mishear words, so read them before you post (the sidecar `.ass` and `report.json` carry the text).
6. **Facecam (optional).** A static webcam region in a corner is detected and stacked above the gameplay.
7. **Render.** One ffmpeg pass per clip: an action-following 9:16 crop with smoothed panning, HDR tone-mapped to SDR, fades, libx264 `veryfast` CRF 20, AAC.

## Optional: local vision re-rank with Ollama

If [Ollama](https://ollama.com) is running on your machine with a vision model (`ollama pull qwen3-vl:4b`, or `gemma3:4b`, `minicpm-v`, `moondream`), `--vision` sends 4 small frames from each candidate clip to it and asks for a clip-worthiness score and a 4-6 word title. The final score becomes 0.7 action + 0.3 vision; titles land in the report and in the file names. Only `127.0.0.1:11434` is ever contacted. If Ollama is not running, no vision model is installed, or the model times out or answers badly, the run continues with the action-only order and leaves one warning line. Pick a model explicitly with `[vision] model = "..."` in the config.

Scores and titles from this pass are AI-generated and may be wrong: a title can misdescribe the moment, and the re-ordering can demote a real highlight. The pass is not yet tuned or measured on real footage, so treat it as an experiment and read `report.json` before trusting a re-ordered list or a title.

## Library use

The CLI is a thin wrapper; the pipeline is a plain library with no global state, so it can run inside your own script or a service.

```python
from clip_anything.config import Options
from clip_anything.pipeline import run

report = run("gameplay.mp4", Options.from_layers({"clips": {"count": 5}}))
for clip in report.ok_clips:
    print(clip.rank, clip.start, clip.end, clip.title, clip.path)
```

`run(video, options, on_event=..., cancel=...)` emits progress events instead of printing and returns the same `Report` that becomes `report.json`.

## Known limits

Measured on 2026-11-12 (see [benchmark.md](benchmark.md)); anything not measured is listed as such.

- The action bar was calibrated on two games (an FPS and a turn-based RPG). It is game-agnostic by construction, but it has not been scored on a third, unseen game yet.
- Top-10 lists on a long match miss moments: on the 40-minute match 8 of 19 labelled moments made the top 10, and one text card still did. Raise `--count` or lower `--min-score` to see more; the report says why each clip was picked.
- Windows in turn-based games can end on a result screen; clips are not yet shaped around menu transitions.
- 1080p60 sources analyse at roughly 100 s per hour (decode-bound), above the one-minute goal. 480p-1080p30 sources are well under it.
- Bounded memory is verified to 3 hours (363 MiB peak); a 10-hour file has not been run.
- Captions and facecam detection were verified on fixtures and the two recordings above, not on a streamer VOD with a webcam.
- The `--vision` pass has not been run against a real Ollama model. Its titles and scores are AI-generated and may be wrong.
- Captions come from automatic speech recognition and may be wrong; check them before posting.
- No human has yet reviewed a batch of clips for "postable without edits"; that review is the next step before claiming it.
- Windows is untested (the code avoids shell-specific paths, nothing more).

## Roadmap

- Window shaping for turn-based games (end a clip before the result screen) and a bar calibrated on more than two games
- Faster analysis on 1080p60 sources (hardware decode for the proxy)
- Desktop app for people who do not want to run anything in a terminal
- Direct posting to TikTok, YouTube Shorts and Reels
- A learned scorer trained on which clips people keep
- Resumable analysis for very long (10 h+) recordings

See [CHANGELOG.md](../CHANGELOG.md) for what shipped.

## Development

```
uv venv --python 3.11 && uv pip install -e '.[dev,captions]'
python scripts/make_test_video.py        # 3-min synthetic video with known bursts
pytest && ruff check .
```

The synthetic video has six injected audio bursts and four motion bursts; the end-to-end test asserts that the top six clips contain all six bursts with build-up before each. See [CONTRIBUTING.md](../CONTRIBUTING.md).
