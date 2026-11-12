"""ffmpeg/ffprobe discovery, preflight, probing, the 16 kHz audio pipe and the gray proxy pipe."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .errors import FFmpegMissing, InputError

EXTRA_PATHS = ["/opt/homebrew/opt/ffmpeg-full/bin", "/usr/local/opt/ffmpeg-full/bin"]


def _extra_paths() -> list[str]:
    """Keg-only ffmpeg-full locations; CLIP_ANYTHING_EXTRA_PATHS overrides (empty = none)."""
    env = os.environ.get("CLIP_ANYTHING_EXTRA_PATHS")
    if env is None:
        return EXTRA_PATHS
    return [p for p in env.split(os.pathsep) if p]


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
    tonemap: bool = False  # `scale` has in_transfer/out_transfer (ffmpeg >= 8 colour management)
    hwaccel: str = ""  # decoder hwaccel to use for the analysis proxy ("" = software)


HDR_TRANSFERS = ("smpte2084", "arib-std-b67")


@dataclass(frozen=True)
class AudioStream:
    index: int  # ordinal among audio streams: -map 0:a:<index>
    codec: str = ""
    channels: int = 0
    sample_rate: int = 0
    title: str = ""
    language: str = ""


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
    color_primaries: str = ""
    container: str = ""  # ffprobe format_name (first entry)
    creation_time: str = ""  # container tag, ISO text, "" when absent
    audio_streams: tuple[AudioStream, ...] = ()
    hdr_assumed: bool = False  # 10-bit bt2020 with no transfer tag: treated as PQ, warned
    duration_measured: bool = False  # container had no duration: measured with a -c copy pass

    @property
    def is_hdr(self) -> bool:
        return self.color_transfer in HDR_TRANSFERS

    @property
    def is_portrait(self) -> bool:
        w, h = self.display_size
        return h > w

    @property
    def display_size(self) -> tuple[int, int]:
        """(w, h) after ffmpeg's automatic rotation, i.e. what filters see."""
        if self.rotation in (90, 270):
            return self.height, self.width
        return self.width, self.height

    def proxy_size(self, width: int) -> tuple[int, int]:
        """Proxy (w, h) for `scale=width:h` keeping aspect, both even."""
        w, h = self.display_size
        if w <= 0 or h <= 0:
            return width, width * 9 // 16
        ph = max(2, int(round(width * h / w / 2)) * 2)
        return width, ph


def _popen_kwargs() -> dict:
    kw: dict = {}
    if os.name == "nt":  # pragma: no cover
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return kw


def bundle_dirs() -> list[Path]:
    """Where a packaged desktop build keeps its own ffmpeg/ffprobe: next to the executable
    (PyInstaller one-folder, `_MEIPASS`), or the .app's Resources/Frameworks/MacOS folders.
    `CLIP_ANYTHING_FFMPEG_DIR` adds one more folder first (also for tests)."""
    dirs: list[Path] = []
    env = os.environ.get("CLIP_ANYTHING_FFMPEG_DIR")
    if env:
        dirs.append(Path(env))
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        meipass = getattr(sys, "_MEIPASS", None)
        dirs += [exe_dir, exe_dir / "ffmpeg"]
        if meipass:  # PyInstaller one-folder: <app>/_internal (= Contents/Frameworks in .app)
            dirs += [Path(meipass) / "ffmpeg", Path(meipass)]
        if exe_dir.name == "MacOS" and exe_dir.parent.name == "Contents":  # .app bundle
            contents = exe_dir.parent
            res = contents / "Resources"
            dirs += [res, contents / "Frameworks", res / "ffmpeg"]
    return dirs


def _bundled(name: str) -> str | None:
    exe = name + (".exe" if os.name == "nt" else "")
    for d in bundle_dirs():
        cand = d / exe
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return None


def _find(name: str) -> str | None:
    bundled = _bundled(name)
    if bundled:
        return bundled
    found = shutil.which(name)
    if found:
        return found
    for extra in _extra_paths():
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


def _has_ass_filter(ffmpeg: str) -> bool:
    filters = subprocess.run(
        [ffmpeg, "-hide_banner", "-filters"],
        capture_output=True,
        text=True,
        check=False,
        **_popen_kwargs(),
    ).stdout
    return bool(re.search(r"^\s*\S+\s+ass\s", filters, re.M))


