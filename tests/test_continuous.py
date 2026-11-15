"""10-02: continuous recordings (racing, sports) - detection, the continuous profile and the
never-empty fallback."""

from __future__ import annotations

import json

import numpy as np

from clip_anything.audio_signals import Signals
from clip_anything.config import Options, ScoringOptions, preset_layer
from clip_anything.pipeline import run
from clip_anything.scoring import continuity, continuous_components, select_candidates

HOP = 0.5


def _drone_file(duration=900.0, jolts=(), impacts=(), seed=5) -> Signals:
    """Raw signals of a racing-like recording: a flat loud drone (rms MAD ~0.3 dB, no onsets),
    whole-frame motion around 14 all the time; a jolt = the motion drops by 85 % for 2 s; an
    impact = the 3-8 kHz band jumps 12 dB for one window."""
    rng = np.random.default_rng(seed)
    n = int(duration / HOP)
    rms = -26 + 0.4 * rng.standard_normal(n)
    onset = np.abs(0.01 * rng.standard_normal(n))
    motion = 14 + 1.5 * rng.standard_normal(n)
    still = np.full(n, 0.3) + 0.02 * rng.standard_normal(n)
    hi = -40 + 0.5 * rng.standard_normal(n)
    for t in jolts:
        i = int(t / HOP)
        motion[i : i + 4] = 2.0
    for t in impacts:
        i = int(t / HOP)
        hi[i] += 12.0
        rms[i] += 1.0
    arrays = {
        "audio.rms_db": rms.astype(np.float32),
        "audio.onset": onset.astype(np.float32),
        "audio.loud_rel": (rms - np.median(rms)).astype(np.float32),
        "audio.hi_db": hi.astype(np.float32),
        "video.motion": motion.astype(np.float32),
        "video.still": still.astype(np.float32),
        "video.cspread": np.full(n, 0.2, np.float32),
        "video.cut": np.zeros(n, np.float32),
    }
    return Signals(hop_s=HOP, t0=0.0, n=n, duration_s=duration, arrays=arrays)


def test_continuity_detects_a_drone_file_and_not_a_bursty_one():
    opts = ScoringOptions()
    cont = continuity(_drone_file(), opts)
    assert cont["continuous"] and cont["rms_mad_db"] < 1.0 and cont["motion_frac"] > 0.9
    # the same file with gunfire-like bursts every 5 s is an ordinary recording
    sig = _drone_file()
    for t in range(5, 895, 5):
        i = int(t / HOP)
        sig.arrays["audio.rms_db"][i : i + 2] += 15
        sig.arrays["audio.onset"][i] = 1.0
    assert not continuity(sig, opts)["continuous"]
    # a quiet static game (menus) is not continuous either: nothing moves
    sig = _drone_file()
    sig.arrays["video.motion"][:] = 1.0
    assert not continuity(sig, opts)["continuous"]


def test_jolt_and_impact_fire_only_inside_moving_stretches():
    opts = ScoringOptions()
    sig = _drone_file(jolts=[300.0], impacts=[300.5, 600.0])
    # a menu (static card) from 580 s to 620 s: the impact at 600 s lands on a card
    i0, i1 = int(580 / HOP), int(620 / HOP)
    sig.arrays["video.motion"][i0:i1] = 0.5
    sig.arrays["video.still"][i0:i1] = 0.97
    cc = continuous_components(sig, opts)
    j, imp = cc["video.jolt"], cc["audio.impact"]
    assert j[int(300 / HOP)] > 0.9 and imp[int(300.5 / HOP)] > 0.9
    assert imp[int(600 / HOP)] == 0.0 and cc["drive"][int(600 / HOP)] == 0.0
    assert float(np.sum(j > 0.3)) <= 6  # the jolt and nothing else


def test_continuous_profile_ranks_the_jolts_and_reports_it():
    jolts = [100.0, 250.0, 400.0, 550.0, 700.0]
    sig = _drone_file(jolts=jolts, impacts=[t + 0.5 for t in jolts[:3]])
    info: dict = {}
    top, _, _ = select_candidates(sig, ScoringOptions(), 5, 15, 45, info=info)
    assert info["profile"] == "continuous" and not info["fallback"]
    got = sorted(c.peak_t for c in top)
    assert len(got) == 5 and all(abs(g - t) < 4.0 for g, t in zip(got, jolts, strict=True))
    # a jolt with an impact sound carries both components; a silent one only the jolt
    with_sound = [c for c in top if c.peak_t < 450]
    assert all(c.components["ev_audio"] > 0.5 and c.components["jolt"] > 0.5 for c in with_sound)
    # forcing the standard profile on the same file finds nothing above the bar
    info = {}
    select_candidates(sig, ScoringOptions(profile="standard"), 5, 15, 45, info=info)
    assert info["profile"] == "standard" and info["cleared_bar"] == 0


def test_racing_preset_forces_the_continuous_profile():
    layer = preset_layer("racing")
    assert layer["scoring"]["profile"] == "continuous"
    opts = Options.from_layers(layer).scoring
    sig = _drone_file()
    for t in range(5, 895, 5):  # bursty audio: auto would say standard
        sig.arrays["audio.onset"][int(t / HOP)] = 1.0
        sig.arrays["audio.rms_db"][int(t / HOP)] += 15
    info: dict = {}
    select_candidates(sig, opts, 5, 15, 45, info=info)
    assert info["profile"] == "continuous"


def test_continuous_fixture_end_to_end(synth_continuous_video, tmp_path):
    truth = json.loads((synth_continuous_video.parent / "synth_continuous.json").read_text())
    opts = Options.from_layers(
        {
            "clips": {"count": 5},
            "render": {"out_dir": str(tmp_path), "dry_run": True},
            "speech": {"captions": False},
            "analysis": {"cache": False},
        }
    )
    report = run(synth_continuous_video, opts)
    assert report.scoring["profile"] == "continuous", report.scoring
    assert len(report.clips) == 5
    for j in truth["jolts"]:
        assert any(c.start <= j["t"] + 1.0 <= c.end for c in report.clips), (j, report.clips)
    assert not any(w.code == "below_bar_fallback" for w in report.warnings)
    assert all(c.components["jolt"] > 0.5 for c in report.clips)


def test_plain_fixture_is_still_standard(synth_video, tmp_path):
    opts = Options.from_layers(
        {
            "clips": {"count": 6},
            "render": {"out_dir": str(tmp_path), "dry_run": True},
            "speech": {"captions": False},
            "analysis": {"cache": False},
        }
    )
    report = run(synth_video, opts)
    assert report.scoring["profile"] == "standard"
    assert not report.scoring["fallback"]


def test_fallback_returns_strongest_moments_with_a_warning(synth_lobby_video, tmp_path):
    # two real events + static cards, 5 asked: the cards never come back (never a card),
    # the two events do, and the report says the bar was not the ranking
    opts = Options.from_layers(
        {
            "clips": {"count": 5},
            "render": {"out_dir": str(tmp_path), "dry_run": True},
            "speech": {"captions": False},
            "analysis": {"cache": False},
        }
    )
    report = run(synth_lobby_video, opts)
    truth = json.loads((synth_lobby_video.parent / "synth_lobby.json").read_text())
    for c in report.clips:
        for card in truth["cards"]:
            assert c.end <= card["start"] or c.start >= card["end"]
    codes = {w.code for w in report.warnings}
    assert ("below_bar_fallback" in codes) == report.scoring["fallback"]
    assert "no_peaks" not in codes
