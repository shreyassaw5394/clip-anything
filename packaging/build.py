#!/usr/bin/env python3
"""Local/CI build of the desktop app: fetch pinned ffmpeg, run PyInstaller, zip (and on macOS
also a .dmg), print sizes. Run from the repo root with the project environment active:
    python packaging/build.py [--skip-fetch] [--no-captions] [--dist DIR]"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
APP = "Clip Anything"


def _mib(p: Path) -> float:
    if p.is_file():
        return p.stat().st_size / 2**20
    files = (f for f in p.rglob("*") if f.is_file() and not f.is_symlink())
    return sum(f.stat().st_size for f in files) / 2**20


def _zip_dir(src: Path, out: Path) -> None:
    out.unlink(missing_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in sorted(src.rglob("*")):
            if f.is_symlink() or f.is_file():
                info = zipfile.ZipInfo.from_file(f, str(f.relative_to(src.parent)))
                info.compress_type = zipfile.ZIP_DEFLATED
                if f.is_symlink():
                    info.external_attr = 0o120755 << 16
                    zf.writestr(info, os.readlink(f))
                else:
                    info.external_attr = (f.stat().st_mode & 0xFFFF) << 16
                    with open(f, "rb") as fh:
                        zf.writestr(info, fh.read())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-fetch", action="store_true")
    ap.add_argument("--no-captions", action="store_true", help="leave faster-whisper out")
    ap.add_argument("--dist", default=str(DIST), help="output folder (default dist/)")
    args = ap.parse_args(argv)
    dist = Path(args.dist).resolve()
    work = dist / "build"
    env = dict(os.environ)
    if args.no_captions:
        env["CLIP_ANYTHING_BUNDLE_CAPTIONS"] = "0"
    if not args.skip_fetch:
        subprocess.run([sys.executable, str(ROOT / "packaging" / "fetch_ffmpeg.py")], check=True)
    for stale in (dist / APP, dist / f"{APP}.app", work / "clip_anything"):
        shutil.rmtree(stale, ignore_errors=True)
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(ROOT / "packaging" / "clip_anything.spec"),
         "--noconfirm", "--distpath", str(dist), "--workpath", str(work)],
        check=True, cwd=ROOT, env=env,
    )  # fmt: skip
    arch = platform.machine().lower().replace("amd64", "x86_64")
    if sys.platform == "darwin":
        src = dist / f"{APP}.app"
        tag = f"macos-{arch}"
    elif sys.platform == "win32":
        src = dist / APP
        tag = "windows-x86_64"
    else:
        src = dist / APP
        tag = f"linux-{arch}"
    zip_out = dist / f"clip-anything-{tag}.zip"
    _zip_dir(src, zip_out)
    print(f"folder {src.name}: {_mib(src):.0f} MiB; {zip_out.name}: {_mib(zip_out):.0f} MiB")
    if sys.platform == "darwin" and shutil.which("hdiutil"):
        dmg = dist / f"clip-anything-{tag}.dmg"
        dmg.unlink(missing_ok=True)
        subprocess.run(
            ["hdiutil", "create", "-volname", APP, "-srcfolder", str(src), "-ov", "-format",
             "UDZO", str(dmg)],
            check=True, stdout=subprocess.DEVNULL,
        )  # fmt: skip
        print(f"{dmg.name}: {_mib(dmg):.0f} MiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
