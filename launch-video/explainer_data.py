"""Export the real series behind a run for the explainer reel.

usage: uv run python launch-video/explainer_data.py <signals.npz> <report.json> <out.json>
Loads the cached signals, runs the library's own scoring on them (nothing re-implemented),
and writes downsampled 0..1 series: audio evidence, visual evidence, action score, the
static-card (menu/lobby) factor, the bar, and the picked spans from the report.
"""

from __future__ import annotations

import json
import sys

import numpy as np

from clip_anything.audio_signals import Signals
from clip_anything.scoring import ScoringOptions, action_score


def pool(a: np.ndarray, m: int, how: str = "mean") -> list[float]:
    """Pool to m points: mean for the dense traces, max for sparse spikes."""
    n = a.size
    edges = np.linspace(0, n, m + 1).astype(int)
    f = np.nanmax if how == "max" else np.nanmean
    out = [float(f(a[lo:hi])) if hi > lo else 0.0 for lo, hi in zip(edges[:-1], edges[1:])]
    return [round(x, 4) for x in out]


def main() -> int:
    npz, report, out = sys.argv[1:4]
    d = np.load(npz)
    arrays = {k: d[k] for k in d.files if k != "fingerprint"}
    n = int(next(iter(arrays.values())).size)
    hop = 0.5
    rep = json.load(open(report))
    duration = (
        float(rep["input"].get("duration_s") or n * hop)
        if isinstance(rep.get("input"), dict)
        else n * hop
    )
    sig = Signals(hop_s=hop, t0=0.0, n=n, duration_s=duration, arrays=arrays)
    opts = ScoringOptions()
    score, comps = action_score(sig, opts)
    m = 360
    ev_a = comps.get("ev_audio", np.zeros(n))
    ev_v = comps.get("ev_visual", np.zeros(n))
    ev = comps.get("evidence", np.zeros(n))
    card = comps.get("video.card", np.zeros(n))
    clips = [
        {
            "start": c["start"],
            "end": c["end"],
            "score": c["score"],
            "evidence": c["components"]["evidence"],
        }
        for c in rep["clips"]
    ]
    # one real menu/lobby bump: the loudest window that the card factor marks down
    loud = np.nan_to_num(comps.get("audio.loud_rel", np.zeros(n)))
    inner = (np.arange(n) > 0.05 * n) & (np.arange(n) < 0.95 * n)
    cand = np.where((card > 0.5) & inner)[0]
    if not cand.size:
        cand = np.where(card > 0.5)[0]
    bump = None
    if cand.size:
        i = int(cand[np.argmax(loud[cand])])
        bump = {"t": i * hop, "card": float(card[i]), "loud": float(loud[i])}
    json.dump(
        {
            "duration_s": duration,
            "hop_s": hop,
            "n": n,
            "points": m,
            "bar": opts.min_evidence,
            "audio": pool(np.nan_to_num(ev_a), m, "max"),
            "visual": pool(np.nan_to_num(ev_v), m),
            "evidence": pool(np.nan_to_num(ev), m),
            "score": pool(np.nan_to_num(score), m),
            "card": pool(np.nan_to_num(card), m, "max"),
            "clips": clips,
            "bump": bump,
            "candidates_total": rep.get("candidates_total"),
        },
        open(out, "w"),
    )
    print(
        f"wrote {out}: {n} windows -> {m} points, {len(clips)} clips, bar {opts.min_evidence}, bump {bump}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
