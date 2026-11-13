# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-folder build of the desktop app. Run from the repo root:
    python packaging/fetch_ffmpeg.py && pyinstaller packaging/clip_anything.spec --noconfirm
faster-whisper (captions) is bundled unless CLIP_ANYTHING_BUNDLE_CAPTIONS=0 (saves ~150 MB).
The app UI (clip_anything/app/static) is always bundled; pywebview (native window) when the
[app] extra is installed in the build environment. Sizes: see docs/desktop.md."""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 - provided by PyInstaller
FF = ROOT / "packaging" / "ffmpeg"
APP = "Clip Anything"

binaries = []
datas = [
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "NOTICE"), "."),
    (str(ROOT / "THIRD_PARTY_LICENSES.md"), "."),
    (str(ROOT / "packaging" / "THIRD_PARTY_NOTICE.txt"), "."),
]
for f in sorted((ROOT / "packaging" / "licences").glob("*")):
    if f.is_file():
        datas.append((str(f), "ffmpeg"))  # GPL/LGPL texts for the bundled ffmpeg
if FF.is_dir():
    for f in sorted(FF.iterdir()):
        if f.name.startswith("LICENSE"):
            datas.append((str(f), "ffmpeg"))
        elif f.is_file():
            binaries.append((str(f), "ffmpeg"))
# the app UI (html/css/js/fonts) ships as package data next to clip_anything/app
static = ROOT / "clip_anything" / "app" / "static"
for f in static.rglob("*"):
    if f.is_file():
        datas.append((str(f), str(Path("clip_anything/app/static") / f.parent.relative_to(static))))
icon_png = ROOT / "assets" / "icon.png"
if icon_png.is_file():
    datas.append((str(icon_png), "assets"))
icon = None
if sys.platform == "win32" and (ROOT / "assets" / "icon.ico").is_file():
    icon = str(ROOT / "assets" / "icon.ico")
elif sys.platform == "darwin" and (ROOT / "assets" / "icon.icns").is_file():
    icon = str(ROOT / "assets" / "icon.icns")

bundle_captions = os.environ.get("CLIP_ANYTHING_BUNDLE_CAPTIONS", "1") != "0"
excludes = ["matplotlib", "PyQt5", "PyQt6", "PySide2", "PySide6", "IPython", "pytest"]
hiddenimports = ["clip_anything.pipeline", "clip_anything.render", "clip_anything.speech",
                 "clip_anything.facecam", "clip_anything.captions", "clip_anything.vision",
                 "clip_anything.app.server", "clip_anything.app.launch", "clip_anything.setup_cmd",
                 "clip_anything.ai"]
# native window when the [app] extra (pywebview) is installed in the build env; otherwise the
# bundle opens the default browser (gui.py decides at run time)
try:
    import webview  # noqa: F401

    hiddenimports += collect_submodules("webview")
    datas += collect_data_files("webview")
    HAVE_WEBVIEW = True
except ImportError:
    HAVE_WEBVIEW = False
print(f"clip_anything.spec: pywebview {'bundled' if HAVE_WEBVIEW else 'not installed: browser mode'}")
if bundle_captions:
    # faster_whisper ships the Silero VAD model as package data; ctranslate2 loads its
    # backends lazily
    datas += collect_data_files("faster_whisper")
    hiddenimports += collect_submodules("faster_whisper") + ["ctranslate2", "tokenizers", "av"]
else:
    excludes += ["faster_whisper", "ctranslate2", "torch", "huggingface_hub", "tokenizers", "av"]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name=APP,
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=APP)
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP}.app",
        icon=icon,
        bundle_identifier="dev.shipatmidnight.clip-anything",
        info_plist={
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
            "CFBundleShortVersionString": os.environ.get("CLIP_ANYTHING_VERSION", "0.1.0"),
            "NSHumanReadableCopyright": "MIT. ffmpeg (GPL v3) ships as a separate program; see THIRD_PARTY_NOTICE.txt.",
        },
    )
