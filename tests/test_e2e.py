import json
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
    opts = Options.from_layers(
        {
            "clips": {"count": 6},
            "scoring": {"w_motion": 0.0},
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
    env = {"PATH": str(tmp_path), "HOME": str(tmp_path)}
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
