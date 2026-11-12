# Security

Clip Anything is a local command line tool: it reads video files you point it at, runs
`ffmpeg`, writes clips next to them, and talks to nothing on the network except an optional,
one-time Whisper model download (asked first) and, with `--vision`, an Ollama server on
`127.0.0.1`. There is no account, no server and no telemetry.

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's private reporting:

https://github.com/shreyassaw5394/clip-anything/security/advisories/new

Include the version (`clip-anything --version`), your OS, and a way to reproduce (a small
synthetic file from `scripts/make_test_video.py` is ideal; please do not send footage). You
should hear back within 7 days. Fixes ship as a new PyPI release and a note in `CHANGELOG.md`;
credit is given if you want it.

## Scope

In scope: anything that lets a crafted video, folder, config file, Ollama reply or file name
run code, write outside the output and cache folders, read files it should not, or make a
network connection the README does not describe.

Out of scope: bugs in `ffmpeg`, Ollama or Python packages themselves (report those upstream),
and clips that are badly chosen.

## Supported versions

Only the latest release on PyPI receives fixes.
