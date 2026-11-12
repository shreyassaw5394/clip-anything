#!/usr/bin/env python3
"""Generate the synthetic test video: 3 min testsrc2 720p30 with 6 loud audio bursts and
4 visual motion bursts at known times. Writes <out>/synth.mp4 + synth.json (ground truth).

Variants: base (default), music (constant loud bed under the bursts), vfr (random frame
drops with -fps_mode vfr so frame durations vary), quiet (no audio bursts: only the motion
bursts can be found), square (40 s, one slow-moving square + one audio burst, for the
follow-crop test; truth in synth_square.json).  Usage:
  python scripts/make_test_video.py [--out tests/fixtures] [--variant base|music|vfr|quiet|all]
  (also: --variant square)
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

GEN_VERSION = 5
DURATION = 180.0
# (start_s, duration_s) gunfire-like white-noise bursts
AUDIO_BURSTS = [(12.0, 0.6), (44.0, 1.2), (76.0, 0.4), (108.0, 1.5), (140.0, 0.8), (172.0, 1.0)]
# (start_s, duration_s) fast-moving bright overlay
MOTION_BURSTS = [(28.0, 2.0), (62.0, 2.0), (95.0, 2.0), (125.0, 2.0)]


NAMES = {
    "base": "synth.mp4",
    "music": "synth_music.mp4",
    "vfr": "synth_vfr.mp4",
    "quiet": "synth_quiet.mp4",
    "square": "synth_square.mp4",
}
# square variant: duration, square x-centre fraction at start/end (linear), one audio burst
SQUARE_DURATION = 40.0
SQUARE_X0, SQUARE_X1 = 0.12, 0.88
SQUARE_BURST = (22.0, 0.8)


def _audio_expr(music_bed: bool, bursts_on: bool = True) -> str:
    bursts = "+".join(f"between(t,{s},{s + d})" for s, d in AUDIO_BURSTS)
    if not bursts_on:
        bursts = "0"
    base = "0.04*sin(2*PI*220*t)+0.01*(random(0)-0.5)"
    if music_bed:
        base = "0.30*sin(2*PI*330*t)+0.12*sin(2*PI*660*t)+0.08*(random(0)-0.5)"
    return f"{base}+1.5*(random(0)-0.5)*({bursts})"


def _motion_enable() -> str:
    return "+".join(f"between(t,{s},{s + d})" for s, d in MOTION_BURSTS)


def build(out_dir: Path, variant: str, ffmpeg: str = "ffmpeg") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    name = NAMES[variant]
    out = out_dir / name
    if variant == "square":
        return _build_square(out_dir, out, ffmpeg)
    if variant == "vfr":
        src = out_dir / "synth.mp4"
        if not src.is_file():
            build(out_dir, "base", ffmpeg)
        cmd = [
            ffmpeg,
            "-y",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-vf",
            "select='gt(random(0),0.35)'",
            "-fps_mode",
            "vfr",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(out),
        ]
    else:
        cmd = [
            ffmpeg,
            "-y",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size=1280x720:rate=30:duration={DURATION}",
            "-f",
            "lavfi",
            "-i",
            f"color=c=white:s=260x260:r=30:d={DURATION}",
            "-f",
            "lavfi",
            "-i",
            f"aevalsrc=exprs='{_audio_expr(variant == 'music', variant != 'quiet')}'"
            f":s=48000:d={DURATION}",
            "-filter_complex",
            "[0:v][1:v]overlay=x='(W-w)*mod(t*1.7,1)':y='(H-h)*abs(sin(t*5))'"
            f":enable='{_motion_enable()}'[v]",
            "-map",
            "[v]",
            "-map",
            "2:a",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(out),
        ]
    subprocess.run(cmd, check=True)
    truth = {
        "gen_version": GEN_VERSION,
        "duration_s": DURATION,
        "audio_bursts": [{"t": s, "dur": d} for s, d in AUDIO_BURSTS],
        "motion_bursts": [{"t": s, "dur": d} for s, d in MOTION_BURSTS],
    }
    (out_dir / "synth.json").write_text(json.dumps(truth, indent=2))
    return out


def _build_square(out_dir: Path, out: Path, ffmpeg: str) -> Path:
    d = SQUARE_DURATION
    s, bd = SQUARE_BURST
    sq = 160
    # square centre fraction of width = X0 + (X1-X0)*t/d  (about 2 % of width per second)
    x_expr = f"W*({SQUARE_X0}+({SQUARE_X1}-{SQUARE_X0})*t/{d})-{sq / 2}"
    audio = f"0.03*sin(2*PI*220*t)+1.5*(random(0)-0.5)*between(t,{s},{s + bd})"
    cmd = [
        ffmpeg,
        "-y",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x202020:s=1280x720:r=30:d={d}",
        "-f",
        "lavfi",
        "-i",
        f"color=c=white:s={sq}x{sq}:r=30:d={d}",
        "-f",
        "lavfi",
        "-i",
        f"aevalsrc=exprs='{audio}':s=48000:d={d}",
        "-filter_complex",
        f"[0:v][1:v]overlay=x='{x_expr}':y='(H-h)/2+40*sin(t)'[v]",
        "-map",
        "[v]",
        "-map",
        "2:a",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(out),
    ]
    subprocess.run(cmd, check=True)
    truth = {
        "gen_version": GEN_VERSION,
        "duration_s": d,
        "square_x0": SQUARE_X0,
        "square_x1": SQUARE_X1,
        "audio_bursts": [{"t": s, "dur": bd}],
    }
    (out_dir / "synth_square.json").write_text(json.dumps(truth, indent=2))
    return out


def ensure(out_dir: Path, variant: str = "base") -> Path:
    """Build only if missing or generated by an older version of this script."""
    out = out_dir / NAMES[variant]
    truth = out_dir / ("synth_square.json" if variant == "square" else "synth.json")
    if out.is_file() and truth.is_file():
        try:
            if json.loads(truth.read_text()).get("gen_version") == GEN_VERSION:
                return out
        except json.JSONDecodeError:
            pass
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    return build(out_dir, variant, ffmpeg)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="tests/fixtures")
    ap.add_argument("--variant", default="base", choices=[*NAMES, "all"])
    args = ap.parse_args(argv)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("ffmpeg not found on PATH", file=sys.stderr)
        return 3
    variants = list(NAMES) if args.variant == "all" else [args.variant]
    for v in variants:
        out = build(Path(args.out), v, ffmpeg)
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
