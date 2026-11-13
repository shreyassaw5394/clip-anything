# Clip Anything desktop app

A small window for people who do not use a terminal: choose a recording (or a folder of
them), choose where the clips go, press **Make clips**. It is the same local pipeline as the
command line tool, with ffmpeg included, so nothing else needs installing. Nothing is
uploaded; the app never talks to the network except the one-time speech-model download when
captions are on (the checkbox says so).

Downloads: the **Releases** page of the repository
(`clip-anything-macos-arm64.dmg` / `.zip` for Apple silicon Macs, `clip-anything-windows-x86_64.zip`
for Windows 10/11, `clip-anything-macos-x86_64.zip` for Intel Macs when that build is present).

From a source install the same app is `clip-anything app` (or `clip-anything-gui`); add the
`[app]` extra (`uv tool install "clip-anything[app]"`) for the native window.

## The builds are not signed yet

Signing certificates (Apple Developer ID, Windows code signing) cost money and take time; they
will come later. Until then the operating system warns once. This is expected; here is the
exact click path.

### macOS: "Apple could not verify..."

1. Open the `.dmg` (or unzip) and drag **Clip Anything** to Applications (or anywhere).
2. Double-click it. macOS shows *"Clip Anything" Not Opened* / *Apple could not verify ... is
   free of malware*. Click **Done** (not *Move to Trash*).
3. Open **System Settings → Privacy & Security**, scroll down to the Security section: a line
   says *"Clip Anything" was blocked to protect your Mac*. Click **Open Anyway**, confirm with
   your password or Touch ID, then **Open** in the last dialog.
4. From now on it opens normally.

On macOS 13 and 14 the shortcut also works: **right-click the app → Open → Open**.

If the app is "damaged and can't be opened", the quarantine flag was set on the zip; remove it
once in Terminal: `xattr -dr com.apple.quarantine "/Applications/Clip Anything.app"`.

### Windows: "Windows protected your PC"

1. Unzip `clip-anything-windows-x86_64.zip` anywhere (for example your Desktop). Keep the folder
   together: `Clip Anything.exe` needs the `_internal` folder next to it.
2. Double-click **Clip Anything.exe**. SmartScreen shows a blue *Windows protected your PC* box.
3. Click **More info**, then **Run anyway**.
4. Windows remembers the choice for that file.

Some antivirus products flag any unsigned PyInstaller app the first time; "allow" it or check the
file's SHA-256 against `SHA256SUMS.txt` on the release page.

## Using it

The app is the same tool as the command line, as a window. It runs a small local server on
127.0.0.1 (a random port and a per-launch token, loopback only) and shows the page in a native
window; with no native window available it opens in your default browser instead and the
terminal says so.

1. **Drop a recording** (or a folder of recordings: one session, clips never cross a file) on
   the page, or use **Choose a recording** / **Choose a folder**. Recent runs are listed below
   so a second pass is one click.
2. **Settings** sit in one strip, all visible: how many clips (a maximum; only moments above the
   action bar are returned), length (short 15–30 s, normal 15–45 s, long 30–60 s), captions when
   there is speech, facecam stacking, crop follows the action, and **With AI** (titles, hooks and
   a second opinion from a local Ollama model; if an OpenAI/Anthropic key is set in your
   environment the switch says that frames and spoken lines leave the computer).
3. **Make clips.** The run screen is one big bar with the stage name and a time estimate, and
   the action-score curve draws as the analysis streams; the picked moments pop in as markers.
   **Cancel** (or Esc) stops after the current step; half-written files are removed.
4. **Your clips**: a grid of the vertical clips themselves. Hover to preview muted, drag across
   a clip to scrub, press play for sound. Each card shows rank, time in the recording, score,
   why it was picked and (with AI) the title and hook. Per clip: **Open**, **Reveal in folder**,
   **Copy post text**, **Delete**. For the run: **Open folder**, **Re-run with different
   settings** (uses the saved analysis: seconds), **Export report** (`report.json`).
5. **Set up** checks ffmpeg, captions and the optional local AI, one line each, with an install
   button per missing item that shows the exact command and asks before running it.

Everything is keyboard-reachable; the interface honours reduced-motion settings and works down
to about 760 px wide.

Analysis speed is the same as the CLI: a one-hour 1080p recording takes about a minute on a
recent laptop, plus a few seconds per clip to render.

## Prefer the terminal?

One paste installs `uv`, `ffmpeg` and the tool:

- macOS / Linux: `curl -fsSL https://raw.githubusercontent.com/shreyassaw5394/clip-anything/main/scripts/install.sh | sh`
- Windows (PowerShell): `irm https://raw.githubusercontent.com/shreyassaw5394/clip-anything/main/scripts/install.ps1 | iex`

Then `clip-anything your-recording.mp4`. The app is also there as `clip-anything app`
(`clip-anything-gui` still works); `--browser` forces the browser, `--window` the native window.

## Building the app yourself

```
uv sync --extra desktop --extra app     # --extra app = pywebview for the native window
uv run python packaging/build.py        # fetches the pinned ffmpeg, runs PyInstaller, zips
```

`packaging/fetch_ffmpeg.py` holds the exact ffmpeg download URLs and SHA-256 checksums. The
release workflow (`.github/workflows/release.yml`) runs the same script on a `v*` tag and
attaches the files to a draft release. ffmpeg is a separate GPL-licensed program shipped next to
the MIT app; see `THIRD_PARTY_NOTICE.txt` inside the bundle.

## What the desktop build does not do (v0.1)

- No `--vision` (Ollama) option in the window; use the CLI for that.
- Windows build is produced by CI only; it has not been clicked through by a human yet.
- `--run <recording> --out <folder>` runs the same job without a window (used for smoke tests).
- Not signed or notarised (see above).
