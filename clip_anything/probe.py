"""ffmpeg/ffprobe discovery, preflight, media probing and the 16 kHz audio pipe."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .errors import FFmpegMissing, InputError

EXTRA_PATHS = ["/opt/homebrew/opt/ffmpeg-full/bin", "/usr/local/opt/ffmpeg-full/bin"]

INSTALL_HELP = {
    "Darwin": "brew install ffmpeg        (captions need libass: brew install ffmpeg-full)",
    "Linux": "sudo apt install ffmpeg    (or your distro's package manager)",
    "Windows": "winget install Gyan.FFmpeg   (restart your shell afterwards)",
}


def install_help() -> str:
    sysname = platform.system()
    line = INSTALL_HELP.get(sysname, "see https://ffmpeg.org/download.html")
    return f"ffmpeg is required.\n  {line}\n  https://ffmpeg.org/download.html"


@dataclass(frozen=True)
class FFmpegCaps:
    ffmpeg: str
    ffprobe: str
    version: tuple[int, int]
    captions: bool  # libass `ass` filter present
    filter_file_flag: str  # "-/filter_complex" (>=7) or "-filter_complex_script"


@dataclass(frozen=True)
class MediaInfo:
    path: str
    duration_s: float
    width: int
    height: int
    fps: float
    has_audio: bool
    has_video: bool
    rotation: int
    size_bytes: int
    vcodec: str = ""
    acodec: str = ""
    pix_fmt: str = ""
    color_transfer: str = ""


def _popen_kwargs() -> dict:
    kw: dict = {}
    if os.name == "nt":  # pragma: no cover
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return kw


def _find(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for extra in EXTRA_PATHS:
        cand = Path(extra) / name
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return None


def _version_of(ffmpeg: str) -> tuple[int, int]:
    out = subprocess.run(
        [ffmpeg, "-version"], capture_output=True, text=True, check=False, **_popen_kwargs()
    ).stdout
    m = re.search(r"ffmpeg version\s+n?(\d+)\.(\d+)", out)
    if not m:
        m = re.search(r"ffmpeg version\s+N-\d+", out)
        return (99, 0) if m else (0, 0)  # git builds: assume new
    return int(m.group(1)), int(m.group(2))


def preflight() -> FFmpegCaps:
    """Locate ffmpeg/ffprobe, check version >= 5, detect the ass filter."""
    ffmpeg = _find("ffmpeg")
    ffprobe = _find("ffprobe")
    if not ffmpeg or not ffprobe:
        raise FFmpegMissing("ffmpeg/ffprobe not found on PATH", install_help())
    version = _version_of(ffmpeg)
    if version < (5, 0):
        raise FFmpegMissing(
            f"ffmpeg {version[0]}.{version[1]} is too old (need >= 5.0)", install_help()
        )
    filters = subprocess.run(
        [ffmpeg, "-hide_banner", "-filters"],
        capture_output=True,
        text=True,
        check=False,
        **_popen_kwargs(),
    ).stdout
    captions = bool(re.search(r"^\s*\S+\s+ass\s", filters, re.M))
    flag = "-/filter_complex" if version >= (7, 0) else "-filter_complex_script"
    return FFmpegCaps(ffmpeg, ffprobe, version, captions, flag)


def _fraction(text: str | None) -> float:
    if not text:
        return 0.0
    if "/" in text:
        num, den = text.split("/", 1)
        try:
            return float(num) / float(den) if float(den) else 0.0
        except ValueError:
            return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def probe(path: str | os.PathLike, caps: FFmpegCaps) -> MediaInfo:
    p = Path(path)
    if not p.is_file():
        raise InputError(f"input file not found: {p}")
    cmd = [
        caps.ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        os.fspath(p),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False, **_popen_kwargs())
    if res.returncode != 0:
        raise InputError(f"ffprobe could not read {p.name}: {res.stderr.strip()[:300]}")
    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError as exc:
        raise InputError(f"ffprobe returned invalid JSON for {p.name}") from exc
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if v is None and a is None:
        raise InputError(f"no audio or video streams in {p.name}")
    duration = _fraction(fmt.get("duration"))
    if not duration and v is not None:
        duration = _fraction(v.get("duration"))
    if not duration and a is not None:
        duration = _fraction(a.get("duration"))
    if duration <= 0:
        raise InputError(f"could not determine duration of {p.name}")
    rotation = 0
    width = height = 0
    fps = 0.0
    if v is not None:
        width = int(v.get("width") or 0)
        height = int(v.get("height") or 0)
        fps = _fraction(v.get("avg_frame_rate")) or _fraction(v.get("r_frame_rate"))
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                try:
                    rotation = int(sd["rotation"]) % 360
                except (TypeError, ValueError):
                    pass
        if not rotation and "rotate" in (v.get("tags") or {}):
            try:
                rotation = int(v["tags"]["rotate"]) % 360
            except ValueError:
                pass
    return MediaInfo(
        path=os.fspath(p),
        duration_s=duration,
        width=width,
        height=height,
        fps=fps,
        has_audio=a is not None,
        has_video=v is not None,
        rotation=rotation,
        size_bytes=int(fmt.get("size") or p.stat().st_size),
        vcodec=(v or {}).get("codec_name", "") or "",
        acodec=(a or {}).get("codec_name", "") or "",
        pix_fmt=(v or {}).get("pix_fmt", "") or "",
        color_transfer=(v or {}).get("color_transfer", "") or "",
    )


def audio_pipe(
    path: str | os.PathLike,
    caps: FFmpegCaps,
    sample_rate: int = 16000,
    chunk_s: float = 30.0,
    start_s: float = 0.0,
) -> Iterator[bytes]:
    """Yield s16le mono PCM chunks from ffmpeg without loading the whole file."""
    cmd = [caps.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error"]
    if start_s > 0:
        cmd += ["-ss", f"{start_s:.3f}"]
    cmd += [
        "-i",
        os.fspath(path),
        "-vn",
        "-sn",
        "-dn",
        "-map",
        "0:a:0",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "s16le",
        "-",
    ]
    chunk_bytes = int(sample_rate * chunk_s) * 2
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_popen_kwargs())
    assert proc.stdout is not None
    try:
        while True:
            buf = proc.stdout.read(chunk_bytes)
            if not buf:
                break
            yield buf
    finally:
        proc.stdout.close()
        err = b""
        if proc.stderr is not None:
            err = proc.stderr.read()
            proc.stderr.close()
        rc = proc.wait()
        if rc != 0 and err:
            raise InputError(f"ffmpeg audio decode failed: {err.decode(errors='replace')[:300]}")
