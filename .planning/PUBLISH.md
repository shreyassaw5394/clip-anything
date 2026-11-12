# PUBLISH — exact commands for the owner (nothing here has been run; no repo, no tag, no upload exists)

Built 2026-11-12 by the 05-01 executor from a clean `git archive HEAD` (commit 21eccae or later):
`dist/clip_anything-0.1.0-py3-none-any.whl` (72 KB) and `dist/clip_anything-0.1.0.tar.gz` (63 KB).
Checked: wheel = `clip_anything/*.py` + `dist-info/licenses/{LICENSE,NOTICE}`; sdist adds README, CHANGELOG, NOTICE,
`clip-anything.toml`, pyproject; no `tests/`, no fixtures, no footage, no `.planning`. `uvx --from dist/*.whl` and
`pipx run --spec dist/*.whl` both print `clip-anything 0.1.0`.

## 0. Before anything
```
cd ~/clip-anything
git reset -q && git status --short          # must be clean (only untracked local junk)
rm -rf dist && uv build                      # rebuild from the final commit
tar tzf dist/*.tar.gz | grep -v '^clip_anything-0.1.0/clip_anything/' ; unzip -l dist/*.whl | grep -i licen
```
Fix in README before publishing (PyPI renders the README from the sdist, relative image links break):
replace `![demo](assets/demo.gif)` with the absolute raw URL once the GitHub repo exists, e.g.
`https://raw.githubusercontent.com/<owner>/clip-anything/main/assets/demo.gif`. Also set `[project.urls]` in
pyproject (`Homepage`, `Source`, `Changelog`) and move `## Unreleased (0.1.0)` → `## 0.1.0 — 2026-11-15` in CHANGELOG.md.

## 1. GitHub (public repo, MIT)
```
gh repo create clip-anything --public --source . --remote origin --description "Free, local CLI: long gameplay recording in, top N vertical highlight clips out" --push
git tag -a v0.1.0 -m "clip-anything 0.1.0" && git push origin v0.1.0
```

## 2. TestPyPI dry run
```
uv publish --publish-url https://test.pypi.org/legacy/ --token "$TESTPYPI_TOKEN" dist/*
# verify from a clean cache:
UV_CACHE_DIR=$(mktemp -d) uvx --index-url https://test.pypi.org/simple/ --index-strategy unsafe-best-match \
  --from clip-anything==0.1.0 clip-anything --version
```
(`--index-strategy unsafe-best-match` lets the deps resolve from PyPI while the package comes from TestPyPI.)

## 3. PyPI
```
uv publish --token "$PYPI_TOKEN" dist/*
UV_CACHE_DIR=$(mktemp -d) uvx clip-anything --version        # expect: clip-anything 0.1.0
pipx run clip-anything --help
```
Trusted publishing instead of a token: add a PyPI "pending publisher" (owner/clip-anything, workflow `publish.yml`,
environment `pypi`) and a GitHub Actions workflow with `pypa/gh-action-pypi-publish@release/v1` on tag push.

## 4. After publish
- GitHub release v0.1.0 with the CHANGELOG 0.1.0 section and `assets/demo.gif`.
- Ship at Midnight: products page + log entry (demo.gif, `uvx clip-anything gameplay.mp4`).
- Next version: bump `pyproject.toml` `version` and `clip_anything/__init__.py` `__version__` together (the CLI prints the latter).
