"""Action-following crop: video.cx inside a clip -> smoothed keyframes. Pure numpy, no I/O.

Keyframes are [t_rel, left] where left is the crop's left edge as a fraction 0..1 of the
available travel (iw - ow). Render turns them into one piecewise-linear crop expression."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np

from .audio_signals import Signals
from .config import LayoutOptions, RenderOptions
from .probe import MediaInfo


@dataclass
class CropPlan:
    mode: str = "center"  # center | follow
    keyframes: list[list[float]] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def fill_nan(x: np.ndarray) -> np.ndarray:
    """Hold-last then hold-next; all-NaN input comes back unchanged."""
    x = x.astype(np.float64).copy()
    ok = np.isfinite(x)
    if not ok.any():
        return x
    idx = np.where(ok, np.arange(x.size), 0)
    np.maximum.accumulate(idx, out=idx)
    x = x[idx]
    first = int(np.argmax(ok))
    x[:first] = x[first]
    return x


def one_euro(x: np.ndarray, dt: float, min_cutoff: float, beta: float, d_cutoff=1.0):
    def alpha(cutoff: float) -> float:
        tau = 1.0 / (2.0 * math.pi * max(cutoff, 1e-6))
        return 1.0 / (1.0 + tau / dt)

    out = np.empty_like(x)
    x_prev = float(x[0])
    dx_prev = 0.0
    out[0] = x_prev
    a_d = alpha(d_cutoff)
    for i in range(1, x.size):
        v = float(x[i])
        dx = (v - x_prev) / dt
        dx_hat = a_d * dx + (1.0 - a_d) * dx_prev
        a = alpha(min_cutoff + beta * abs(dx_hat))
        x_prev = a * v + (1.0 - a) * x_prev
        dx_prev = dx_hat
        out[i] = x_prev
    return out


def deadband_speed_cap(f: np.ndarray, deadband: float, max_step: float) -> np.ndarray:
    """Hold until the target moves more than `deadband`; never move more than `max_step`/hop."""
    out = np.empty_like(f)
    cur = float(f[0])
    target = cur
    for i in range(f.size):
        if abs(float(f[i]) - target) > deadband:
            target = float(f[i])
        step = max(-max_step, min(max_step, target - cur))
        cur += step
        out[i] = cur
    return out


def plan_crop(
    sig: Signals,
    start: float,
    end: float,
    info: MediaInfo,
    layout: LayoutOptions,
    render: RenderOptions,
) -> CropPlan:
    if layout.crop != "follow":
        return CropPlan("center", [], "disabled")
    cx_all = sig.arrays.get("video.cx")
    cs_all = sig.arrays.get("video.cspread")
    if cx_all is None or cx_all.size != sig.n:
        return CropPlan("center", [], "no motion signal")
    w, h = info.display_size
    cw = min(w, h * render.width / render.height)
    travel = w - cw
    if travel < 2:
        return CropPlan("center", [], "no horizontal travel")
    i0, i1 = sig.index_of(start), sig.index_of(end)
    cx = np.asarray(cx_all[i0 : i1 + 1], dtype=np.float64)
    if cx.size < 2:
        return CropPlan("center", [], "clip too short")
    finite = np.isfinite(cx)
    if finite.mean() < 0.4:
        return CropPlan("center", [], f"motion sparse ({finite.mean():.0%} of windows)")
    if cs_all is not None and cs_all.size == sig.n:
        cs = np.asarray(cs_all[i0 : i1 + 1], dtype=np.float64)
        cs = cs[np.isfinite(cs)]
        if cs.size and float(np.median(cs)) > layout.diffuse_spread:
            return CropPlan("center", [], f"motion diffuse (spread {np.median(cs):.2f})")
    from scipy.ndimage import median_filter

    x = fill_nan(cx)
    x = median_filter(x, size=min(5, x.size) | 1, mode="nearest")
    x = one_euro(x, sig.hop_s, layout.min_cutoff, layout.beta)
    left = np.clip((x * w - cw / 2.0) / travel, 0.0, 1.0)
    max_step = layout.pan_speed * w / travel * sig.hop_s
    left = deadband_speed_cap(left, layout.deadband, max_step)
    if float(left.max() - left.min()) < 1e-3:
        return CropPlan("follow", [[0.0, round(float(left[0]), 4)]], "static")
    keys = []
    for k in range(left.size):
        t_rel = (i0 + k) * sig.hop_s - start
        keys.append([round(max(0.0, t_rel), 3), round(float(left[k]), 4)])
    keys[0][0] = 0.0
    return CropPlan("follow", keys, f"{len(keys)} keyframes")


def x_expression(keyframes: list[list[float]]) -> str:
    """Nested piecewise-linear ffmpeg expression in t (clip-relative seconds), value 0..1."""
    if not keyframes:
        return "0.5"
    if len(keyframes) == 1:
        return f"{keyframes[0][1]:.4f}"
    expr = f"{keyframes[-1][1]:.4f}"
    for (t0, x0), (t1, x1) in reversed(list(zip(keyframes[:-1], keyframes[1:], strict=True))):
        dt = max(t1 - t0, 1e-3)
        expr = f"if(lt(t,{t1:.3f}),{x0:.4f}+({x1 - x0:.4f})*(t-{t0:.3f})/{dt:.3f},{expr})"
    return expr
