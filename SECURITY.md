# Security

Clip Anything is a local tool: it reads video files you point it at, runs `ffmpeg`, writes clips
next to them, and talks to nothing on the network unless you turn an option on: the one-time
Whisper model download (asked first), Ollama on `127.0.0.1:11434` (`--ai`, `--vision`), or a
cloud AI provider when you set your own OpenAI/Anthropic key (frames and caption text leave the
machine, see [docs/privacy.md](docs/privacy.md)). There is no account and no telemetry.

Threat model in one line: the desktop app is an HTTP server bound to `127.0.0.1` on a random
port; every request must carry a loopback `Host`, a same-origin (or absent) `Origin`, and the
per-launch bearer token, and the page runs under a strict CSP with no inline code or third-party
requests. Anything that lets a website, another local user or a crafted file get past that is in
scope.

## Reporting a vulnerability

Please report privately, not in a public issue or on Discord. Use GitHub's private reporting:

https://github.com/shreyassaw5394/clip-anything/security/advisories/new

Include the version (`clip-anything --version`), your OS, and a way to reproduce (a small
synthetic file from `scripts/make_test_video.py` is ideal; please do not send footage). You
should hear back within 7 days. Fixes ship as a new PyPI release and a note in `CHANGELOG.md`;
credit is given if you want it.

## Scope

In scope: anything that lets a crafted video, folder, config file, Ollama reply or file name
run code, write outside the output and cache folders, read files it should not, or make a
network connection [docs/privacy.md](docs/privacy.md) does not describe; anything that lets a
web page or another process on the machine drive the app's local server.

Out of scope: bugs in `ffmpeg`, Ollama or Python packages themselves (report those upstream),
and clips that are badly chosen.

## Supported versions

Only the latest release (PyPI package and desktop builds) receives fixes.
