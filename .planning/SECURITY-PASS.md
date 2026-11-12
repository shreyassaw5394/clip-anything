# Security and legal pass, 2026-11-12 (pre-publication)

Not legal advice; a risk-reduction pass by the executor. Commits: ad372ec, 088edef, 854d223, 911186f, plus the docs commit after this file.

## Checked
- Secrets: `gitleaks git .` over 49 commits: no leaks. History grep for tokens/keys/PEM/emails: only the noreply commit address. No footage, no `.clipanything`, no `tests/fixtures/*.mp4` tracked; `assets/demo.cast` has no home paths or hostnames. `.planning` has local `/Users/...` paths (kept) and no token-like strings; one personal-media phrase in TEST-FOOTAGE.md reworded.
- Dependencies (fresh venv from the wheel + `captions`, pip-licenses): all permissive. Weak copyleft only as unmodified separate libraries: LGPL FFmpeg inside the opencv and PyAV wheels, MPL-2.0 part of tqdm. No GPL/AGPL/source-available. NOTICE now lists PyAV, onnxruntime, huggingface_hub, tqdm; full table in `THIRD_PARTY_LICENSES.md` (in the wheel and sdist).
- Code: every ffmpeg/ffprobe call is an argv list (no shell); user paths go through `os.fspath`; captions file is copied into a private temp dir so the filter graph never sees a user path; `.part` outputs and temp dirs are removed on failure/cancel; config is `tomllib` (data only, unknown keys rejected); Whisper download only with `--yes`/TTY confirm (`local_files_only` otherwise); Ollama client stdlib `urllib` with timeouts; no telemetry; `--json` contains only the user's own input/output paths.

## Changed
- `vision.py`: responses capped at 1 MiB; `base` must be plain http on 127.0.0.1/localhost/::1 or the pass is skipped. `cache.py`: a symlinked `.clipanything` (or id dir) disables the cache instead of being followed. Tests added.
- `pyproject.toml`: upper bounds on majors, classifiers, `[project.urls]` (GitHub + shipatmidnight.dev/clip-anything), `license-files`, anchored sdist includes (an `npm/LICENSE` had slipped in). `uv.lock` added.
- New: SECURITY.md (advisory flow only: the owner's email is not public on GitHub), CODEOWNERS, CONTRIBUTING.md, `.github/workflows/ci.yml` (push to main + PR, `permissions: contents: read`, checkout `persist-credentials: false`, actions pinned to SHAs, macOS+Ubuntu x 3.11/3.13, `uv sync --frozen`, ruff, pytest, wheel check), `dependabot.yml` (pip + actions, weekly, 7-day cooldown), minimal issue template, `publish.yml.disabled` (PyPI trusted publishing draft, off until renamed).
- README: absolutes softened ("Most"/"usually" -> "Many"/"often"; "works for any game" -> built game-agnostic, measured on two); AI/ASR disclosure next to `--vision` and captions; as-is/no-warranty line; trademark line; absolute image URLs for PyPI. CHANGELOG line for the repo tooling.

## Only the owner can do (after `gh repo create`)
1. Branch protection on `main` (CI job name is `test (...)` per matrix; require all four):
```
gh api -X PUT repos/shreyassaw5394/clip-anything/branches/main/protection --input - <<'JSON'
{"required_status_checks":{"strict":true,"contexts":["test (ubuntu-latest, py3.11)","test (ubuntu-latest, py3.13)","test (macos-latest, py3.11)","test (macos-latest, py3.13)"]},
 "enforce_admins":true,"required_pull_request_reviews":{"required_approving_review_count":0},
 "restrictions":null,"allow_force_pushes":false,"allow_deletions":false,"required_linear_history":true,"required_conversation_resolution":true}
JSON
```
2. Secret scanning + push protection, Dependabot alerts + security updates, private vulnerability reporting:
```
gh api -X PATCH repos/shreyassaw5394/clip-anything -f 'security_and_analysis[secret_scanning][status]=enabled' -f 'security_and_analysis[secret_scanning_push_protection][status]=enabled'
gh api -X PUT repos/shreyassaw5394/clip-anything/vulnerability-alerts
gh api -X PUT repos/shreyassaw5394/clip-anything/automated-security-fixes
gh api -X PUT repos/shreyassaw5394/clip-anything/private-vulnerability-reporting
```
3. PyPI: enable 2FA on the account; prefer the trusted publisher (steps in the header of `publish.yml.disabled`) over `uv publish --token`; if a token is used once, delete it afterwards.
4. Unverified here: the CI matrix on real runners (apt ffmpeg 6.1 must have libx265/libvpx/libsvtav1/prores for the input fixtures; macOS runner brew install time). Watch the first run.
