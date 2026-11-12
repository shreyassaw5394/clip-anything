# clip-anything (npm launcher)

A thin launcher for the [Clip Anything](https://github.com/shreyassaw5394/clip-anything) Python CLI: long gameplay recording in, the top N vertical (9:16) highlight clips out, with a `report.json` that says why each moment was picked. Free, local, open source. Nothing is uploaded.

This package contains no video code. Its only job is to find `uvx` (from [uv](https://docs.astral.sh/uv/)) or `pipx` on your PATH and run `uvx clip-anything <your arguments>`. If neither is installed it prints the install lines and exits.

```
npx clip-anything gameplay.mp4
```

Needs:

- `uv` (`curl -LsSf https://astral.sh/uv/install.sh | sh`, or `winget install astral-sh.uv`) or `pipx`
- `ffmpeg` and `ffprobe` on PATH (`brew install ffmpeg`, `sudo apt install ffmpeg`, `winget install Gyan.FFmpeg`)
- Python 3.11+ (uv fetches one if needed)

All options, exit codes, the config file and the full documentation live in the main README. If you already have uv, `uvx clip-anything gameplay.mp4` is the same thing with one hop fewer.

Zero dependencies. MIT. Game names appear only to describe what a recording contains; Clip Anything is not affiliated with or endorsed by any game publisher.
