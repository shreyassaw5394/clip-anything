"""Streaming visual features per 0.5 s hop from a gray 320 px / 5 fps proxy.

Raw signals (normalisation is scoring's job):
  video.motion      mean |frame diff| over the window (0..255)
  video.hist_delta  max persistent histogram distance in the window (0..1); flashes removed
  video.cut         hist_delta where it exceeds an adaptive threshold, else 0 (finalize)
  video.flash       max single-frame brightness spike (jump up then back) in the window
  video.cx          centre of motion mass, x fraction 0..1 of proxy width; NaN when motion weak
  video.cspread     x spread of the motion mass (std, 0..~0.29); high = diffuse/global motion
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

EXTRACTOR_VERSION = 1
HIST_BINS = 32
EDGE_FRAC = 0.06  # ignore this border fraction for the centroid (HUD, letterbox)
MOTION_FLOOR = 1.5  # mean abs diff below this: no reliable centroid
CUT_MIN = 0.30  # persistent histogram distance below this is never a cut


@dataclass
class _Frame:
    motion: float
    hist_delta: float
    bright: float
    cx: float
    cspread: float


class VideoExtractor:
    """Feed gray uint8 frames [k, h, w] in any chunking; results are chunk-invariant.
    Per-frame rows are aggregated into windows of `hop_s` by frame index / fps."""

    def __init__(self, fps: float, hop_s: float, width: int, height: int):
        self.fps = fps
        self.hop_s = hop_s
        self.w = width
        self.h = height
        self._prev: np.ndarray | None = None
        self._prev_hist: np.ndarray | None = None
        self._prev_bright = 0.0
        self._prev_bright2 = 0.0
        self._suppress_next = False  # frame after a flash: its 'return' jump is not a cut
        self._pending: _Frame | None = None  # needs the next frame to confirm cut vs flash
        self._prev_delta = 0.0
        self._n_frames = 0
        # per-frame confirmed rows (motion, cut_persist, flash, cx, cspread)
        self._rows: list[tuple[float, float, float, float, float]] = []
        x0 = int(round(width * EDGE_FRAC))
        y0 = int(round(height * EDGE_FRAC))
        self._mask = np.zeros((height, width), dtype=np.float32)
        self._mask[y0 : height - y0, x0 : width - x0] = 1.0
        self._xs = (np.arange(width, dtype=np.float32) + 0.5) / width

    def feed(self, frames: np.ndarray) -> None:
        for f in frames:
            self._frame(f)

    def finish(self) -> None:
        if self._pending is not None:
            p = self._pending
            self._rows.append((p.motion, p.hist_delta, 0.0, p.cx, p.cspread))
            self._pending = None

    def _frame(self, f: np.ndarray) -> None:
        f16 = f.astype(np.int16)
        hist = np.bincount(f.ravel() >> 3, minlength=HIST_BINS).astype(np.float64)
        hist /= max(1.0, hist.sum())
        bright = float(f16.mean())
        if self._prev is None:
            row = _Frame(0.0, 0.0, bright, np.nan, np.nan)
        else:
            diff = np.abs(f16 - self._prev).astype(np.float32)
            motion = float(diff.mean())
            delta = float(np.sqrt(max(0.0, 1.0 - np.sum(np.sqrt(hist * self._prev_hist)))))
            cx, spread = self._centroid(diff, motion)
            row = _Frame(motion, delta, bright, cx, spread)
        self._n_frames += 1
        # confirm the pending frame now that we know what followed it
        if self._pending is not None:
            p = self._pending
            flash = 0.0
            persist = 0.0 if self._suppress_next else p.hist_delta
            self._suppress_next = False
            up = p.bright - self._prev_bright2
            back = bright - p.bright
            if p.hist_delta > 0.15 and row.hist_delta > 0.5 * p.hist_delta:
                # the scene jumped and jumped again: a flash (or very fast cutting), not a cut
                persist = 0.0
                self._suppress_next = True
                if up > 8.0 and back < -0.5 * up:
                    flash = min(p.hist_delta, row.hist_delta)
            self._rows.append((p.motion, persist, flash, p.cx, p.cspread))
        self._prev_bright2 = self._prev_bright
        self._prev_bright = bright
        self._pending = row
        self._prev = f16
        self._prev_hist = hist

    def _centroid(self, diff: np.ndarray, motion: float) -> tuple[float, float]:
        if motion < MOTION_FLOOR:
            return np.nan, np.nan
        d = diff * self._mask
        thr = float(np.percentile(d[d > 0], 95)) if np.any(d > 0) else 0.0
        d = np.where(d >= max(thr, 1.0), d, 0.0)
        col = d.sum(axis=0)
        total = float(col.sum())
        if total <= 0:
            return np.nan, np.nan
        p = col / total
        cx = float(np.dot(p, self._xs))
        spread = float(np.sqrt(max(0.0, np.dot(p, self._xs**2) - cx * cx)))
        return cx, spread

    def result(self, duration_s: float) -> dict[str, np.ndarray]:
        n = int(np.ceil(duration_s / self.hop_s)) if duration_s > 0 else 0
        rows = np.asarray(self._rows, dtype=np.float32).reshape(-1, 5)
        k = np.arange(rows.shape[0])
        win = np.floor(k / self.fps / self.hop_s).astype(int)
        n = max(n, int(win.max()) + 1 if win.size else 0)
        out = {
            "video.motion": np.zeros(n, np.float32),
            "video.hist_delta": np.zeros(n, np.float32),
            "video.flash": np.zeros(n, np.float32),
            "video.cx": np.full(n, np.nan, np.float32),
            "video.cspread": np.full(n, np.nan, np.float32),
        }
        if rows.size == 0:
            return out
        counts = np.bincount(win, minlength=n).astype(np.float32)
        nz = counts > 0
        out["video.motion"][nz] = np.bincount(win, rows[:, 0], n)[nz] / counts[nz]
        np.maximum.at(out["video.hist_delta"], win, rows[:, 1])
        np.maximum.at(out["video.flash"], win, rows[:, 2])
        valid = np.isfinite(rows[:, 3])
        if valid.any():
            wv = win[valid]
            cnt = np.bincount(wv, minlength=n).astype(np.float32)
            ok = cnt > 0
            # weight the centroid by motion so the strongest frames dominate the window
            wgt = rows[valid, 0] + 1e-3
            sx = np.bincount(wv, rows[valid, 3] * wgt, n)
            ss = np.bincount(wv, rows[valid, 4] * wgt, n)
            sw = np.bincount(wv, wgt, n)
            out["video.cx"][ok] = sx[ok] / sw[ok]
            out["video.cspread"][ok] = ss[ok] / sw[ok]
        return out


def finalize(arrays: dict[str, np.ndarray]) -> None:
    """video.cut = hist_delta where it exceeds max(CUT_MIN, median + 6*MAD), else 0."""
    hd = arrays["video.hist_delta"].astype(np.float32)
    if hd.size == 0:
        arrays["video.cut"] = hd.copy()
        return
    med = float(np.median(hd))
    mad = float(np.median(np.abs(hd - med)))
    thr = max(CUT_MIN, med + 6.0 * 1.4826 * mad)
    arrays["video.cut"] = np.where(hd > thr, hd, 0.0).astype(np.float32)


def extract_video(
    chunks: Iterable[bytes],
    fps: float,
    hop_s: float,
    width: int,
    height: int,
    duration_s: float,
    progress=None,
) -> dict[str, np.ndarray]:
    ex = VideoExtractor(fps, hop_s, width, height)
    frame_bytes = width * height
    fed = 0
    for buf in chunks:
        frames = np.frombuffer(buf, dtype=np.uint8).reshape(-1, height, width)
        ex.feed(frames)
        fed += len(buf) // frame_bytes
        if progress is not None:
            progress(min(duration_s, fed / fps))
    ex.finish()
    arrays = ex.result(duration_s)
    finalize(arrays)
    return arrays
