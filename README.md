# clip-anything

Free, local, open-source CLI. Long gameplay recording in, top N vertical (9:16) highlight clips + `report.json` out. Picks moments by action (audio bursts now; motion and cuts next), so it works with zero speech. No account, no upload, no watermark.

```
uvx clip-anything gameplay.mp4 --count 10
```

Needs `ffmpeg` + `ffprobe` on PATH (`brew install ffmpeg`, `sudo apt install ffmpeg`, `winget install Gyan.FFmpeg`).

## Usage

```
clip-anything <video> [--count 10] [--min 15] [--max 45] [--out ./clips]
                      [--dry-run] [--json] [--config clip-anything.toml] [--no-cache] [--force]
```

- `--dry-run` writes `report.json` only (what would be clipped and why).
- `--json` prints the report to stdout; progress always goes to stderr.
- Exit codes: 0 ok, 1 nothing rendered, 2 bad input, 3 ffmpeg missing.

Output: `clips/<stem>_01_<mm-ss>.mp4` (1080x1920 H.264 + AAC, faststart) and `clips/report.json` with per-clip score, per-signal breakdown, start/end and snap decisions.

## How it works (v1 core)

1. Audio is streamed from ffmpeg at 16 kHz mono; per 0.5 s: RMS, spectral-flux onset, loudness over a rolling 60 s median baseline (so constant music or engine noise does not flatten it).
2. Signals are robust-normalised (rolling median/MAD), gated by informativeness, mixed, smoothed, then peaks are picked.
3. Each peak becomes a 15-45 s window with 60% before / 40% after, snapped to a quiet point; overlapping windows are deduped.
4. Each clip is one ffmpeg pass: centre 9:16 crop, 1080x1920, fades, libx264 veryfast CRF 20.

Analysis signals are cached beside the video in `.clipanything/<id>/` so re-runs with new weights take seconds.

## Library use

```python
from clip_anything.config import Options
from clip_anything.pipeline import run

report = run("gameplay.mp4", Options.from_layers({"clips": {"count": 5}}))
for clip in report.ok_clips:
    print(clip.rank, clip.start, clip.end, clip.path)
```

## Development

```
uv venv --python 3.11 && uv pip install -e '.[dev]'
python scripts/make_test_video.py        # 3-min synthetic video with known bursts
pytest && ruff check .
```

MIT.
