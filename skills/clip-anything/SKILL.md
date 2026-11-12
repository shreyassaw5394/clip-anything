---
name: clip-anything
description: "Use when the user wants clips, highlights, shorts or reels cut from a gameplay recording, stream VOD or a folder of recordings. Runs the local clip-anything CLI: previews the picks, renders 9:16 clips, explains each pick from report.json. Not for editing a clip by hand or for uploading."
version: 0.1.0
license: MIT
allowed-tools: Bash Read Glob
metadata:
  author: Ship at Midnight Authors <65935477+shreyassaw5394@users.noreply.github.com>
  tags: [video, clips, highlights, gameplay, ffmpeg]
---

# clip-anything

## Purpose

Turns a long recording (one file, several files, or a folder that is one session) into the top N vertical highlight clips using the free, local `clip-anything` CLI. The skill drives the tool, shows what it would cut before it cuts, and reads the report so the user knows why each moment was picked. It never uploads, posts or sends footage anywhere; the CLI itself makes no network calls except an optional, one-time Whisper model download that asks first.

## Prerequisites

- `uvx` (from uv) or `pipx` on PATH. The CLI is a Python package; `uvx clip-anything` runs it without an install.
- `ffmpeg` and `ffprobe` on PATH. The CLI exits with code 3 and an install line when they are missing.
- A recording the user can point to: `.mp4 .mkv .mov .m4v .ts .m2ts .mts .webm .avi .flv`, or a folder of them.

## Instructions

Work from the user's current directory. Use the exact paths the user gave; quote them. Do not move, rename or delete footage. Do not install anything beyond what the steps below print as a suggestion for the user to run.

## Workflow

(Use the steps in order; a step that cannot be completed is reported, not skipped.)

1. **Check the tools.** Run `command -v uvx || command -v pipx` and `command -v ffmpeg && command -v ffprobe`. If `uvx` and `pipx` are both missing, print and stop:
   `curl -LsSf https://astral.sh/uv/install.sh | sh` (macOS/Linux) or `winget install astral-sh.uv` (Windows).
   If ffmpeg is missing, print and stop: `brew install ffmpeg` / `sudo apt install ffmpeg` / `winget install Gyan.FFmpeg`.
   Use `pipx run clip-anything` wherever this file says `uvx clip-anything` if only pipx exists.
2. **Resolve the input.** If the user named a file or folder, use it. If they said "my recording" with no path, look for video files in the current directory (`Glob` for the extensions above, newest first). Ask only when there are several plausible inputs or none; otherwise proceed and say which path was used. A folder is passed as-is: the CLI treats it as one session.
3. **Dry run first, always.** Run `uvx clip-anything "<input>" --dry-run --json 2>/dev/null` (add `--count N` if the user named a number). Parse the JSON from stdout. Show a short table: rank, `start` to `end` as mm:ss, `duration_s`, `score`, `title` if present, and the top component from `components`. If `clips` is empty, say so plainly and read `warnings` (a `below_floor` warning means nothing cleared the action bar) before suggesting `--min-score 0` or a lower value.
4. **Render.** Unless the user asked only for a preview, run `uvx clip-anything "<input>"` with the same options, without `--dry-run` and `--json`, so the progress UI shows. Add `--yes` only if the user said captions are wanted and has agreed to the one-time model download; otherwise let the CLI ask. Report the output folder (`./clips` by default, or `--out`).
5. **Explain the picks.** Read `clips/report.json` (`Read` or `python3 -I -c` over the file). For each `ok` clip give one line: the time span, the score, and which signals carried it (`components`: loudness over baseline, audio onsets, motion, audio/motion agreement, static-card penalty, speech bonus when present). Mention `layout` when it is `facecam` and `captions` when true. List every entry in `warnings` in plain words; the tool degrades out loud and the user should hear it.
6. **Offer the knobs**, one line each, only the ones that fit what the user saw:
   - `--count N` more or fewer clips (it is a maximum; quiet sessions return fewer)
   - `--min-score 0.3` lower the action bar; `--min-score 0` rank the file against itself
   - `--min 20 --max 60` clip length bounds in seconds
   - `--crop center` static centre crop instead of following the action
   - `--no-captions` never burn captions; `--facecam off` no webcam stack
   - `--vision` local Ollama re-rank and titles (experimental; only talks to `127.0.0.1:11434`)
   - `--force` overwrite clips from the last run; `--no-cache` ignore cached analysis
   A re-run with different knobs takes seconds because analysis is cached next to the video.
7. **Disclosure.** When captions or titles are present, say once: captions are machine transcription (faster-whisper, local) and titles come from a local vision model; both can be wrong and should be checked before posting.

## Examples

- "Make 5 shorts from last night's stream, it's in ~/Videos/obs/" → step 1, pass the folder, `--count 5` dry run, show the table, render, explain.
- "Why did it pick a loading screen?" → open `report.json`, show that clip's `components` (a high `card` value means the static-card penalty fired but loud onsets still won), suggest `--min-score 0.6` or a higher `w_card` in a `--config` TOML.
- "Just show me what it would cut, don't render" → steps 1 to 3 only.

## Limitations

- Transcript-first moments (a joke with no action) score low by design; the tool ranks action, speech is a bonus.
- The action bar was calibrated on two games; an unseen game may return fewer clips than asked. Say so instead of forcing clips with `--min-score 0` unprompted.
- 1080p60 sources analyse at roughly 100 s per hour; a multi-hour file is a wait, not a hang.
- The skill does not edit clips, pick thumbnails, or post anywhere. Posting is the user's step.

## Troubleshooting

- Exit 2: bad input (missing path, unsupported file, folder with no videos). Show the CLI's message.
- Exit 3: ffmpeg or ffprobe missing. Print the install line for the user's OS from step 1.
- Exit 1: nothing rendered. Read `warnings` in the dry-run JSON; usually `below_floor`.
- Captions written as a sidecar `.ass` instead of burned in: the ffmpeg build has no libass (stock Homebrew formula). An `ffmpeg-full` build on PATH fixes it; everything else still works.
- `--vision` had no effect: Ollama is not running or has no vision model; the run continues action-only and leaves one warning.
