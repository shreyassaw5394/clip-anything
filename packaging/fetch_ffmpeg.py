#!/usr/bin/env python3
"""Download the ffmpeg/ffprobe build bundled with the desktop app, pinned by URL + SHA-256.

Windows: BtbN FFmpeg-Builds (GPL, shared DLLs: the LGPL build has no libx264, which the clip
encoder needs). macOS: ffmpeg-static b6.1.1 (GPL, static, arm64 and x86_64). ffmpeg runs as a
separate process; its licence text travels with it in packaging/ffmpeg/LICENSE*.
Usage: python packaging/fetch_ffmpeg.py [--dest packaging/ffmpeg] [--target win64|mac-arm64|mac-x64]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import platform
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

BTBN = "https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-11-12-15-40/"
STATIC = "https://github.com/eugeneware/ffmpeg-static/releases/download/b6.1.1/"

PINS: dict[str, list[tuple[str, str, str]]] = {
    # target: [(url, sha256, kind)]  kind = zip (take bin/ffmpeg*, bin/*.dll, LICENSE.txt) | file
    "win64": [
        (
            BTBN + "ffmpeg-n9.0.2-57-gd838f9f9ae-win64-gpl-shared-9.0.zip",
            "87a17e366ceb90219e292128b4b23bcf9a929109639b23f5c45040848c87ced4",
            "zip",
        ),
    ],
    "mac-arm64": [
        (
            STATIC + "ffmpeg-darwin-arm64",
            "a90e3db6a3fd35f6074b013f948b1aa45b31c6375489d39e572bea3f18336584",
            "ffmpeg",
        ),
        (
            STATIC + "ffprobe-darwin-arm64",
            "bb2db6f5d8cef919da12fbf592119a987202a8c060a886f3cab091f9cab90b64",
            "ffprobe",
        ),
        (
            STATIC + "darwin-arm64.LICENSE",
            "cb48bf09a11f5fb576cddb0431c8f5ed0a60157a9ec942adffc13907cbe083f2",
            "LICENSE.txt",
        ),
    ],
    "mac-x64": [
        (
            STATIC + "ffmpeg-darwin-x64",
            "ebdddc936f61e14049a2d4b549a412b8a40deeff6540e58a9f2a2da9e6b18894",
            "ffmpeg",
        ),
        (
            STATIC + "ffprobe-darwin-x64",
            "fa3add0ce901f7241abe0dfc0155d958fc834aca3f8ce61f87cc712ae669c1e0",
            "ffprobe",
        ),
        (
            STATIC + "darwin-x64.LICENSE",
            "2e1d16c72fd74e12063776371da757322f8b77589386532f4fd8634bde7de1af",
            "LICENSE.txt",
        ),
    ],
}


def default_target() -> str:
    if sys.platform == "win32":
        return "win64"
    if sys.platform == "darwin":
        return "mac-arm64" if platform.machine() == "arm64" else "mac-x64"
    raise SystemExit("no pinned ffmpeg for this platform (Linux users install ffmpeg themselves)")


def fetch(url: str, sha256: str) -> bytes:
    print(f"fetch {url}")
    with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310 - pinned https URL
        data = resp.read()
    got = hashlib.sha256(data).hexdigest()
    if got != sha256:
        raise SystemExit(f"checksum mismatch for {url}\n  expected {sha256}\n  got      {got}")
    return data


def install(target: str, dest: Path) -> list[Path]:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    out: list[Path] = []
    for url, sha, kind in PINS[target]:
        data = fetch(url, sha)
        if kind == "zip":
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for m in zf.infolist():
                    name = Path(m.filename).name
                    parent = Path(m.filename).parent.name
                    wanted = name.endswith(".dll") or name in ("ffmpeg.exe", "ffprobe.exe")
                    keep = (parent == "bin" and wanted) or name == "LICENSE.txt"
                    if keep and not m.is_dir():
                        p = dest / name
                        p.write_bytes(zf.read(m))
                        out.append(p)
        else:
            p = dest / kind
            p.write_bytes(data)
            if kind in ("ffmpeg", "ffprobe"):
                p.chmod(0o755)
            out.append(p)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dest", default=str(Path(__file__).resolve().parent / "ffmpeg"))
    ap.add_argument("--target", choices=sorted(PINS), default=None)
    args = ap.parse_args(argv)
    target = args.target or default_target()
    files = install(target, Path(args.dest))
    total = sum(p.stat().st_size for p in files)
    print(f"{target}: {len(files)} files, {total / 2**20:.1f} MiB -> {args.dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
