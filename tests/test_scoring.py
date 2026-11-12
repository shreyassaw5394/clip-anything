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


# --- absolute bar (02-04): evidence against fixed reference levels, not the file's own scale


def _real_like(duration=600.0, events=(), silent=False, seed=3):
    """Raw signals in real-footage units: quiet gameplay with `events` = (t, kind) where kind
    is 'both' (gunfire + whole-frame motion), 'audio' (shot on a still screen), 'motion'
    (camera pan, nothing to hear) or 'menu' (click + a small animated region)."""
    rng = np.random.default_rng(seed)
    n = int(duration / HOP)
    rms = -30 + 0.5 * rng.standard_normal(n)
    onset = np.abs(0.01 * rng.standard_normal(n))
    motion = 6 + 1.0 * rng.standard_normal(n)
    still = np.full(n, 0.6) + 0.02 * rng.standard_normal(n)
    spread = np.full(n, 0.2)
    for t, kind in events:
        i = int(t / HOP)
        if kind in ("both", "audio"):
            rms[i : i + 2] += 15
            onset[i] += 1.0
        if kind == "audio":  # a shot while aiming at a wall: nothing moves
            motion[i - 6 : i + 7] = 1.0
            still[i - 6 : i + 7] = 0.95
        if kind in ("both", "motion"):
            motion[i - 6 : i + 7] = 35
            still[i - 6 : i + 7] = 0.1
        if kind == "menu":  # a click (sharp, not loud) and a small animated region
            rms[i : i + 2] += 6
            onset[i] += 0.6
            motion[i - 6 : i + 7] = 14
            still[i - 6 : i + 7] = 0.75
    if silent:
        rms[:] = -60
        onset[:] = 0
    loud = rms - np.median(rms)
    arrays = {
        "audio.rms_db": rms.astype(np.float32),
        "audio.onset": onset.astype(np.float32),
        "audio.loud_rel": loud.astype(np.float32),
        "video.motion": motion.astype(np.float32),
        "video.still": still.astype(np.float32),
        "video.cspread": spread.astype(np.float32),
    }
    return Signals(hop_s=HOP, t0=0.0, n=n, duration_s=duration, arrays=arrays)


def _ev_at(sig, t, opts=None):
    _, comps = action_score(sig, opts or ScoringOptions())
    return float(comps["evidence"][int(t / HOP)])


def test_evidence_needs_audio_and_motion():
    sig = _real_like(events=[(100.0, "both"), (200.0, "audio"), (300.0, "motion"), (400.0, "menu")])
    opts = ScoringOptions()
    both, audio, motion, menu = (_ev_at(sig, t, opts) for t in (100.0, 200.0, 300.0, 400.0))
    assert both >= opts.min_evidence
    # one group alone never clears the bar on its own (quiet background adds a few %)
    assert audio < opts.min_evidence + 0.1 and motion <= opts.lone_cap + 1e-6
    # a click on a mostly static screen is far below a firefight and below the bar
    assert menu < both - 0.3 and menu < opts.min_evidence
    assert _ev_at(sig, 500.0, opts) < 0.1


def test_bar_filters_candidates_and_zero_disables_it():
    sig = _real_like(events=[(100.0, "both"), (200.0, "audio"), (300.0, "motion"), (400.0, "menu")])
    top, total, _ = select_candidates(sig, ScoringOptions(), count=10, min_s=15, max_s=45)
    assert total >= 2
    assert len(top) == 1 and abs(top[0].peak_t - 100.0) < 2.0
    assert all(c.components["evidence"] >= 0.5 for c in top)
    top, _, _ = select_candidates(
        sig, ScoringOptions(min_evidence=0.0), count=10, min_s=15, max_s=45
    )
    assert len(top) >= 2  # file-relative ranking: the lone-signal moments come back


def test_silent_file_keeps_motion_only_moments():
    # no audio evidence exists at all: nothing to agree with, so the bar stands down and the
    # file is ranked against itself
    sig = _real_like(events=[(100.0, "motion"), (300.0, "motion")], silent=True)
    opts = ScoringOptions()
    assert _ev_at(sig, 100.0, opts) > opts.lone_cap
    top, _, _ = select_candidates(sig, opts, count=5, min_s=15, max_s=45)
    assert len(top) >= 2
    assert all(
        abs(c.peak_t - t) < 3.0
        for c, t in zip(sorted(top[:2], key=lambda c: c.peak_t), (100.0, 300.0), strict=True)
    )
