# Clip Anything desktop app

A small window for people who do not use a terminal: choose a recording (or a folder of
them), choose where the clips go, press **Make clips**. It is the same local pipeline as the
command line tool, with ffmpeg included, so nothing else needs installing. Nothing is
uploaded; the app never talks to the network except the one-time speech-model download when
captions are on (the checkbox says so).

Downloads: the **Releases** page of the repository
(`clip-anything-macos-arm64.dmg` / `.zip` for Apple silicon Macs, `clip-anything-windows-x86_64.zip`
for Windows 10/11, `clip-anything-macos-x86_64.zip` for Intel Macs when that build is present).

(Screenshot to follow: the window is a single column of buttons, options, a progress bar and the clip list.)

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

- **Choose recording...** picks one or more video files; **Choose folder of recordings...** treats
  a folder as one session (clips never cross a file boundary).
- **Clips go to...** defaults to a `clips` folder next to the recording.
- **Number of clips** is a maximum: only moments that clear the action bar are returned.
- **Captions** are included (faster-whisper). The first captioned run downloads the ~150 MB
  speech model once, as the checkbox says; untick it for a fully offline run. Captions are machine
  transcription: read them before posting.
- **Facecam** `auto` looks for a static camera corner and stacks it above the gameplay.
- **Vertical crop** `follow` keeps the action in frame; `center` is a plain centre crop.
- **Cancel** stops after the current step; half-written files are removed.
- When it finishes, the list shows each clip's time and score and **Open clips folder** opens
  the output in Finder / Explorer. `report.json` next to the clips explains every pick.

Analysis speed is the same as the CLI: a one-hour 1080p recording takes about a minute on a
recent laptop, plus a few seconds per clip to render.

## Prefer the terminal?

One paste installs `uv`, `ffmpeg` and the tool:

- macOS / Linux: `curl -fsSL https://raw.githubusercontent.com/shreyassaw5394/clip-anything/main/scripts/install.sh | sh`
- Windows (PowerShell): `irm https://raw.githubusercontent.com/shreyassaw5394/clip-anything/main/scripts/install.ps1 | iex`

Then `clip-anything your-recording.mp4`. The GUI is also available from a source or `uv tool`
install as `clip-anything-gui` (or `python -m clip_anything.gui`).

## Building the app yourself

```
uv sync --extra desktop
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
