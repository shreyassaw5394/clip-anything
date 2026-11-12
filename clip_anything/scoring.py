"""Signals -> action score -> peaks -> windows -> snap -> NMS. Pure numpy/scipy, no I/O."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np

from .audio_signals import Signals
from .config import ScoringOptions

# (signal name, weight attr, floor attr, eps for the MAD denominator in raw units)
BASE_SIGNALS = (
    ("audio.loud_rel", "w_loud", "floor_loud_db", 1.0),
    ("audio.onset", "w_onset", "floor_onset", 0.05),
    ("audio.rms_db", "w_rms", "floor_rms_db", 1.0),
    ("video.motion", "w_motion", "floor_motion", 0.5),
)


@dataclass
class Candidate:
    id: int
    peak_t: float
    score: float
    prominence: float
    components: dict[str, float]
    start: float
    end: float
    snap: dict = field(default_factory=dict)
    features: dict[str, float] = field(default_factory=dict)

    @property
    def duration_s(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        d = asdict(self)
        d["duration_s"] = round(self.duration_s, 3)
        return d


def _rolling_median(x: np.ndarray, size: int) -> np.ndarray:
    from scipy.ndimage import median_filter

    size = int(max(3, min(size, x.size))) | 1
    return median_filter(x, size=size, mode="nearest")


def robust_normalise(
    x: np.ndarray, window: int, z_soft: float, eps: float, scale_frac: float = 0.25
) -> np.ndarray:
    """tanh(z / z_soft) of the positive rolling z-score, z = (x - rolling median) / sigma.
    sigma = max(1.4826 * rolling MAD, eps, scale_frac * global (p90 - p50)): a flat stretch
    (menu, lobby, quiet room) cannot make the next small change look huge."""
    x = np.nan_to_num(x.astype(np.float64), nan=0.0)
    if x.size == 0:
        return x
    med = _rolling_median(x, window)
    mad = _rolling_median(np.abs(x - med), window)
    p50, p90 = np.percentile(x, [50.0, 90.0])
    sigma = np.maximum(1.4826 * mad, max(eps, scale_frac * float(p90 - p50)))
    z = np.maximum(0.0, (x - med) / sigma)
    return np.tanh(z / z_soft)


def informativeness(x: np.ndarray, floor: float) -> float:
    """0..1: how much the top 1% of the signal stands out from its median (rare-event safe)."""
    x = x[np.isfinite(x)]
    if x.size < 4:
        return 0.0
    k = max(3, int(x.size * 0.01))
    top = np.sort(x)[-k:]
    spread = float(top.mean() - np.median(x))
    return float(np.clip(spread / max(floor, 1e-9), 0.0, 1.0))


def card_score(sig: Signals, opts: ScoringOptions) -> np.ndarray | None:
    """0..1 per window: a static card = almost every pixel unchanged, and what does change is
    thin strokes (text, counters). Pure still frames count fully."""
    still = sig.arrays.get("video.still")
    if still is None or still.size != sig.n:
        return None
    still = np.nan_to_num(still.astype(np.float64), nan=0.0)
    stroke = sig.arrays.get("video.stroke")
    stroke = np.ones(sig.n) if stroke is None or stroke.size != sig.n else np.nan_to_num(stroke)
    # a card is a property of the neighbourhood: a menu page flip or a cursor move inside a
    # static screen must not look like motion, so judge the rolling median over card_s
    k = int(opts.card_s / sig.hop_s)
    still = _rolling_median(still, k)
    stroke = _rolling_median(stroke.astype(np.float64), k)
    still_n = np.clip((still - opts.still_lo) / max(1e-6, 0.98 - opts.still_lo), 0.0, 1.0)
    stroke_n = np.clip(stroke / 0.5, 0.0, 1.0)
    return still_n * (0.6 + 0.4 * stroke_n)


def action_score(sig: Signals, opts: ScoringOptions) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Return (score 0..1 per window, per-signal normalised+gated components).
    score = w_mean * weighted mean + w_max * max + w_agree * sqrt(audio * motion), where the
    agreement term degrades to the remaining group when one group is absent/uninformative;
    plus a small cut bonus, times the static-card and intro/outro factors."""
    n = sig.n
    window = int(opts.local_window_s / sig.hop_s)
    comps: dict[str, np.ndarray] = {}
    weights: dict[str, float] = {}
    for name, wattr, fattr, eps in BASE_SIGNALS:
        raw = sig.arrays.get(name)
        w = float(getattr(opts, wattr))
        if raw is None or raw.size != n or w <= 0:
            continue
        gate = informativeness(raw, float(getattr(opts, fattr)))
        if gate <= 0:
            continue
        s = robust_normalise(raw, window, opts.z_soft, eps, opts.scale_frac) * gate
        comps[name] = s
        weights[name] = w
    if not comps:
        return np.zeros(n), comps
    wsum = sum(weights.values())
    base = sum(weights[k] * comps[k] for k in comps) / wsum
    peak = np.max(np.stack(list(comps.values())), axis=0)
    groups = []
    for prefix in ("audio.", "video."):
        names = [k for k in comps if k.startswith(prefix)]
        if names:
            stack = np.stack([comps[k] for k in names])
            gw = np.array([weights[k] for k in names])[:, None]
            groups.append(0.5 * (stack * gw).sum(axis=0) / gw.sum() + 0.5 * stack.max(axis=0))
    agree = np.sqrt(np.prod(np.stack(groups), axis=0)) if len(groups) == 2 else groups[0]
    wsum3 = opts.w_mean + opts.w_max + opts.w_agree
    score = (opts.w_mean * base + opts.w_max * peak + opts.w_agree * agree) / max(wsum3, 1e-9)
    cut = sig.arrays.get("video.cut")
    if cut is not None and cut.size == n and opts.w_cut > 0:
        near = np.convolve(np.nan_to_num(cut) > 0, np.ones(5), mode="same") > 0  # +-1 s
        score = score + opts.w_cut * near
    card = card_score(sig, opts)
    if card is not None and opts.w_card > 0:
        score = score * (1.0 - opts.w_card * card)
        comps["video.card"] = card
    if opts.edge_s > 0 and opts.edge_factor < 1.0:
        t = sig.t0 + np.arange(n) * sig.hop_s
        edge = (t < opts.edge_s) | (t > sig.duration_s - opts.edge_s)
        weak = edge & (agree < opts.edge_agree)
        score = np.where(weak, score * opts.edge_factor, score)
    comps["agree"] = agree
    return np.clip(score, 0.0, 1.0), comps


