"""Facecam detection: a static rectangle in a corner (low temporal variance across sampled
frames, high everywhere the game moves) that contains a face on >= 2 of the samples (Haar,
ships with opencv). Default off below the confidence floor; console captures report none."""

from __future__ import annotations

import os
import subprocess
from dataclasses import asdict, dataclass

import numpy as np

from .probe import FFmpegCaps, MediaInfo, _popen_kwargs

SAMPLE_WIDTH = 640
CORNER_FRAC = 0.42  # each corner search window spans this fraction of width/height
MIN_AREA_FRAC = 0.015  # facecam must cover >= 1.5 % of the frame
MAX_AREA_FRAC = 0.20


@dataclass
class Facecam:
    x: float  # fractions of the display frame
    y: float
    w: float
    h: float
    corner: str
    confidence: float
    face_hits: int
    samples: int

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("x", "y", "w", "h", "confidence"):
            d[k] = round(d[k], 4)
        return d


def sample_frames(
    info: MediaInfo, caps: FFmpegCaps, n: int, width: int = SAMPLE_WIDTH
) -> list[np.ndarray]:
    """n gray frames spread over the recording (skipping the first/last 5 %), via seeks."""
    w, h = info.display_size
    if w <= 0 or h <= 0 or info.duration_s <= 0:
        return []
    ph = max(2, int(round(width * h / w / 2)) * 2)
    out: list[np.ndarray] = []
    for i in range(n):
        t = info.duration_s * (0.05 + 0.9 * (i + 0.5) / n)
        cmd = [
            caps.ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{t:.3f}",
            "-i",
            os.fspath(info.path),
            "-frames:v",
            "1",
            "-vf",
            f"scale={width}:{ph},format=gray",
            "-f",
            "rawvideo",
            "-",
        ]
        res = subprocess.run(cmd, capture_output=True, check=False, **_popen_kwargs())
        if res.returncode != 0 or len(res.stdout) < width * ph:
            continue
        out.append(np.frombuffer(res.stdout[: width * ph], np.uint8).reshape(ph, width))
    return out


def _corner_windows(h: int, w: int) -> dict[str, tuple[int, int, int, int]]:
    cw, ch = int(w * CORNER_FRAC), int(h * CORNER_FRAC)
    return {
        "top-left": (0, 0, cw, ch),
        "top-right": (w - cw, 0, cw, ch),
        "bottom-left": (0, h - ch, cw, ch),
        "bottom-right": (w - cw, h - ch, cw, ch),
    }


def static_regions(frames: list[np.ndarray], std_thresh: float | None = None) -> list[dict]:
    """Connected blobs that are static over time (per-pixel temporal std below a threshold set
    relative to the frame) AND textured in space (flat colour bars, letterbox and blank HUD
    panels never qualify), touching a corner window. Dicts: x,y,w,h (px), frac, corner."""
    import cv2

    if len(frames) < 3:
        return []
    stack = np.stack(frames).astype(np.float32)
    std = stack.std(axis=0)
    h, w = std.shape
    if float(np.median(std)) < 4.0:
        return []  # the whole picture is static (menu, pause): no corner stands out
    if std_thresh is None:
        std_thresh = max(6.0, min(18.0, 0.35 * float(np.median(std))))
    static = (std < std_thresh).astype(np.uint8)
    # texture that persists: the edge must sit on the same pixel in EVERY sample (a sweeping
    # edge of a flat area shows up in one frame only, so its min gradient is ~0)
    grad = None
    for fr in stack:
        g = np.abs(cv2.Sobel(fr, cv2.CV_32F, 1, 0, ksize=3)) + np.abs(
            cv2.Sobel(fr, cv2.CV_32F, 0, 1, ksize=3)
        )
        grad = g if grad is None else np.minimum(grad, g)
    textured = (grad > 40.0).astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    mask = cv2.morphologyEx(static & textured, cv2.MORPH_CLOSE, k)
    n, _labels, stats, _cent = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out: list[dict] = []
    for i in range(1, n):
        x, y, bw, bh, _area = (int(v) for v in stats[i])
        frac = bw * bh / (w * h)
        if frac < MIN_AREA_FRAC or frac > MAX_AREA_FRAC:
            continue
        if static[y : y + bh, x : x + bw].mean() < 0.5:
            continue  # the box must be static as a whole, not just its edges
        for corner, (cx, cy, cw, ch) in _corner_windows(h, w).items():
            inter_w = min(x + bw, cx + cw) - max(x, cx)
            inter_h = min(y + bh, cy + ch) - max(y, cy)
            if inter_w > 0 and inter_h > 0 and inter_w * inter_h >= 0.8 * bw * bh:
                out.append({"x": x, "y": y, "w": bw, "h": bh, "frac": frac, "corner": corner})
                break
    return out


def face_boxes(frame: np.ndarray, min_size: int = 24) -> list[tuple[int, int, int, int]]:
    import cv2

    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if cascade.empty():
        return []
    eq = cv2.equalizeHist(frame)
    faces = cascade.detectMultiScale(
        eq, scaleFactor=1.1, minNeighbors=4, minSize=(min_size, min_size)
    )
    return [tuple(int(v) for v in f) for f in faces]


def _contains(region: dict, box: tuple[int, int, int, int]) -> bool:
    fx, fy, fw, fh = box
    cx, cy = fx + fw / 2, fy + fh / 2
    return (
        region["x"] <= cx <= region["x"] + region["w"]
        and region["y"] <= cy <= region["y"] + region["h"]
    )


def detect_facecam(
    info: MediaInfo,
    caps: FFmpegCaps,
    samples: int = 5,
    min_hits: int = 2,
    min_confidence: float = 0.4,
    frames: list[np.ndarray] | None = None,
) -> Facecam | None:
    """Static corner region with a Haar face on >= min_hits of the samples, else None."""
    frames = sample_frames(info, caps, samples) if frames is None else frames
    if len(frames) < 3:
        return None
    regions = static_regions(frames)
    if not regions:
        return None
    h, w = frames[0].shape
    best: Facecam | None = None
    for region in regions:
        hits = 0
        for fr in frames:
            # search a slightly padded window so faces on the region edge still count
            pad = 8
            x0, y0 = max(0, region["x"] - pad), max(0, region["y"] - pad)
            x1 = min(w, region["x"] + region["w"] + pad)
            y1 = min(h, region["y"] + region["h"] + pad)
            sub = np.ascontiguousarray(fr[y0:y1, x0:x1])
            boxes = [(bx + x0, by + y0, bw, bh) for bx, by, bw, bh in face_boxes(sub)]
            if any(_contains(region, b) for b in boxes):
                hits += 1
        conf = hits / len(frames)
        if hits >= min_hits and conf >= min_confidence:
            cand = Facecam(
                region["x"] / w,
                region["y"] / h,
                region["w"] / w,
                region["h"] / h,
                region["corner"],
                conf,
                hits,
                len(frames),
            )
            if best is None or cand.confidence > best.confidence:
                best = cand
    return best
