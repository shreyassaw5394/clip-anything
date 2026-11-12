"""Phase 3 fixtures: a drawn face (no real person) in a static corner box over moving test
video, and a speech stand-in made with the macOS `say` TTS (skipped elsewhere)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np

DUR = 24


def draw_face(size: int = 200) -> np.ndarray:
    """Cartoon face (gray) that the Haar frontal cascade detects at 120-260 px."""
    import cv2

    img = np.full((size, size), 170, np.uint8)
    c = size // 2
    cv2.ellipse(img, (c, c), (int(size * 0.30), int(size * 0.40)), 0, 0, 360, 215, -1)
    for dx in (-1, 1):
        ex, ey = c + dx * int(size * 0.13), c - int(size * 0.10)
        cv2.ellipse(img, (ex, ey), (int(size * 0.07), int(size * 0.045)), 0, 0, 360, 120, -1)
        cv2.circle(img, (ex, ey), int(size * 0.03), 30, -1)
        cv2.ellipse(
            img,
            (ex, ey - int(size * 0.08)),
            (int(size * 0.09), int(size * 0.02)),
            0,
            0,
            360,
            90,
            -1,
        )
    cv2.line(img, (c, c - int(size * 0.05)), (c - int(size * 0.03), c + int(size * 0.10)), 150, 2)
    cv2.ellipse(
        img, (c, c + int(size * 0.20)), (int(size * 0.10), int(size * 0.035)), 0, 0, 360, 100, -1
    )
    cv2.ellipse(
        img, (c, c - int(size * 0.30)), (int(size * 0.31), int(size * 0.16)), 0, 180, 360, 60, -1
    )
    return img


def build_facecam_video(out_dir: Path, corner: str = "top-left") -> Path:
    """1280x720 panning testsrc2 with a static 320x240 'webcam' box holding the drawn face."""
    import cv2

    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / "face.png"
    cam = np.full((240, 320), 150, np.uint8)
    cam[20:220, 60:260] = draw_face(200)
    cv2.rectangle(cam, (0, 0), (319, 239), 40, 6)
    cv2.imwrite(str(png), cam)
    x = 20 if "left" in corner else 1280 - 320 - 20
    y = 20 if "top" in corner else 720 - 240 - 20
    out = out_dir / f"synth_facecam_{corner}.mp4"
    cmd = [
        "ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc2=size=1480x840:rate=30:duration={DUR}",
        "-loop", "1", "-i", str(png),
        "-f", "lavfi", "-i", f"aevalsrc=exprs='0.3*sin(2*PI*220*t)*gt(mod(t,6),5)':s=48000:d={DUR}",
        "-filter_complex",
        "[0:v]crop=1280:720:x='100+90*sin(t)':y='60+50*cos(1.3*t)'[bg];"
        f"[1:v]format=gray,format=yuv420p[cam];[bg][cam]overlay={x}:{y}:shortest=1[v]",
        "-map", "[v]", "-map", "2:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(out),
    ]  # fmt: skip
    subprocess.run(cmd, check=True)
    return out


SPEECH_TEXT = "No way. Let's go! Oh my god, that was insane, bro."
SPEECH_AT = 3.0
ACTION_AT = 8.0


def build_speech_video(out_dir: Path) -> Path | None:
    """Panning testsrc2 + TTS speech at 3 s (macOS `say`) + one action moment at 8 s (loud
    burst + a fast white square) so the scorer has a peak; None when `say` is unavailable."""
    if not shutil.which("say"):
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    aiff = out_dir / "speech.aiff"
    subprocess.run(["say", "-o", str(aiff), SPEECH_TEXT], check=True)
    out = out_dir / "synth_speech.mp4"
    ms = int(SPEECH_AT * 1000)
    cmd = [
        "ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc2=size=1480x840:rate=30:duration={DUR}",
        "-i", str(aiff),
        "-f", "lavfi", "-i",
        f"aevalsrc=exprs='0.9*sin(2*PI*180*t)*between(t,{ACTION_AT},{ACTION_AT + 1.2})'"
        f":s=48000:d={DUR}",
        "-f", "lavfi", "-i", f"color=c=white:s=260x260:r=30:d={DUR}",
        "-filter_complex",
        f"[1:a]adelay={ms}|{ms},apad,atrim=0:{DUR},aformat=sample_rates=48000:channel_layouts=mono[sp];"
        "[2:a]aformat=sample_rates=48000:channel_layouts=mono[bu];"
        "[sp][bu]amix=inputs=2:normalize=0[a];"
        "[0:v]crop=1280:720:x='100+90*sin(t)':y='60+50*cos(1.3*t)'[bg];"
        "[bg][3:v]overlay=x='(W-w)*mod(t*1.7,1)':y='(H-h)*abs(sin(t*5))'"
        f":enable='between(t,{ACTION_AT},{ACTION_AT + 2})'[v]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(out),
    ]  # fmt: skip
    subprocess.run(cmd, check=True)
    return out