def smooth(score: np.ndarray, hop_s: float, sigma_s: float) -> np.ndarray:
    from scipy.ndimage import gaussian_filter1d

    sigma = sigma_s / hop_s
    return gaussian_filter1d(score, sigma=sigma, mode="nearest") if sigma > 0 else score


def find_peaks(sm: np.ndarray, hop_s: float, opts: ScoringOptions) -> tuple[np.ndarray, np.ndarray]:
    from scipy.signal import find_peaks as _fp

    if sm.size == 0 or float(sm.max()) <= 0:
        return np.zeros(0, dtype=int), np.zeros(0)
    distance = max(1, math.ceil(opts.min_gap_s / hop_s))
    # floor only: prominence + distance do the real selection. A high percentile floor
    # drops short bursts once sustained events (motion) add mass to the distribution.
    height = max(opts.min_height, float(np.percentile(sm, opts.height_pct)))
    idx, props = _fp(sm, height=height, prominence=opts.prominence, distance=distance, wlen=240)
    return idx, props.get("prominences", np.zeros(len(idx)))


def active_span(sm: np.ndarray, p: int, frac: float, gap: int) -> tuple[int, int]:
    """Indices [a, b] around peak p where sm >= frac * sm[p], tolerating `gap` low samples."""
    thr = frac * sm[p]
    a = p
    low = 0
    while a - 1 >= 0:
        if sm[a - 1] >= thr:
            low = 0
        else:
            low += 1
            if low > gap:
                break
        a -= 1
    a += min(low, a)
    b = p
    low = 0
    while b + 1 < sm.size:
        if sm[b + 1] >= thr:
            low = 0
        else:
            low += 1
            if low > gap:
                break
        b += 1
    b -= min(low, sm.size - 1 - b)
    return a, b


def make_window(
    peak_t: float,
    span: tuple[float, float],
    min_s: float,
    max_s: float,
    duration: float,
    lead_frac: float,
    pad_s: float = 10.0,
) -> tuple[float, float]:
    span_len = max(0.0, span[1] - span[0])
    d = float(np.clip(span_len + pad_s, min_s, max_s))
    d = min(d, duration)
    if span_len >= d:  # span longer than the clip: centre the clip on the peak 60/40
        start = peak_t - lead_frac * d
    else:
        start = span[0] - lead_frac * (d - span_len)
    start = max(0.0, min(start, duration - d))
    return start, start + d


def _quiet_index(rms: np.ndarray, lo: int, hi: int) -> int | None:
    lo, hi = max(0, lo), min(rms.size - 1, hi)
    if hi < lo:
        return None
    seg = rms[lo : hi + 1]
    return lo + int(np.argmin(seg))


