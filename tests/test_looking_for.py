"""10-01: the brief (`--ai-brief`), presets / chips, and the extra signals (voice reaction,
stinger, fade, streak merge). Stub providers only; synthetic signals only."""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
import pytest

from clip_anything import ai
from clip_anything.ai_prompts import clip_prompt
from clip_anything.audio_signals import Signals, extract_audio
from clip_anything.config import PRESETS, Options, ScoringOptions, preset_layer
from clip_anything.errors import InputError
from clip_anything.report import Clip, Report
from clip_anything.scoring import Candidate, select_candidates, snap_window, streak_chain
from clip_anything.video_signals import extract_video

HOP = 0.5

# ---------------------------------------------------------------- signals


def _pcm(x: np.ndarray) -> bytes:
    return (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()


def test_voice_react_fires_on_laughter_like_burst_not_gunfire():
    sr = 16000
    t = np.arange(sr * 20) / sr
    x = 0.003 * np.random.default_rng(1).standard_normal(t.size)
    m = (t > 5) & (t < 7)  # 5 Hz amplitude-modulated harmonic tone, like "ha-ha-ha"
    env = 0.5 * (1 + np.sin(2 * np.pi * 5 * t[m]))
    x[m] += 0.5 * env * sum(np.sin(2 * np.pi * 180 * k * t[m]) / k for k in range(1, 9))
    m2 = (t > 10) & (t < 11)  # broadband bursts at 12 Hz, like automatic fire
    gate = np.sin(2 * np.pi * 12 * t[m2]) > 0.5
    x[m2] += 0.6 * np.random.default_rng(0).standard_normal(int(m2.sum())) * gate
    arrays = extract_audio([_pcm(x)], sr, HOP, 1.0, 60.0, 20.0)
    vr = arrays["audio.voice_react"]
    assert vr[10:14].max() > 0.7, "laughter-like burst"
    assert vr[20:22].max() < 0.1, "gunfire"
    assert vr[:8].max() == 0 and vr[26:].max() == 0


def test_stinger_is_a_tonal_level_jump():
    sr = 16000
    t = np.arange(sr * 10) / sr
    x = 0.002 * np.random.default_rng(2).standard_normal(t.size)
    m = (t > 4) & (t < 5.5)  # clean chord hit
    x[m] += 0.5 * (np.sin(2 * np.pi * 440 * t[m]) + np.sin(2 * np.pi * 660 * t[m]))
    m2 = (t > 7) & (t < 7.5)  # noise burst of the same level: not a stinger
    x[m2] += 0.5 * np.random.default_rng(3).standard_normal(int(m2.sum()))
    arrays = extract_audio([_pcm(x)], sr, HOP, 1.0, 60.0, 10.0)
    st = arrays["audio.stinger"]
    assert st[7:9].max() > 0.5
    assert st[14:16].max() < 0.2


def _frames(n_s: float, fps: int = 5, w: int = 320, h: int = 180, black=()):
    rng = np.random.default_rng(0)
    base = rng.integers(60, 200, (h, w)).astype(np.uint8)
    out = []
    for i in range(int(n_s * fps)):
        f = np.clip(base.astype(int) + rng.integers(-3, 4, (h, w)), 0, 255).astype(np.uint8)
        if any(a <= i / fps < b for a, b in black):
            f[:] = 0
        out.append(f)
    return np.stack(out)


def test_fade_only_for_a_short_black_between_lit_frames():
    arr = _frames(40, black=[(10.0, 11.0), (25.0, 35.0)])  # a fade, then a long black
    out = extract_video([arr.tobytes()], 5, HOP, 320, 180, 40.0)
    fade, black = out["video.fade"], out["video.black"]
    assert fade[20] == 1.0 and fade.sum() == 1.0, "one fade at 10 s"
    assert black[20:22].all() and black[50:70].all()


# ---------------------------------------------------------------- scoring


def _signals(duration=300.0, spikes=(), black=(), soft=()):
    """`spikes` = sharp loud bursts (level + onset); `soft` = level only, weaker bursts."""
    rng = np.random.default_rng(1)
    n = int(duration / HOP)
    rms = -40 + 0.3 * rng.standard_normal(n)
    onset = np.abs(0.002 * rng.standard_normal(n))
    for t, db in spikes:
        i = int(t / HOP)
        rms[i : i + 2] += db
        onset[i] += 1.5
    for t, db in soft:
        i = int(t / HOP)
        rms[i : i + 2] += db
    blk = np.zeros(n, np.float32)
    for a, b in black:
        blk[int(a / HOP) : int(b / HOP)] = 1.0
    arrays = {
        "audio.rms_db": rms.astype(np.float32),
        "audio.onset": onset.astype(np.float32),
        "audio.flux": onset.astype(np.float32),
        "audio.loud_rel": (rms - np.median(rms)).astype(np.float32),
        "video.black": blk,
    }
    return Signals(hop_s=HOP, t0=0.0, n=n, duration_s=duration, arrays=arrays)


def test_streak_merges_bursts_into_one_longer_clip():
    # one sharp peak with four weaker bursts 12-13 s to each side = one streak that needs
    # more than 45 s; a lone burst far away stays its own 15-45 s clip
    sig = _signals(
        spikes=[(100.0, 18), (250.0, 18)],
        soft=[(75.0, 6), (88.0, 6), (112.0, 6), (125.0, 6)],
    )
    opts = ScoringOptions(min_evidence=0.0)
    top, _, _ = select_candidates(sig, opts, 5, 15, 45)
    streak = [c for c in top if c.components.get("streak")]
    assert len(streak) == 1 and streak[0].components["streak"] >= 4, streak
    c = streak[0]
    assert c.start <= 88.0 and c.end >= 112.0, (c.start, c.end)
    assert 45 < c.duration_s <= 60 and c.snap["streak"] == c.components["streak"]
    lone = [c for c in top if abs(c.peak_t - 250.0) < 2]
    assert lone and lone[0].duration_s <= 45 and "streak" not in lone[0].components
    # no streak merge: the same three bursts give separate windows, none longer than --max
    off = ScoringOptions(min_evidence=0.0, streak_gap_s=0.0)
    top_off, _, _ = select_candidates(sig, off, 5, 15, 45)
    assert all(c.duration_s <= 45 for c in top_off)


def test_streak_chain_respects_gap_fraction_and_span():
    sm = np.zeros(400)
    peaks = [100, 130, 160, 190, 300]
    for p in peaks:
        sm[p] = 1.0
    sm[160] = 0.3  # too weak to join
    opts = ScoringOptions(streak_gap_s=20.0, streak_frac=0.6, streak_max_s=60.0)
    assert streak_chain(sm, 100, np.array(peaks), HOP, opts) == [100, 130]  # 160 weak -> stop
    sm[160] = 1.0
    chain = streak_chain(sm, 100, np.array(peaks), HOP, opts)
    assert chain == [100, 130, 160, 190]  # 300 is 55 s away
    opts.streak_max_s = 40.0  # chain span capped at 30 s
    assert streak_chain(sm, 100, np.array(peaks), HOP, opts) == [100, 130, 160]


def test_fade_to_black_is_the_preferred_clip_end():
    sig = _signals(duration=200.0, black=[(121.0, 122.0)])
    start, end, info = snap_window(90.0, 120.0, 100.0, sig, 15, 45)
    assert info["end"] == "fade" and abs(end - 121.0) < HOP + 1e-6 and start < 100.0


def test_preset_layer_and_unknown_preset():
    opts = Options.from_layers(preset_layer("funny"))
    assert opts.scoring.preset == "funny" and opts.scoring.w_voice == PRESETS["funny"]["w_voice"]
    assert Options.from_layers(preset_layer("")).scoring.preset == ""
    with pytest.raises(InputError):
        preset_layer("nope")
    # CLI layer still wins over the preset
    opts = Options.from_layers(preset_layer("horror"), {"scoring": {"min_evidence": 0.9}})
    assert opts.scoring.min_evidence == 0.9 and opts.scoring.lead_frac == 0.75


# ---------------------------------------------------------------- the brief


def test_prompt_carries_the_brief_and_asks_for_match():
    p = clip_prompt(None, True, "action score 0.5 of 1", brief='funny "fails"')
    assert "funny 'fails'" in p and '"match"' in p and '"matches"' in p
    plain = clip_prompt(None, True, "action score 0.5 of 1")
    assert "match" not in plain
    text_only = clip_prompt("no way", False, "", brief="clutch plays")
    assert '"match"' in text_only and '"score"' not in text_only


def test_parse_reply_match():
    r = ai.parse_reply('{"title": "Big Fall", "match": 8, "matches": "he trips"}', False, True)
    assert r.match == 8 and r.matches == "he trips" and r.error is None
    r = ai.parse_reply('{"title": "Big Fall"}', False, True)
    assert r.error == "no numeric match"
    r = ai.parse_reply('{"title": "Big Fall", "match": 8}', False, False)
    assert r.match is None and r.error is None


class _FakeProvider(ai.Provider):
    """Text-only provider: rates the match from a word in the prompt's action hint."""

    name = "fake"
    model = "fake-1"
    vision = False

    def __init__(self, matches: dict[str, float]):
        self.matches = matches
        self.prompts: list[str] = []

    def ask(self, prompt: str, frames: list[bytes]) -> ai.Reply:
        self.prompts.append(prompt)
        if not self.need_match:
            return ai.Reply(title="Plain Title", hook="h")
        for key, m in self.matches.items():
            if key in prompt:
                return ai.Reply(title=f"Match {key}", match=m, matches=f"{key} happens")
        return ai.Reply(title="None", match=1.0, matches="")


@dataclass
class _Info:
    path: str = "/nonexistent/video.mp4"


def _cands():
    return [
        Candidate(
            id=i,
            peak_t=100.0 * (i + 1),
            score=s,
            prominence=0.5,
            components={},
            start=90.0 * (i + 1),
            end=90.0 * (i + 1) + 30,
        )
        for i, s in enumerate((0.9, 0.6, 0.5))
    ]


def test_brief_reranks_by_match_and_lands_in_report():
    cands = _cands()
    provider = _FakeProvider({"0.50 of 1": 9.0, "0.60 of 1": 5.0, "0.90 of 1": 1.0})
    rr = ai.Reranker(provider, "ffmpeg", brief="  funny   fails ")
    assert rr.widen == 5 and rr.brief == "funny fails" and rr.weight == ai.BRIEF_WEIGHT
    report = Report(input={}, options={})
    out = rr(cands, _Info(), report, {})
    assert all("funny fails" in p for p in provider.prompts)
    assert [c.id for c in out] == [2, 0, 1] or [c.id for c in out][0] == 2
    assert out[0].features["ai"]["match"] == 9.0
    assert out[0].features["ai"]["matches"] == "0.50 of 1 happens"
    assert out[0].components["match"] == pytest.approx(8 / 9, abs=1e-3)
    assert report.ai["brief"] == "funny fails" and report.ai["reranked"] is True
    assert rr.outcome.status == "ok"
    assert "Matches:" in ai.sidecar_text(
        Clip(
            rank=1, candidate_id=2, start=0, end=1, duration_s=1, score=1, ai=out[0].features["ai"]
        )
    )


def test_empty_brief_keeps_the_old_behaviour():
    cands = _cands()
    provider = _FakeProvider({})
    rr = ai.Reranker(provider, "ffmpeg", brief="")
    assert rr.widen == 3 and rr.weight == ai.AI_WEIGHT and rr.max_items == ai.MAX_ITEMS
    report = Report(input={}, options={})
    out = rr(cands, _Info(), report, {})
    assert [c.id for c in out] == [0, 1, 2]  # text model, no brief: titles only, no re-rank
    assert all("match" not in p for p in provider.prompts)
    assert "match" not in out[0].features["ai"] and report.ai["brief"] is None
    assert json.dumps(report.to_dict())  # serialisable


# ---------------------------------------------------------------- app request + reason line


def test_job_request_brief_and_preset(tmp_path):
    from clip_anything.app.jobs import JobRequest, why_line

    f = tmp_path / "v.mp4"
    f.write_bytes(b"x")
    req = JobRequest.from_json(
        {"inputs": [str(f)], "out_dir": str(tmp_path), "preset": " Funny ", "brief": " a  b " * 200}
    )
    assert req.preset == "funny" and req.problem() is None and len(req.brief) == 300
    assert req.options().scoring.preset == "funny"
    bad = JobRequest.from_json({"inputs": [str(f)], "out_dir": str(tmp_path), "preset": "x"})
    assert bad.problem() == "Unknown preset."
    clip = Clip(
        rank=1,
        candidate_id=0,
        start=0,
        end=20,
        duration_s=20,
        score=0.7,
        components={"loud_rel": 0.5, "voice_react": 0.8, "agree": 0.6, "fade": 1.0},
    )
    assert (
        why_line(clip) == "A loud burst and a voice reaction at the same time, then a fade to black"
    )
    clip = Clip(
        rank=1,
        candidate_id=0,
        start=0,
        end=20,
        duration_s=20,
        score=0.7,
        components={"motion": 0.6, "streak": 3.0},
    )
    assert why_line(clip) == "Fast motion and 3 bursts in a row"


def test_cli_rejects_unknown_preset(tmp_path):
    from typer.testing import CliRunner

    from clip_anything.cli import app

    res = CliRunner().invoke(app, [str(tmp_path / "v.mp4"), "--preset", "nope", "--dry-run"])
    assert res.exit_code == 2 and "unknown preset" in (res.output + str(res.exception))