def _full_build() -> tuple[str, str] | None:
    """A keg-only `ffmpeg-full` (brew) with libass, if installed: preferred for captions."""
    for extra in _extra_paths():
        f, p = Path(extra) / "ffmpeg", Path(extra) / "ffprobe"
        if f.is_file() and p.is_file() and os.access(f, os.X_OK):
            return str(f), str(p)
    return None


def preflight() -> FFmpegCaps:
    """Locate ffmpeg/ffprobe (a bundled copy first, then PATH), check version >= 5, detect
    the ass filter. When the PATH build lacks libass but a keg-only ffmpeg-full exists, use
    that one."""
    ffmpeg = _find("ffmpeg")
    ffprobe = _find("ffprobe")
    if not ffmpeg or not ffprobe:
        raise FFmpegMissing("ffmpeg/ffprobe not found on PATH", install_help())
    captions = _has_ass_filter(ffmpeg)
    if not captions and _bundled("ffmpeg") is None:
        full = _full_build()
        if (
            full
            and full[0] != ffmpeg
            and _version_of(full[0]) >= (5, 0)
            and _has_ass_filter(full[0])
        ):
            ffmpeg, ffprobe, captions = full[0], full[1], True
    version = _version_of(ffmpeg)
    if version < (5, 0):
        raise FFmpegMissing(
            f"ffmpeg {version[0]}.{version[1]} is too old (need >= 5.0)", install_help()
        )
    flag = "-/filter_complex" if version >= (7, 0) else "-filter_complex_script"
    tonemap = False
    if version >= (8, 0):
        scale_help = subprocess.run(
            [ffmpeg, "-hide_banner", "-h", "filter=scale"],
            capture_output=True,
            text=True,
            check=False,
            **_popen_kwargs(),
        ).stdout
        tonemap = "in_transfer" in scale_help and "out_primaries" in scale_help
    hwaccel = ""
    if platform.system() == "Darwin":  # videotoolbox halves 4K HEVC proxy decode; sw fallback
        hw = subprocess.run(
            [ffmpeg, "-hide_banner", "-hwaccels"],
            capture_output=True,
            text=True,
            check=False,
            **_popen_kwargs(),
        ).stdout
        if re.search(r"^videotoolbox$", hw, re.M):
            hwaccel = "videotoolbox"
    return FFmpegCaps(ffmpeg, ffprobe, version, captions, flag, tonemap, hwaccel)


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


TIME_RE = re.compile(rb"time=(\d+):(\d\d):(\d\d(?:\.\d+)?)")


def measure_duration(path: str | os.PathLike, caps: FFmpegCaps) -> float:
    """Duration of a file whose container has none (interrupted OBS mkv, .ts chunk): a
    `-c copy` pass to null, no decode; the last `time=` on stderr is the answer."""
    cmd = [
        caps.ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "info",
        "-stats",
        "-i",
        os.fspath(path),
        "-map",
        "0",
        "-c",
        "copy",
        "-f",
        "null",
        "-",
    ]
    res = subprocess.run(cmd, capture_output=True, check=False, **_popen_kwargs())
    last = 0.0
    for m in TIME_RE.finditer(res.stderr):
        last = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    return last


def _audio_streams(streams: list[dict]) -> tuple[AudioStream, ...]:
    out = []
    for s in streams:
        if s.get("codec_type") != "audio":
            continue
        tags = s.get("tags") or {}
        out.append(
            AudioStream(
                index=len(out),
                codec=s.get("codec_name", "") or "",
                channels=int(s.get("channels") or 0),
                sample_rate=int(s.get("sample_rate") or 0),
                title=str(tags.get("title") or tags.get("handler_name") or ""),
                language=str(tags.get("language") or ""),
            )
        )
    return tuple(out)


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
    measured = False
    if duration <= 0:
        duration = measure_duration(p, caps)
        measured = True
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
    transfer = (v or {}).get("color_transfer", "") or ""
    pix_fmt = (v or {}).get("pix_fmt", "") or ""
    primaries = (v or {}).get("color_primaries", "") or ""
    hdr_assumed = False
    if (
        v is not None
        and transfer in ("", "unknown")
        and primaries == "bt2020"
        and re.search(r"p?10|p?12", pix_fmt)
    ):
        transfer, hdr_assumed = "smpte2084", True  # HDR metadata lost on remux (webm/mkv)
    tags = fmt.get("tags") or {}
    creation = str(tags.get("creation_time") or (v or {}).get("tags", {}).get("creation_time", ""))
    return MediaInfo(
        path=os.fspath(p.resolve()),
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
        pix_fmt=pix_fmt,
        color_transfer=transfer,
        color_primaries=primaries,
        container=str(fmt.get("format_name", "") or "").split(",")[0],
        creation_time=creation,
        audio_streams=_audio_streams(streams),
        hdr_assumed=hdr_assumed,
        duration_measured=measured,
    )


