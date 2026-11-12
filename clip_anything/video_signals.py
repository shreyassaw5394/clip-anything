"""Streaming visual features per 0.5 s hop from a gray 320 px / 5 fps proxy.

Raw signals (normalisation is scoring's job):
  video.motion      mean |frame diff| over the window (0..255)
  video.hist_delta  max persistent histogram distance in the window (0..1); flashes removed
  video.cut         hist_delta where it exceeds an adaptive threshold, else 0 (finalize)
  video.flash       max single-frame brightness spike (jump up then back) in the window
  video.cx          centre of motion mass, x fraction 0..1 of proxy width; NaN when motion weak
  video.cspread     x spread of the motion mass (std, 0..~0.29); high = diffuse/global motion
  video.still       mean fraction of pixels with |diff| <= STILL_DIFF (static card detector)
  video.stroke      mean fraction of changed pixels (diff > CHANGE_DIFF) that are thin strokes
                    (removed by a 3x3 opening): text/HUD counters, not moving objects.
                    Frames with no changed pixels count as 1.0 (nothing but noise).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import cv2
import numpy as np

EXTRACTOR_VERSION = 2
HIST_BINS = 32
EDGE_FRAC = 0.06  # ignore this border fraction for the centroid (HUD, letterbox)
MOTION_FLOOR = 0.3  # mean abs diff below this: no centroid (diffuse noise is caught by cspread)
CUT_MIN = 0.30  # persistent histogram distance below this is never a cut
STILL_DIFF = 2  # |diff| at or below this = unchanged pixel
CHANGE_DIFF = 20  # |diff| above this = changed pixel (stroke test)
_OPEN_KERNEL = np.ones((3, 3), np.uint8)


@dataclass
class _Frame:
    motion: float
    hist_delta: float
    bright: float
    cx: float
    cspread: float
    still: float = 1.0
    stroke: float = 1.0


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
        # per-frame confirmed rows (motion, cut_persist, flash, cx, cspread, still, stroke)
        self._rows: list[tuple[float, float, float, float, float, float, float]] = []
        x0 = int(round(width * EDGE_FRAC))
        y0 = int(round(height * EDGE_FRAC))
        self._mask = np.zeros((height, width), dtype=np.float32)
        self._mask[y0 : height - y0, x0 : width - x0] = 1.0
        self._xs = (np.arange(width, dtype=np.float64) + 0.5) / width

    def feed(self, frames: np.ndarray) -> None:
        """Vectorised per chunk: diffs, histograms and centroids in numpy; only the scalar
        cut/flash confirmation runs per frame."""
        if frames.size == 0:
            return
        k = frames.shape[0]
        hw = self.w * self.h
        # histograms on a 2x2-subsampled frame (cut detection does not need every pixel)
        sub = frames[:, ::2, ::2].reshape(k, -1)
        hist = np.bincount(
            (
                (sub >> 3).astype(np.int32) + (np.arange(k, dtype=np.int32) * HIST_BINS)[:, None]
            ).ravel(),
            minlength=k * HIST_BINS,
        ).reshape(k, HIST_BINS) / float(sub.shape[1])
        bright = sub.sum(axis=1, dtype=np.uint32) / float(sub.shape[1])
        if self._prev is None:
            self._push(_Frame(0.0, 0.0, float(bright[0]), np.nan, np.nan))
            if k == 1:
                self._prev, self._prev_hist = frames[-1], hist[-1]
                return
            prev = frames[:-1]
            frames, hist_cur, bright = frames[1:], hist[1:], bright[1:]
            prev_hist = hist[:-1]
            k -= 1
        else:
            prev = np.concatenate([self._prev[None], frames[:-1]])
            hist_cur = hist
            prev_hist = np.concatenate([self._prev_hist[None], hist[:-1]])
        diff = cv2.absdiff(frames.reshape(k * self.h, self.w), prev.reshape(k * self.h, self.w))
        diff = diff.reshape(k, self.h, self.w)
        motion = diff.reshape(k, -1).sum(axis=1, dtype=np.uint32) / float(hw)
        still = (diff <= STILL_DIFF).reshape(k, -1).sum(axis=1) / float(hw)
        # stroke test on a 2x2 subsample: 1-2 px text strokes vanish under a 3x3 opening,
        # moving objects survive; 4x cheaper than full resolution
        changed = (diff[:, ::2, ::2] > CHANGE_DIFF).astype(np.uint8)
        changed = np.ascontiguousarray(changed.reshape(-1, changed.shape[2]))
        opened = cv2.morphologyEx(changed, cv2.MORPH_OPEN, _OPEN_KERNEL)
        n_changed = changed.reshape(k, -1).sum(axis=1, dtype=np.int64)
        n_thin = (changed & (opened == 0)).reshape(k, -1).sum(axis=1, dtype=np.int64)
        stroke = np.where(n_changed > 0, n_thin / np.maximum(n_changed, 1), 1.0)
        bc = np.sqrt(hist_cur * prev_hist).sum(axis=1)
        delta = np.sqrt(np.maximum(0.0, 1.0 - bc))
        # centroid: squared diff (motion >> noise) inside the edge mask, summed per column
        d = diff.astype(np.float32)
        cols = np.einsum("khw,khw,hw->kw", d, d, self._mask)
        total = cols.sum(axis=1)
        ok = (motion >= MOTION_FLOOR) & (total > 0)
        cx = np.full(k, np.nan)
        spread = np.full(k, np.nan)
        if ok.any():
            p = cols[ok] / total[ok][:, None]
            m1 = p @ self._xs
            m2 = p @ (self._xs**2)
            cx[ok] = m1
            spread[ok] = np.sqrt(np.maximum(0.0, m2 - m1 * m1))
        for i in range(k):
            self._push(
                _Frame(
                    float(motion[i]),
                    float(delta[i]),
                    float(bright[i]),
                    cx[i],
                    spread[i],
                    float(still[i]),
                    float(stroke[i]),
                )
            )
        self._prev = frames[-1]
        self._prev_hist = hist_cur[-1]

    def finish(self) -> None:
        if self._pending is not None:
            p = self._pending
            self._rows.append((p.motion, p.hist_delta, 0.0, p.cx, p.cspread, p.still, p.stroke))
            self._pending = None

    def _push(self, row: _Frame) -> None:
        """Confirm the pending frame now that we know what followed it."""
        self._n_frames += 1
        if self._pending is not None:
            p = self._pending
            flash = 0.0
            persist = 0.0 if self._suppress_next else p.hist_delta
            self._suppress_next = False
            up = p.bright - self._prev_bright2
            back = row.bright - p.bright
            if p.hist_delta > 0.15 and row.hist_delta > 0.5 * p.hist_delta:
                # the scene jumped and jumped again: a flash (or very fast cutting), not a cut
                persist = 0.0
                self._suppress_next = True
                if up > 8.0 and back < -0.5 * up:
                    flash = min(p.hist_delta, row.hist_delta)
            self._rows.append((p.motion, persist, flash, p.cx, p.cspread, p.still, p.stroke))
        self._prev_bright2 = self._prev_bright
        self._prev_bright = row.bright
        self._pending = row

    def result(self, duration_s: float) -> dict[str, np.ndarray]:
        n = int(np.ceil(duration_s / self.hop_s)) if duration_s > 0 else 0
        rows = np.asarray(self._rows, dtype=np.float32).reshape(-1, 7)
        k = np.arange(rows.shape[0])
        win = np.floor(k / self.fps / self.hop_s).astype(int)
        n = max(n, int(win.max()) + 1 if win.size else 0)
        out = {
            "video.motion": np.zeros(n, np.float32),
            "video.hist_delta": np.zeros(n, np.float32),
            "video.flash": np.zeros(n, np.float32),
            "video.cx": np.full(n, np.nan, np.float32),
            "video.cspread": np.full(n, np.nan, np.float32),
            "video.still": np.ones(n, np.float32),
            "video.stroke": np.ones(n, np.float32),
        }
        if rows.size == 0:
            return out
        counts = np.bincount(win, minlength=n).astype(np.float32)
        nz = counts > 0
        out["video.motion"][nz] = np.bincount(win, rows[:, 0], n)[nz] / counts[nz]
        out["video.still"][nz] = np.bincount(win, rows[:, 5], n)[nz] / counts[nz]
        out["video.stroke"][nz] = np.bincount(win, rows[:, 6], n)[nz] / counts[nz]
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
