import json
import os
import subprocess
import sys

import pytest

from clip_anything.config import Options
from clip_anything.pipeline import run


def _covering(report, t):
    return [c for c in report.clips if c.start <= t <= c.end]


def _assert_all_bursts(report, truth):
    for b in truth["audio_bursts"]:
        hits = _covering(report, b["t"])
        assert hits, f"burst at {b['t']}s not inside any of the top clips"
        for c in hits:
            assert 15.0 - 1e-6 <= c.duration_s <= 45.0 + 1e-6
            # build-up: the burst sits in the later part of the clip, never at its start
            assert b["t"] - c.start >= 3.0


def test_dry_run_finds_all_audio_bursts(synth_video, synth_truth, tmp_path):
    opts = Options.from_layers(
        {
            "clips": {"count": 6},
            "render": {"out_dir": str(tmp_path), "dry_run": True},
            "analysis": {"cache": False},
        }
    )
    report = run(synth_video, opts)
    assert len(report.clips) == 6
    _assert_all_bursts(report, synth_truth)
    data = json.loads((tmp_path / "report.json").read_text())
    assert data["schema_version"] == 1 and len(data["clips"]) == 6
    assert data["clips"][0]["components"]["loud_rel"] > 0.5
    assert "video.motion" in data["signals"]["names"] and "video.cx" in data["signals"]["names"]


def _motion_hits(report, truth):
    return [b for b in truth["motion_bursts"] if _covering(report, b["t"] + b["dur"] / 2)]


def test_music_bed_still_finds_bursts(synth_music_video, synth_truth, tmp_path):
    # audio path alone (motion weight off): the bed must not hide the bursts
    # the synthetic square moves 5 % of a static frame: by design it sits below the
    # real-footage action bar (02-04), so these ranking tests run with the bar off
    opts = Options.from_layers(
        {
            "clips": {"count": 6},
            "scoring": {"w_motion": 0.0, "min_evidence": 0.0},
            "render": {"out_dir": str(tmp_path), "dry_run": True},
            "analysis": {"cache_dir": str(tmp_path / "cache")},
        }
    )
    report = run(synth_music_video, opts)
    _assert_all_bursts(report, synth_truth)
    # full scoring: motion bursts win over bed-masked audio (events sit < 30 s apart, so the
    # min-gap rule keeps only one of each neighbouring pair); the lone burst at 172 s survives
    opts = Options.from_layers(
        {
            "clips": {"count": 10},
            "scoring": {"min_evidence": 0.0},
            "render": {"out_dir": str(tmp_path), "dry_run": True},
            "analysis": {"cache_dir": str(tmp_path / "cache")},
        }
    )
    report = run(synth_music_video, opts)
    assert len(_motion_hits(report, synth_truth)) == 4
    assert _covering(report, 172.0)


def test_quiet_audio_picks_motion_bursts(synth_quiet_video, synth_truth, tmp_path):
    opts = Options.from_layers(
        {
            "clips": {"count": 4},
            "scoring": {"min_evidence": 0.0},  # 5 % square: below the real-footage bar
            "render": {"out_dir": str(tmp_path), "dry_run": True},
            "analysis": {"cache": False},
        }
    )
    report = run(synth_quiet_video, opts)
    assert len(report.clips) == 4
    assert len(_motion_hits(report, synth_truth)) == 4
    for c in report.clips:
        assert c.components["motion"] > 0.5
        assert c.components.get("loud_rel", 0.0) < 0.1
    assert [s.status for s in report.stages if s.name in ("audio", "video")] == ["ok", "ok"]


def test_signal_cache_roundtrip(synth_video, tmp_path):
    cache_dir = tmp_path / "cache"
    opts = Options.from_layers(
        {
            "clips": {"count": 6},
            "render": {"out_dir": str(tmp_path), "dry_run": True},
            "analysis": {"cache_dir": str(cache_dir)},
        }
    )
    r1 = run(synth_video, opts)
    r2 = run(synth_video, opts)
    assert [s.status for s in r1.stages if s.name == "audio"] == ["ok"]
    assert [s.status for s in r2.stages if s.name == "audio"] == ["cached"]
    assert [(c.start, c.end) for c in r1.clips] == [(c.start, c.end) for c in r2.clips]


def test_cli_dry_run_json(synth_video, tmp_path):
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "clip_anything.cli",
            str(synth_video),
            "--count",
            "3",
            "--dry-run",
            "--json",
            "--no-cache",
            "--out",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert len(data["clips"]) == 3


def test_cli_bad_input(tmp_path):
    res = subprocess.run(
        [sys.executable, "-m", "clip_anything.cli", str(tmp_path / "missing.mp4")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 2


def test_cli_ffmpeg_missing(tmp_path):
    env = {"PATH": str(tmp_path), "HOME": str(tmp_path), "CLIP_ANYTHING_EXTRA_PATHS": ""}
    for k in ("SYSTEMROOT", "USERPROFILE", "TEMP", "TMP"):  # Windows: python needs these
        if k in os.environ:
            env[k] = os.environ[k]
    res = subprocess.run(
        [sys.executable, "-m", "clip_anything.cli", "x.mp4"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert res.returncode == 3
    assert "ffmpeg" in res.stderr.lower()


@pytest.mark.parametrize("flag", ["--help"])
def test_help_is_light(flag):
    code = (
        "import sys, clip_anything.cli as c; "
        "assert 'scipy' not in sys.modules and 'cv2' not in sys.modules and "
        "'numpy' not in sys.modules"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def _dry(video, tmp_path, count):
    opts = Options.from_layers(
        {
            "clips": {"count": count},
            "render": {"out_dir": str(tmp_path), "dry_run": True},
            "speech": {"captions": False},
            "analysis": {"cache": False},
        }
    )
    return run(video, opts)


def test_lobby_cards_are_never_picked(synth_lobby_video, tmp_path):
    truth = json.loads((synth_lobby_video.parent / "synth_lobby.json").read_text())
    report = _dry(synth_lobby_video, tmp_path, count=5)
    # --count is a maximum: two real events, no filler from the silent or the loud-music card
    assert 1 <= len(report.clips) <= 2
    for c in report.clips:
        for card in truth["cards"]:
            assert c.end <= card["start"] or c.start >= card["end"], (c.start, c.end, card)
    for e in truth["events"]:
        assert _covering(report, e["t"] + 1.0)
    assert any(w.code == "below_floor" for w in report.warnings)


def test_agreement_ranks_audio_plus_motion_first(synth_agree_video, tmp_path):
    truth = json.loads((synth_agree_video.parent / "synth_agree.json").read_text())
    report = _dry(synth_agree_video, tmp_path, count=3)
    assert report.clips and report.clips[0].start <= truth["both"] <= report.clips[0].end
    both = report.clips[0]
    for c in report.clips[1:]:
        assert c.score < both.score
    assert both.components["agree"] > 0.8