def snap_window(
    start: float,
    end: float,
    peak_t: float,
    sig: Signals,
    min_s: float,
    max_s: float,
) -> tuple[float, float, dict]:
    """Snap start to a quiet point/cut in [start-2, start+0.5], end in [end-0.5, end+2]."""
    rms = sig.arrays.get("audio.rms_db")
    cut = sig.arrays.get("video.cut")
    hop = sig.hop_s
    info = {"start": "none", "end": "none", "moved_s": 0.0}
    new_start, new_end = start, end

    def pick(lo_t: float, hi_t: float) -> tuple[float, str] | None:
        lo, hi = sig.index_of(lo_t), sig.index_of(hi_t)
        if cut is not None and cut.size == sig.n:
            cuts = np.nonzero(cut[lo : hi + 1] > 0)[0]
            if cuts.size:
                return sig.t0 + (lo + int(cuts[0])) * hop, "cut"
        if rms is not None and rms.size == sig.n:
            q = _quiet_index(rms, lo, hi)
            if q is not None:
                return sig.t0 + q * hop, "quiet"
        return None

    got = pick(start - 2.0, start + 0.5)
    if got and got[0] < peak_t:
        new_start, info["start"] = got[0], got[1]
    got = pick(end - 0.5, end + 2.0)
    if got and got[0] > peak_t:
        t_end = got[0] + hop  # end of that window
        new_end, info["end"] = t_end, got[1]
    d = new_end - new_start
    if d < min_s or d > max_s or new_start >= peak_t or new_end <= peak_t:
        return start, end, {"start": "none", "end": "none", "moved_s": 0.0}
    new_end = min(new_end, sig.duration_s)
    info["moved_s"] = round(abs(new_start - start) + abs(new_end - end), 3)
    return new_start, new_end, info


def dedupe(
    cands: list[Candidate], overlap_frac: float, count: int, min_score: float = 0.0
) -> list[Candidate]:
    kept: list[Candidate] = []
    for c in sorted(cands, key=lambda c: c.score, reverse=True):
        if c.score < min_score:
            break
        ok = True
        for k in kept:
            if k.start <= c.peak_t <= k.end or c.start <= k.peak_t <= c.end:
                ok = False
                break
            ov = min(c.end, k.end) - max(c.start, k.start)
            shorter = min(c.duration_s, k.duration_s)
            if ov > 0 and shorter > 0 and ov / shorter > overlap_frac:
                ok = False
                break
        if ok:
            kept.append(c)
        if len(kept) >= count:
            break
    return kept


def select_candidates(
    sig: Signals,
    opts: ScoringOptions,
    count: int,
    min_s: float,
    max_s: float,
) -> tuple[list[Candidate], int, np.ndarray]:
    """Full chain -> (top candidates by score, candidate count before NMS, smoothed score)."""
    score, comps = action_score(sig, opts)
    sm = smooth(score, sig.hop_s, opts.smooth_sigma_s)
    idx, prom = find_peaks(sm, sig.hop_s, opts)
    gap = max(1, int(2.0 / sig.hop_s))
    cands: list[Candidate] = []
    for cid, (p, pr) in enumerate(zip(idx.tolist(), prom.tolist(), strict=True)):
        peak_t = sig.t0 + p * sig.hop_s + sig.hop_s / 2
        a, b = active_span(sm, p, opts.span_frac, gap)
        span = (sig.t0 + a * sig.hop_s, sig.t0 + (b + 1) * sig.hop_s)
        start, end = make_window(peak_t, span, min_s, max_s, sig.duration_s, opts.lead_frac)
        start, end, snap = snap_window(start, end, peak_t, sig, min_s, max_s)
        # smoothed value for ordering plus the raw value at the peak: a 1 s burst must not
        # be flattened below the floor by the smoothing alone
        c_score = 0.5 * float(sm[p]) + 0.5 * float(score[p])
        components = {k.split(".", 1)[-1]: round(float(v[p]), 4) for k, v in comps.items()}
        features = {k: round(float(v[p]), 4) for k, v in sig.arrays.items() if v.size == sig.n}
        cands.append(
            Candidate(
                id=cid,
                peak_t=round(peak_t, 3),
                score=round(c_score, 4),
                prominence=round(float(pr), 4),
                components=components,
                start=round(start, 3),
                end=round(end, 3),
                snap=snap,
                features=features,
            )
        )
    top = dedupe(cands, opts.overlap_frac, count + 1, opts.min_score)
    if len(top) > 1:
        # a clip from 0:00 is usually the intro: keep it only when it clearly dominates
        med = float(np.median([c.score for c in top]))
        top = [c for c in top if c.start > 0.0 or c.score >= opts.zero_start_ratio * med]
    return top[:count], len(cands), sm
