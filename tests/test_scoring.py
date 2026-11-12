import numpy as np

from clip_anything.audio_signals import Signals
from clip_anything.config import ScoringOptions
from clip_anything.scoring import (
    Candidate,
    action_score,
    dedupe,
    make_window,
    select_candidates,
)

HOP = 0.5


def _signals(duration=300.0, spikes=(), noise=0.3, seed=1, flat=False):
    rng = np.random.default_rng(seed)
    n = int(duration / HOP)
    rms = -40 + noise * rng.standard_normal(n)
    onset = np.abs(0.002 * rng.standard_normal(n))
    for t, db in spikes:
        i = int(t / HOP)
        rms[i : i + 2] += db
        onset[i] += 1.5
    if flat:
        rms[:] = -40
        onset[:] = 0
    loud = rms - np.median(rms)
    arrays = {
        "audio.rms_db": rms.astype(np.float32),
        "audio.onset": onset.astype(np.float32),
        "audio.flux": onset.astype(np.float32),
        "audio.loud_rel": loud.astype(np.float32),
    }
    return Signals(hop_s=HOP, t0=0.0, n=n, duration_s=duration, arrays=arrays)


def test_spikes_become_top_candidates():
    spikes = [(30.0, 18), (100.0, 15), (170.0, 20), (250.0, 12)]
    sig = _signals(spikes=spikes)
    top, total, _ = select_candidates(sig, ScoringOptions(), count=4, min_s=15, max_s=45)
    assert len(top) == 4
    got = sorted(c.peak_t for c in top)
    for (t, _), g in zip(spikes, got, strict=True):
        assert abs(g - t) < 1.5
    for c in top:
        assert 15 <= c.duration_s <= 45
        assert c.start < c.peak_t < c.end
        # build-up: more of the clip before the peak than after
        assert (c.peak_t - c.start) > (c.end - c.peak_t)


def test_flat_signal_yields_nothing():
    sig = _signals(flat=True)
    score, comps = action_score(sig, ScoringOptions())
    assert comps == {} and score.max() == 0
    top, total, _ = select_candidates(sig, ScoringOptions(), 5, 15, 45)
    assert top == [] and total == 0


def test_two_close_peaks_dedupe():
    sig = _signals(spikes=[(100.0, 18), (105.0, 17)])
    top, total, _ = select_candidates(sig, ScoringOptions(), 5, 15, 45)
    assert len(top) == 1


def test_clamp_at_edges():
    sig = _signals(duration=120.0, spikes=[(0.5, 18), (119.0, 18)])
    top, _, _ = select_candidates(sig, ScoringOptions(), 5, 15, 45)
    for c in top:
        assert c.start >= 0 and c.end <= 120.0 and c.duration_s >= 15


def test_make_window_60_40():
    s, e = make_window(100.0, (99.5, 100.5), 15, 45, 1000, 0.6)
    assert abs((e - s) - 15) < 1e-6
    assert abs((100.0 - s) / 15 - 0.6) < 0.05


def test_dedupe_overlap_rule():
    a = Candidate(0, 50, 0.9, 0.5, {}, 40, 70)
    b = Candidate(1, 80, 0.8, 0.5, {}, 65, 95)  # 5 s overlap of 30 -> 17%: keep
    c = Candidate(2, 62, 0.7, 0.5, {}, 55, 85)  # peak inside a -> drop
    assert [x.id for x in dedupe([a, b, c], 0.2, 10)] == [0, 1]
