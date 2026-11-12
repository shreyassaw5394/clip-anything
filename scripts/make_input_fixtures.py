#!/usr/bin/env python3
"""Input-shape fixtures (phase 02-03): every way people record, as small synthetic files.

Written under <out>/inputs/ (default tests/fixtures/inputs). Each variant is tiny (20-100 s,
640x360 or smaller) so the end-to-end tests stay fast; `long` (3 h, 320x180 5 fps) is only
built on request. Truth for every variant is in <out>/inputs/inputs.json.

Variants:
  short_clips   folder of 6 x 30 s console-style clips, one burst each of a known loudness,
                creation_time tags in reverse name order (session order must follow the tags)
  session       two files (100 s + 80 s) cut from one timeline: 6 bursts, 3 per file
  two_tracks    mkv with a:0 "Game" (wideband bursts at 30, 70 s) and a:1 "Mic"
                (band-limited burst at 50 s, silence elsewhere)
  no_audio      60 s, no audio stream, motion bursts at 20 and 40 s
  vertical      540x960 phone-style, 40 s, burst at 20 s
  four_three    640x480, ultrawide 1680x720: 40 s, burst at 20 s, moving square
  hdr_hlg       HEVC 10-bit HLG bt2020 (console / Elgato HDR), 40 s
  hdr_notag     VP9 10-bit bt2020 webm with no transfer tag (metadata lost on remux)
  prores        ProRes .mov (phone / editor export), 20 s
  vp9_opus      PS5-style webm (VP9 + Opus), 40 s
  av1           AV1 in mkv (libsvtav1), 40 s
  ts            MPEG-TS chunk (Twitch download), 40 s
  truncated     mkv cut at 60 % of its bytes (interrupted OBS), 40 s source
  long          3 h, bursts every 10 min, low bitrate (memory / resume checks; on request)
Usage: python scripts/make_input_fixtures.py [--out tests/fixtures] [--variant NAME|all|long]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

GEN_VERSION = 6
SHORT_LEVELS = [0.9, 0.12, 0.5, 0.06, 0.25, 0.03]  # burst amplitude per clip_{k} (~6 dB steps)
SHORT_DUR = 30.0
SESSION_BURSTS = [12.0, 44.0, 76.0, 108.0, 140.0, 172.0]
SESSION_SPLIT = 100.0
TWO_TRACK_GAME = [20.0, 90.0]  # > 30 s from the mic shout at 50 (min gap rule)
TWO_TRACK_MIC = 50.0
NO_AUDIO_MOTION = [20.0, 40.0]
GEOM = {"vertical": "540x960", "four_three": "640x480", "ultrawide": "1680x720"}
LONG_S = 3 * 3600.0
LONG_BURST_EVERY = 600.0

VARIANTS = [
    "short_clips",
    "session",
    "two_tracks",
    "no_audio",
    "vertical",
    "four_three",
    "ultrawide",
    "hdr_hlg",
    "hdr_notag",
    "prores",
    "vp9_opus",
    "av1",
    "ts",
    "truncated",
]


def _ff(ffmpeg: str, *args: str) -> None:
    subprocess.run(
        [ffmpeg, "-y", "-nostdin", "-hide_banner", "-loglevel", "error", *args], check=True
    )


def _bursts(times: list[float], dur: float = 1.0, amp: float = 1.5) -> str:
    on = "+".join(f"between(t,{t},{t + dur})" for t in times) or "0"
    return f"0.03*sin(2*PI*220*t)+{amp}*(random(0)-0.5)*({on})"


def _motion(times: list[float], dur: float = 2.0) -> str:
    return "+".join(f"between(t,{t},{t + dur})" for t in times) or "0"


def _src(size: str, d: float, fps: int = 30) -> list[str]:
    return ["-f", "lavfi", "-i", f"testsrc2=size={size}:rate={fps}:duration={d}"]


def _square(d: float, fps: int = 30, px: int = 120) -> list[str]:
    return ["-f", "lavfi", "-i", f"color=c=white:s={px}x{px}:r={fps}:d={d}"]


def _audio(expr: str, d: float) -> list[str]:
    return ["-f", "lavfi", "-i", f"aevalsrc=exprs='{expr}':s=48000:d={d}"]


X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p"]
AAC = ["-c:a", "aac", "-b:a", "96k"]


def _overlay(motion_enable: str, tail: str = "") -> str:
    return (
        "[0:v][1:v]overlay=x='(W-w)*mod(t*1.7,1)':y='(H-h)*abs(sin(t*5))'"
        f":enable='{motion_enable}'{tail}[v]"
    )


def _simple(out: Path, ffmpeg: str, size: str, d: float, bursts: list[float], motion: list[float],
            vcodec: list[str], acodec: list[str], extra: list[str] | None = None,
            tail: str = "") -> None:  # fmt: skip
    _ff(
        ffmpeg,
        *_src(size, d),
        *_square(d),
        *_audio(_bursts(bursts), d),
        "-filter_complex",
        _overlay(_motion(motion), tail),
        "-map",
        "[v]",
        "-map",
        "2:a",
        *vcodec,
        *acodec,
        *(extra or []),
        "-shortest",
        str(out),
    )


def build(root: Path, variant: str, ffmpeg: str) -> Path:
    d = root / "inputs"
    d.mkdir(parents=True, exist_ok=True)
    if variant == "short_clips":
        folder = d / "short_clips"
        folder.mkdir(exist_ok=True)
        for k, amp in enumerate(SHORT_LEVELS):
            # creation_time runs backwards against the names: clip_5 is the oldest
            stamp = f"2026-01-01T00:{(len(SHORT_LEVELS) - k):02d}:00.000000Z"
            _ff(
                ffmpeg,
                *_src("640x360", SHORT_DUR),
                *_square(SHORT_DUR),
                *_audio(_bursts([12.0 + k], 1.0, amp), SHORT_DUR),
                "-filter_complex",
                _overlay(_motion([12.0 + k])),
                "-map", "[v]", "-map", "2:a", *X264, *AAC,
                "-metadata", f"creation_time={stamp}",
                "-shortest", str(folder / f"clip_{k}.mp4"),
            )  # fmt: skip
        return folder
    if variant == "session":
        folder = d / "session"
        folder.mkdir(exist_ok=True)
        whole = d / "session_src.mp4"
        _simple(whole, ffmpeg, "640x360", 180.0, SESSION_BURSTS, [28.0, 95.0], X264, AAC)
        a, b = folder / "part_a.mp4", folder / "part_b.mp4"
        _ff(ffmpeg, "-t", str(SESSION_SPLIT), "-i", str(whole), *X264, *AAC,
            "-metadata", "creation_time=2026-02-01T10:00:00.000000Z", str(a))  # fmt: skip
        _ff(ffmpeg, "-ss", str(SESSION_SPLIT), "-i", str(whole), *X264, *AAC,
            "-metadata", "creation_time=2026-02-01T10:01:40.000000Z", str(b))  # fmt: skip
        whole.unlink()
        return folder
    if variant == "two_tracks":
        out = d / "two_tracks.mkv"
        dd = 130.0
        mic = f"0.8*(random(0)-0.5)*between(t,{TWO_TRACK_MIC},{TWO_TRACK_MIC + 1.5})"
        _ff(
            ffmpeg,
            *_src("640x360", dd),
            *_square(dd),
            *_audio(_bursts(TWO_TRACK_GAME), dd),
            *_audio(mic, dd),
            "-filter_complex",
            _overlay(_motion([*TWO_TRACK_GAME, TWO_TRACK_MIC])) + ";[3:a]lowpass=f=3000[mic]",
            "-map", "[v]", "-map", "2:a", "-map", "[mic]", *X264, *AAC,
            "-metadata:s:a:0", "title=Game", "-metadata:s:a:1", "title=Mic",
            "-shortest", str(out),
        )  # fmt: skip
        return out
    if variant == "no_audio":
        out = d / "no_audio.mp4"
        _ff(ffmpeg, *_src("640x360", 60.0), *_square(60.0), "-filter_complex",
            _overlay(_motion(NO_AUDIO_MOTION)), "-map", "[v]", *X264, "-an", str(out))  # fmt: skip
        return out
    if variant in GEOM:
        out = d / f"{variant}.mp4"
        _simple(out, ffmpeg, GEOM[variant], 40.0, [20.0], [20.0], X264, AAC)
        return out
    if variant == "hdr_hlg":
        out = d / "hdr_hlg.mp4"
        x265 = "log-level=none:colorprim=bt2020:transfer=arib-std-b67:colormatrix=bt2020nc"
        hevc = ["-c:v", "libx265", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p10le",
                "-tag:v", "hvc1", "-x265-params", x265]  # fmt: skip
        tail = ",setparams=color_primaries=bt2020:color_trc=arib-std-b67:colorspace=bt2020nc"
        _simple(out, ffmpeg, "640x360", 40.0, [20.0], [20.0], hevc, AAC, tail=tail)
        return out
    if variant == "hdr_notag":
        out = d / "hdr_notag.webm"
        vp9 = ["-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8", "-b:v", "400k",
               "-pix_fmt", "yuv420p10le"]  # fmt: skip
        tail = ",setparams=color_primaries=bt2020:colorspace=bt2020nc"  # transfer deliberately lost
        _simple(out, ffmpeg, "640x360", 40.0, [20.0], [20.0], vp9,
                ["-c:a", "libopus", "-b:a", "64k"], tail=tail)  # fmt: skip
        return out
    if variant == "prores":
        out = d / "prores.mov"
        _simple(out, ffmpeg, "640x360", 20.0, [10.0], [10.0],
                ["-c:v", "prores_ks", "-profile:v", "0", "-pix_fmt", "yuv422p10le"],
                ["-c:a", "pcm_s16le"])  # fmt: skip
        return out
    if variant == "vp9_opus":
        out = d / "vp9_opus.webm"
        _simple(out, ffmpeg, "640x360", 40.0, [20.0], [20.0],
                ["-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8", "-b:v", "400k"],
                ["-c:a", "libopus", "-b:a", "64k"])  # fmt: skip
        return out
    if variant == "av1":
        out = d / "av1.mkv"
        _simple(out, ffmpeg, "640x360", 40.0, [20.0], [20.0],
                ["-c:v", "libsvtav1", "-preset", "12", "-crf", "45"], AAC)  # fmt: skip
        return out
    if variant == "ts":
        out = d / "chunk.ts"
        _simple(out, ffmpeg, "640x360", 40.0, [20.0], [20.0], X264, AAC, ["-f", "mpegts"])
        return out
    if variant == "truncated":
        full = d / "truncated_src.mkv"
        out = d / "truncated.mkv"
        # -live 1: no duration/cues in the header, like a recorder that never finished
        _simple(full, ffmpeg, "640x360", 40.0, [20.0], [20.0], X264, AAC, ["-live", "1"])
        data = full.read_bytes()
        out.write_bytes(data[: int(len(data) * 0.6)])
        full.unlink()
        return out
    if variant == "long":
        out = d / "long_3h.mp4"
        bursts = [float(t) for t in range(300, int(LONG_S), int(LONG_BURST_EVERY))]
        audio = f"aevalsrc=exprs='{_bursts(bursts)}':s=16000:d={LONG_S}"
        x264 = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "35", "-pix_fmt", "yuv420p"]
        _ff(
            ffmpeg,
            "-f", "lavfi", "-i", f"testsrc2=size=320x180:rate=5:duration={LONG_S}",
            *_square(LONG_S, 5, 60), "-f", "lavfi", "-i", audio,
            "-filter_complex", _overlay(_motion(bursts)),
            "-map", "[v]", "-map", "2:a", *x264, "-g", "50",
            "-c:a", "aac", "-b:a", "24k", "-ac", "1", "-shortest", "-movflags", "+faststart",
            str(out),
        )  # fmt: skip
        return out
    raise ValueError(variant)


def truth() -> dict:
    return {
        "gen_version": GEN_VERSION,
        "short_levels": SHORT_LEVELS,
        "short_dur": SHORT_DUR,
        "session_bursts": SESSION_BURSTS,
        "session_split": SESSION_SPLIT,
        "two_track_game": TWO_TRACK_GAME,
        "two_track_mic": TWO_TRACK_MIC,
        "no_audio_motion": NO_AUDIO_MOTION,
        "geom": GEOM,
        "burst_40s": 20.0,
        "long_s": LONG_S,
        "long_burst_every": LONG_BURST_EVERY,
    }


def ensure(root: Path, variant: str) -> Path:
    """Build the variant only when missing or generated by an older script version."""
    d = root / "inputs"
    marker = d / "inputs.json"
    names = {
        "short_clips": "short_clips", "session": "session", "two_tracks": "two_tracks.mkv",
        "no_audio": "no_audio.mp4", "vertical": "vertical.mp4", "four_three": "four_three.mp4",
        "ultrawide": "ultrawide.mp4", "hdr_hlg": "hdr_hlg.mp4", "hdr_notag": "hdr_notag.webm",
        "prores": "prores.mov", "vp9_opus": "vp9_opus.webm", "av1": "av1.mkv", "ts": "chunk.ts",
        "truncated": "truncated.mkv", "long": "long_3h.mp4",
    }  # fmt: skip
    out = d / names[variant]
    fresh = False
    if marker.is_file():
        try:
            fresh = json.loads(marker.read_text()).get("gen_version") == GEN_VERSION
        except json.JSONDecodeError:
            fresh = False
    if out.exists() and fresh:
        return out
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    if not fresh:
        for v in VARIANTS:  # version bump: rebuild everything small
            build(root, v, ffmpeg)
        marker.write_text(json.dumps(truth(), indent=2))
        if out.exists():
            return out
    return build(root, variant, ffmpeg)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="tests/fixtures")
    ap.add_argument("--variant", default="all", choices=[*VARIANTS, "long", "all"])
    args = ap.parse_args(argv)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("ffmpeg not found on PATH", file=sys.stderr)
        return 3
    root = Path(args.out)
    variants = VARIANTS if args.variant == "all" else [args.variant]
    for v in variants:
        print(build(root, v, ffmpeg))
    if args.variant == "all":
        (root / "inputs" / "inputs.json").write_text(json.dumps(truth(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
