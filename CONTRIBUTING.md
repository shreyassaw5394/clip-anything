# Contributing

Thanks for looking. Clip Anything is a small, free passion project; fixes and well-scoped
features are welcome.

## Setup

```
uv sync --extra dev --extra captions     # or: uv venv && uv pip install -e '.[dev,captions]'
uv run pytest && uv run ruff check .
```

Tests build their own small synthetic videos under `tests/fixtures/` (needs `ffmpeg` on PATH).
Never commit footage, fixtures or anything under `.clipanything/`.

## Pull requests

- One change per PR, with a test when behaviour changes. CI must be green (ruff + pytest on
  macOS and Ubuntu, Python 3.11 and 3.13).
- Keep the pipeline free of global state, prints and exits: only `cli.py` talks to the user.
- Every user-facing option lives in `config.py` and in the README option table.
- Security problems go through `SECURITY.md`, not a PR.

## Licence

By contributing you agree that your contribution is licensed under the MIT licence in
`LICENSE`. Do not add dependencies with copyleft licences without discussing it first.
