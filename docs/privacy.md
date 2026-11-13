# Privacy

Clip Anything is a free, non-commercial passion project by an independent developer. This page
is written for people, not lawyers, and every sentence describes what the current code does.
Last updated 13 November 2026.

## What stays on your computer

Everything, unless you turn one of the options below on.

- Your recording is read from your disk. The clips, `report.json` and (with AI mode) a small
  `<clip>.txt` post-text file are written next to it, or wherever `--out` points.
- Analysis is cached in a `.clipanything` folder next to the recording, so a second run with
  different settings takes seconds (`--cache-dir` moves it, `--no-cache` skips it).
- Captions run locally with faster-whisper. Facecam detection, cropping and scoring are plain
  signal processing on your machine.
- The desktop app is a small web page served by the tool itself on `127.0.0.1` (loopback only),
  on a random port, with a token that changes every launch. Other computers cannot reach it, and
  a website you visit cannot read it.
- There is no account, no sign-in, no telemetry, no crash reporting and no update check.

## What can leave your computer, and only when you choose it

| When | What goes where |
|---|---|
| Captions, first run only | The Whisper speech model (about 145 MB) is downloaded from Hugging Face. The command line asks first (or you pass `--yes`); the app's captions checkbox says so. Hugging Face sees your IP address, as with any download. Later runs load it from your disk (`~/.cache/huggingface`, or `HF_HOME`). |
| Local AI (`--ai` with Ollama) | Frames and spoken lines go to Ollama at `127.0.0.1:11434` on your own machine. Nothing leaves it. Pulling a model (`ollama pull …`) downloads that model from ollama.com; the Setup screen asks before running it. |
| Cloud AI (`--ai-provider openai` or `anthropic`, or a key in `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`) | For up to 3 times the number of clips you asked for, 3 to 4 small frames (320 px JPEGs) and the spoken lines of each candidate moment are sent to `api.openai.com` or `api.anthropic.com` under that provider's terms, and your key pays for it. No file names, paths or other clips are included. The key is read from your environment or `--ai-key` for that run only and is never written to disk, the report or logs. The app shows a red line under the AI switch whenever a key is set. |
| Setup (`clip-anything setup` or the app's Set up screen) | Installs ffmpeg with your system package manager (Homebrew, apt, dnf or winget), the captions extra with uv or pip, and pulls an Ollama model. Each line shows the exact command and runs only after you say yes. Those package managers download from their own servers. The Ollama installer is printed for you to run yourself. |
| Installing or updating the tool | `uvx` / `pip` fetch the package from PyPI (or GitHub if you use that line); the desktop app is downloaded from GitHub Releases. |
| Links in the app and docs | GitHub and Discord links open in your browser only when you click them. |

Verified on a captioned run with the model already present: zero network sockets opened.

## What is stored, where, and how to delete it

| Item | Where | Delete it |
|---|---|---|
| Clips, `report.json`, `<clip>.txt` | Next to the recording, or `--out` | Delete the files; the app's **Delete** button removes one clip |
| Analysis cache | `.clipanything/` next to the recording | Delete that folder, or run with `--no-cache` |
| Speech model | `~/.cache/huggingface` (or `HF_HOME`) | Delete that folder |
| Recent runs (paths, settings, clip counts; never footage) | `recent.json` in the app data folder: macOS `~/Library/Application Support/clip-anything`, Windows `%APPDATA%\clip-anything`, Linux `$XDG_DATA_HOME/clip-anything` or `~/.local/share/clip-anything` | **Forget all** on the home screen, or delete the file |
| Window size and last output folder | `prefs.json` in the same folder | Delete the file or the folder |
| "Got it" on the first-run hints | Browser local storage for the app's local address (key `clip-anything.first-run`) | Clear site data for `127.0.0.1` in your browser; in the native window, delete the app data folder |

Nothing is kept anywhere else, and we never receive any of it.

## The desktop app is not signed yet

Code-signing certificates cost money; until they are bought, macOS says "Apple could not verify"
and Windows SmartScreen says "Windows protected your PC". That dialog means the publisher is
unknown to the operating system, not that something was found. Before you click past it, check
the file's SHA-256 against `SHA256SUMS.txt` on the same release page (`shasum -a 256 <file>` on
macOS, `Get-FileHash <file>` in PowerShell). The exact click path is in
[docs/desktop.md](desktop.md).

## AI-generated text

Titles, hooks and the "reaction" caption come from a model and can be wrong, bland or
inappropriate; captions come from speech recognition and can mishear. Every such field in
`report.json` carries `ai_generated: true`, the run prints a disclosure line, and the app labels
it. Read them before you post.

## Your recordings are your responsibility

The tool does not look at who is in a recording and we never see it. You are responsible for
having the right to process and publish what you give it: the game publisher's video policy,
music that played during the stream, and the voice or likeness of anyone in your facecam or
party chat. See [docs/terms.md](terms.md).

## Contact

Security problems: use GitHub's private reporting at
https://github.com/shreyassaw5394/clip-anything/security/advisories/new (see
[SECURITY.md](../SECURITY.md)). Need help or have an idea? [Discord](https://discord.gg/s8wj7tBAM),
[email](mailto:shreyassaw@gmail.com), or
[upvote the hosted version](https://github.com/shreyassaw5394/shipatmidnight-ideas/issues/7).

This page is a plain-language description, not legal advice. If it ever disagrees with the
code, the code is the truth and the page gets fixed.