def audio_map_args(track: int | str, n_tracks: int) -> list[str]:
    """ffmpeg args selecting the analysis audio: a stream ordinal, or "mix" (amix of all
    tracks), or "mix:0,2" (amix of the listed ordinals)."""
    if isinstance(track, int):
        if track < 0 or track >= max(n_tracks, 1):
            raise InputError(f"audio track {track} does not exist ({n_tracks} audio stream(s))")
        return ["-map", f"0:a:{track}"]
    idx = list(range(n_tracks))
    if track.startswith("mix:"):
        idx = [int(x) for x in track[4:].split(",") if x.strip()]
    if len(idx) <= 1:
        return ["-map", f"0:a:{idx[0] if idx else 0}"]
    graph = "".join(f"[0:a:{i}]" for i in idx) + f"amix=inputs={len(idx)}:duration=longest[a]"
    return ["-filter_complex", graph, "-map", "[a]"]


def audio_pipe(
    path: str | os.PathLike,
    caps: FFmpegCaps,
    sample_rate: int = 16000,
    chunk_s: float = 30.0,
    start_s: float = 0.0,
    duration_s: float | None = None,
    track: int | str = 0,
    n_tracks: int = 1,
) -> Iterator[bytes]:
    """Yield s16le mono PCM chunks from ffmpeg without loading the whole file. `-ss` (and
    `-t`) go before `-i`; `track` selects the stream or the amix of several."""
    cmd = [caps.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error"]
    if start_s > 0:
        cmd += ["-ss", f"{start_s:.3f}"]
    if duration_s is not None:
        cmd += ["-t", f"{duration_s:.3f}"]
    cmd += ["-i", os.fspath(path), "-vn", "-sn", "-dn"]
    cmd += audio_map_args(track, n_tracks)
    cmd += [
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


def video_pipe(
    info: MediaInfo,
    caps: FFmpegCaps,
    fps: float = 5.0,
    width: int = 320,
    chunk_frames: int = 150,
    hwaccel: str | None = None,
    start_s: float = 0.0,
    duration_s: float | None = None,
) -> Iterator[bytes]:
    """Yield raw gray8 frames (chunk_frames per buffer) of a constant-rate `fps` proxy.
    Each frame is w*h bytes with (w, h) = info.proxy_size(width). Never writes a file."""
    pw, ph = info.proxy_size(width)
    frame_bytes = pw * ph
    chunk_bytes = frame_bytes * max(1, chunk_frames)
    hw = caps.hwaccel if hwaccel is None else hwaccel
    attempts = [hw, ""] if hw else [""]
    last_err = b""
    for accel in attempts:
        cmd = [caps.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error"]
        if accel:
            cmd += ["-hwaccel", accel]
        if start_s > 0:
            cmd += ["-ss", f"{start_s:.3f}"]
        if duration_s is not None:
            cmd += ["-t", f"{duration_s:.3f}"]
        cmd += [
            "-i",
            info.path,
            "-an",
            "-sn",
            "-dn",
            "-map",
            "0:v:0",
            "-vf",
            f"fps={fps:g},scale={pw}:{ph},format=gray",
            "-f",
            "rawvideo",
            "-",
        ]
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_popen_kwargs()
        )
        assert proc.stdout is not None
        produced = 0
        try:
            carry = b""
            while True:
                buf = proc.stdout.read(chunk_bytes)
                if not buf:
                    break
                buf = carry + buf
                whole = (len(buf) // frame_bytes) * frame_bytes
                carry = buf[whole:]
                if whole:
                    produced += whole // frame_bytes
                    yield buf[:whole]
        finally:
            proc.stdout.close()
            err = b""
            if proc.stderr is not None:
                err = proc.stderr.read()
                proc.stderr.close()
            rc = proc.wait()
        if rc == 0 or produced > 0:
            if rc != 0 and err:
                msg = err.decode(errors="replace")[:300]
                raise InputError(f"ffmpeg video decode failed: {msg}")
            return
        last_err = err  # hwaccel failed before the first frame: retry in software
    raise InputError(f"ffmpeg video decode failed: {last_err.decode(errors='replace')[:300]}")
