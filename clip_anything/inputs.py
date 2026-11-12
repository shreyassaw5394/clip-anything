"""Inputs: discover video files (file, folder or several paths), order them by creation time,
build one session timeline with per-file offsets, choose the analysis audio track.

Pure helpers except `audio_roles` (decodes the first seconds of each track) and `probe_all`.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from .errors import InputError
from .probe import FFmpegCaps, MediaInfo, audio_pipe, probe

VIDEO_EXTS = {
    ".mp4",
    ".mkv",
    ".mov",
    ".m4v",
    ".ts",
    ".m2ts",
    ".mts",
    ".webm",
    ".avi",
    ".flv",
    ".wmv",
}
STEAM_MARKERS = (".m4s", "timelines", "fg_")  # Steam background recordings: not playable files
SHORT_FILE_S = 90.0  # every file at or below this: each file is one candidate (console clips)


def _natural(name: str) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def _looks_like_steam(folder: Path) -> bool:
    try:
        for child in folder.iterdir():
            n = child.name.lower()
            if n.endswith(".m4s") or n == "timelines" or n.startswith("fg_"):
                return True
            if child.is_dir() and child.name.lower() in ("clips", "video"):
                for sub in child.rglob("*"):
                    if sub.suffix.lower() == ".m4s":
                        return True
    except OSError:
        return False
    return False


def discover(paths: list[str | os.PathLike]) -> list[Path]:
    """Expand files/folders to the list of video files (folders: non-recursive, natural order).
    Friendly InputError for a missing path, an unsupported file, a folder with no videos."""
    if not paths:
        raise InputError("no input given: clip-anything <video or folder>")
    found: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            vids = sorted(
                (c for c in p.iterdir() if c.is_file() and c.suffix.lower() in VIDEO_EXTS
                 and not c.name.startswith(".")),
                key=lambda c: _natural(c.name),
            )  # fmt: skip
            if not vids:
                if _looks_like_steam(p):
                    raise InputError(
                        f"{p} looks like a Steam background recording (raw timeline, not a "
                        "video file): in Steam open Recordings & Screenshots, create a clip "
                        "and Export it as MP4, then run clip-anything on that file"
                    )
                exts = " ".join(sorted(e.lstrip(".") for e in VIDEO_EXTS))
                raise InputError(f"no video files in {p} (looked for: {exts})")
            found.extend(vids)
        elif p.is_file():
            if p.suffix.lower() not in VIDEO_EXTS:
                exts = " ".join(sorted(e.lstrip(".") for e in VIDEO_EXTS))
                raise InputError(f"unsupported file type {p.suffix or '(none)'}: {p.name} ({exts})")
            found.append(p)
        elif not p.exists():
            raise InputError(f"input not found: {p}")
        else:
            raise InputError(f"not a file or folder: {p}")
    seen: set[str] = set()
    out: list[Path] = []
    for f in found:
        key = os.fspath(f.resolve())
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def _parse_time(text: str) -> float | None:
    if not text:
        return None
    t = text.strip().replace("Z", "+00:00")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(t, fmt).timestamp()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(t).timestamp()
    except ValueError:
        return None


def sort_key(info: MediaInfo) -> tuple:
    """creation_time tag -> file mtime -> natural name."""
    ts = _parse_time(info.creation_time)
    if ts is None:
        try:
            ts = Path(info.path).stat().st_mtime
        except OSError:
            ts = 0.0
    return (ts, _natural(Path(info.path).name))


def order_sources(infos: list[MediaInfo]) -> list[MediaInfo]:
    return sorted(infos, key=sort_key)


def probe_all(paths: list[Path], caps: FFmpegCaps) -> list[MediaInfo]:
    infos = [probe(p, caps) for p in paths]
    bad = [Path(i.path).name for i in infos if not i.has_video]
    if bad:
        raise InputError(f"no video stream in: {', '.join(bad)}")
    return order_sources(infos)


@dataclass
class Source:
    info: MediaInfo
    index: int
    offset_s: float  # start of this file on the session timeline (hop-aligned)
    n: int  # hops this file occupies

    @property
    def end_s(self) -> float:
        return self.offset_s + self.info.duration_s


@dataclass
class Session:
    sources: list[Source]
    hop_s: float
    short_mode: bool = False
    total_s: float = 0.0
    n: int = 0
    per_file: dict[int, dict[str, np.ndarray]] = field(default_factory=dict)

    def locate(self, t: float) -> Source:
        for s in self.sources:
            if t < s.offset_s + s.n * self.hop_s:
                return s
        return self.sources[-1]

    def to_dicts(self) -> list[dict]:
        return [
            {
                "index": s.index,
                "path": s.info.path,
                "duration_s": s.info.duration_s,
                "offset_s": s.offset_s,
                "creation_time": s.info.creation_time,
                "container": s.info.container,
                "vcodec": s.info.vcodec,
                "width": s.info.width,
                "height": s.info.height,
                "audio_streams": len(s.info.audio_streams),
            }
            for s in self.sources
        ]


def build_session(infos: list[MediaInfo], hop_s: float) -> Session:
    """One timeline: each file starts on a hop boundary right after the previous one."""
    sources: list[Source] = []
    offset = 0.0
    for i, info in enumerate(infos):
        n = int(np.ceil(info.duration_s / hop_s))
        sources.append(Source(info, i, offset, n))
        offset += n * hop_s
    short = bool(infos) and all(i.duration_s <= SHORT_FILE_S for i in infos)
    total = sum(s.n for s in sources)
    return Session(sources, hop_s, short, offset, total)


def concat_arrays(
    session: Session, names: list[str], per_file: dict[int, dict[str, np.ndarray]]
) -> dict[str, np.ndarray]:
    """Per-file signal arrays -> session arrays (NaN where a file lacks the signal)."""
    out: dict[str, np.ndarray] = {}
    for name in names:
        parts = []
        for s in session.sources:
            arr = per_file.get(s.index, {}).get(name)
            if arr is None:
                parts.append(np.full(s.n, np.nan, np.float32))
                continue
            arr = np.asarray(arr, dtype=np.float32)
            if arr.size < s.n:
                arr = np.pad(arr, (0, s.n - arr.size), constant_values=np.nan)
            parts.append(arr[: s.n])
        out[name] = np.concatenate(parts) if parts else np.zeros(0, np.float32)
    return out


def clamp_to_source(
    session: Session, start: float, end: float, peak_t: float, min_s: float, max_s: float
) -> tuple[Source, float, float]:
    """A clip never crosses a file boundary: keep the file holding the peak, clamp the window
    to it, then grow the other side back towards min_s. Returns (source, local start, end)."""
    src = session.locate(peak_t)
    lo, hi = src.offset_s, src.offset_s + src.info.duration_s
    a, b = max(start, lo), min(end, hi)
    want = min(max_s, max(min_s, end - start))
    if b - a < want:
        a = max(lo, b - want)
        b = min(hi, a + want)
    return src, round(a - lo, 3), round(b - lo, 3)


@dataclass(frozen=True)
class TrackRole:
    index: int
    role: str  # game | mic | silent | mono
    rms_db: float
    active: float  # fraction of 0.5 s windows above -50 dBFS
    dynamic_db: float  # p95 - p50 of window rms
    high_ratio: float  # energy above 4 kHz / total (speech is low; game audio wideband)
    title: str = ""


def _track_stats(pcm: bytes, sr: int) -> tuple[float, float, float, float, float]:
    """(median rms dB, active fraction, p95-p50 dB, high-band ratio, max rms dB)."""
    x = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    if x.size < sr:
        return -120.0, 0.0, 0.0, 0.0, -120.0
    hop = sr // 2
    n = x.size // hop
    seg = x[: n * hop].reshape(n, hop)
    rms = 20 * np.log10(np.sqrt(np.mean(seg * seg, axis=1)) + 1e-6)
    active = float(np.mean(rms > -50.0))
    dyn = float(np.percentile(rms, 95) - np.percentile(rms, 50))
    spec = np.abs(np.fft.rfft(seg * np.hanning(hop), axis=1)) ** 2
    freqs = np.fft.rfftfreq(hop, 1.0 / sr)
    loud = rms > -50.0
    if loud.any():
        tot = spec[loud].sum()
        high = spec[loud][:, freqs >= 4000.0].sum()
        high_ratio = float(high / tot) if tot > 0 else 0.0
    else:
        high_ratio = 0.0
    return float(np.median(rms)), active, dyn, high_ratio, float(rms.max())


def audio_roles(info: MediaInfo, caps: FFmpegCaps, sample_s: float = 120.0, sr: int = 16000):
    """Cheap per-track look at the first `sample_s`: near-silent tracks are dropped from the
    mix, the most speech-like active track is the mic (bonus only), the rest is game audio."""
    roles: list[TrackRole] = []
    for st in info.audio_streams:
        chunks = audio_pipe(
            info.path, caps, sr, 30.0, 0.0, sample_s, st.index, len(info.audio_streams)
        )
        decodable = True
        try:
            pcm = b"".join(chunks)
        except InputError:  # e.g. Apple APAC spatial track: ffmpeg has no decoder
            pcm, decodable = b"", False
        med, active, dyn, high, peak = _track_stats(pcm, sr)
        # near-silent = never above -60 dBFS in the sample (a push-to-talk mic with one
        # shout is kept)
        role = "undecodable" if not decodable else ("silent" if peak < -60.0 else "game")
        roles.append(TrackRole(st.index, role, med, active, dyn, high, st.title))
    out: list[TrackRole] = []
    for r in roles:
        role = r.role
        out.append(
            TrackRole(r.index, role, r.rms_db, r.active, r.dynamic_db, r.high_ratio, r.title)
        )
    active = [r for r in out if r.role not in ("silent", "undecodable")]
    if len(active) >= 2:
        name_hit = [r for r in active if re.search(r"mic|voice|comm|chat", r.title, re.I)]
        if name_hit:
            mic = name_hit[0]
        else:
            mic = min(active, key=lambda r: (r.high_ratio, r.active))
            if mic.high_ratio > 0.12 and mic.active > 0.6:
                mic = None  # all tracks wideband and busy: no obvious mic
        if mic is not None:
            out = [
                TrackRole(r.index, "mic" if r.index == mic.index else r.role, r.rms_db,
                          r.active, r.dynamic_db, r.high_ratio, r.title)
                for r in out
            ]  # fmt: skip
    return out


def choose_track(choice: str, roles: list[TrackRole]) -> tuple[int | str, str]:
    """`--audio-track` value -> (audio_pipe track, human description)."""
    n = len(roles)
    if n == 0:
        return 0, "none"
    if choice in ("", "auto", "all", "mix"):
        live = [r.index for r in roles if r.role not in ("silent", "undecodable")]
        if choice == "all":
            live = [r.index for r in roles if r.role != "undecodable"]
        live = live or [roles[0].index]
        if len(live) == 1:
            return live[0], f"track {live[0]} ({roles[live[0]].role})"
        return "mix:" + ",".join(map(str, live)), "mix of tracks " + ",".join(map(str, live))
    if choice in ("game", "mic"):
        hits = [r.index for r in roles if r.role == choice]
        if not hits and choice == "game":
            hits = [r.index for r in roles if r.role not in ("silent", "undecodable")]
        if not hits:
            raise InputError(f"no audio track looks like {choice}; use --audio-track N")
        if len(hits) == 1:
            return hits[0], f"track {hits[0]} ({choice})"
        return "mix:" + ",".join(map(str, hits)), f"{choice} tracks " + ",".join(map(str, hits))
    try:
        idx = int(choice)
    except ValueError as exc:
        raise InputError(
            f"--audio-track must be auto, all, game, mic or a number, not {choice!r}"
        ) from exc
    if idx < 0 or idx >= n:
        raise InputError(f"audio track {idx} does not exist ({n} audio stream(s))")
    return idx, f"track {idx}"
