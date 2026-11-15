#!/usr/bin/env python3
"""Generate the synthetic test video: 3 min testsrc2 720p30 with 6 loud audio bursts and
4 visual motion bursts at known times. Writes <out>/synth.mp4 + synth.json (ground truth).

Variants: base (default), music (constant loud bed under the bursts), vfr (random frame
drops with -fps_mode vfr so frame durations vary), quiet (no audio bursts: only the motion
bursts can be found), square (40 s, one slow-moving square + one audio burst, for the
follow-crop test; truth in synth_square.json), lobby (two static "cards" with a changing text
strip: one silent, one under loud music, plus two real audio+motion events; the cards must not
be picked), agree (loud-only, motion-only and loud+motion events: the last must rank first),
continuous (a steady engine drone under a constant pan, like a racing recording, with 5 jolts:
the pan nearly stops for 2 s and a short impact burst sounds; truth in synth_continuous.json).
Usage:
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

GEN_VERSION = 6
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
    "lobby": "synth_lobby.mp4",
    "agree": "synth_agree.mp4",
    "continuous": "synth_continuous.mp4",
}
# continuous variant: pan speed (px/s at 1280 wide), jolt times, slow-down length and share
CONT_PAN_PX_S = 300.0
CONT_JOLTS = [20.0, 50.0, 85.0, 120.0, 155.0]
CONT_JOLT_S = 2.0
CONT_SLOW = 0.9  # the pan loses this share of its speed during a jolt
# lobby variant: (start, end) static cards; the second sits under a loud music bed
LOBBY_CARDS = [(20.0, 50.0), (100.0, 130.0)]
LOBBY_EVENTS = [70.0, 150.0]  # 1 s audio burst + 2 s motion burst together
# agree variant: one event of each kind
AGREE_LOUD, AGREE_MOTION, AGREE_BOTH = 40.0, 90.0, 140.0
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
    if variant in ("lobby", "agree"):
        return _build_events(out_dir, out, ffmpeg, variant)
    if variant == "continuous":
        return _build_continuous(out_dir, out, ffmpeg)
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


def _build_events(out_dir: Path, out: Path, ffmpeg: str, variant: str) -> Path:
    d = DURATION
    base = "0.04*sin(2*PI*220*t)+0.01*(random(0)-0.5)"
    if variant == "lobby":
        c0, c1 = LOBBY_CARDS[1]
        bursts = "+".join(f"between(t,{e},{e + 1.0})" for e in LOBBY_EVENTS)
        motion = "+".join(f"between(t,{e},{e + 2.0})" for e in LOBBY_EVENTS)
        music = f"(0.30*sin(2*PI*330*t)+0.12*sin(2*PI*660*t))*between(t,{c0},{c1})"
        audio = f"{base}+{music}+1.5*(random(0)-0.5)*({bursts})"
        cards = "+".join(f"between(t,{a},{b})" for a, b in LOBBY_CARDS)
        # static card: opaque grey frame; a 160x24 strip of testsrc (moving counters) = text
        extra_inputs = [
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x303030:s=1280x720:r=30:d={d}",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=160x24:rate=30:duration={d}",
        ]
        graph = (
            "[0:v][1:v]overlay=x='(W-w)*mod(t*1.7,1)':y='(H-h)*abs(sin(t*5))'"
            f":enable='{motion}'[g];"
            f"[g][3:v]overlay=0:0:enable='{cards}'[c];"
            f"[c][4:v]overlay=560:600:enable='{cards}'[v]"
        )
        truth = {
            "cards": [{"start": a, "end": b} for a, b in LOBBY_CARDS],
            "events": [{"t": e} for e in LOBBY_EVENTS],
        }
    else:
        bursts = (
            f"between(t,{AGREE_LOUD},{AGREE_LOUD + 1.0})+between(t,{AGREE_BOTH},{AGREE_BOTH + 1.0})"
        )
        motion = (
            f"between(t,{AGREE_MOTION},{AGREE_MOTION + 2.0})"
            f"+between(t,{AGREE_BOTH},{AGREE_BOTH + 2.0})"
        )
        audio = f"{base}+1.5*(random(0)-0.5)*({bursts})"
        extra_inputs = []
        graph = (
            f"[0:v][1:v]overlay=x='(W-w)*mod(t*1.7,1)':y='(H-h)*abs(sin(t*5))':enable='{motion}'[v]"
        )
        truth = {"loud": AGREE_LOUD, "motion": AGREE_MOTION, "both": AGREE_BOTH}
    cmd = [
        ffmpeg, "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=30:duration={d}",
        "-f", "lavfi", "-i", f"color=c=white:s=260x260:r=30:d={d}",
        "-f", "lavfi", "-i", f"aevalsrc=exprs='{audio}':s=48000:d={d}",
        *extra_inputs,
        "-filter_complex", graph, "-map", "[v]", "-map", "2:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(out),
    ]  # fmt: skip
    subprocess.run(cmd, check=True)
    truth["gen_version"] = GEN_VERSION
    truth["duration_s"] = d
    (out_dir / f"synth_{variant}.json").write_text(json.dumps(truth, indent=2))
    return out


def _build_continuous(out_dir: Path, out: Path, ffmpeg: str) -> Path:
    """Two identical testsrc2 tiles side by side, cropped with a moving window: a seamless
    constant pan (the whole frame moves all the time). A loud engine drone (harmonics with a
    slow RPM wobble, no onsets) runs throughout. At each jolt the pan drops to 10 % of its
    speed for CONT_JOLT_S and a 0.3 s broadband burst (the impact) sounds."""
    d = DURATION
    slow = "+".join(f"clip(t-{tj},0,{CONT_JOLT_S})" for tj in CONT_JOLTS)
    x = f"mod({CONT_PAN_PX_S}*t-{CONT_PAN_PX_S * CONT_SLOW}*({slow}),1280)"
    bursts = "+".join(f"between(t,{tj},{tj + 0.3})" for tj in CONT_JOLTS)
    drone = (
        "0.25*sin(2*PI*95*(t+0.02*sin(2*PI*0.2*t)))+0.12*sin(2*PI*190*t)"
        "+0.06*sin(2*PI*285*t)+0.03*sin(2*PI*380*t)+0.004*(random(0)-0.5)"
    )
    audio = f"{drone}+1.2*(random(0)-0.5)*({bursts})"
    cmd = [
        ffmpeg, "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=30:duration={d}",
        "-f", "lavfi", "-i", f"aevalsrc=exprs='{audio}':s=48000:d={d}",
        "-filter_complex", f"[0:v]split[a][b];[a][b]hstack[w];[w]crop=1280:720:x='{x}':y=0[v]",
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(out),
    ]  # fmt: skip
    subprocess.run(cmd, check=True)
    truth = {
        "jolts": [{"t": tj, "duration_s": CONT_JOLT_S} for tj in CONT_JOLTS],
        "gen_version": GEN_VERSION,
        "duration_s": d,
    }
    (out_dir / "synth_continuous.json").write_text(json.dumps(truth, indent=2))
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
    own = variant in ("square", "lobby", "agree", "continuous")
    truth = out_dir / (f"synth_{variant}.json" if own else "synth.json")
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
