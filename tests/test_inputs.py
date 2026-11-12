"""Inputs (02-03): folders and many files, short-clip collections, audio tracks, odd geometry,
containers/codecs, interrupted recordings, resume after an abort."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from clip_anything import pipeline
from clip_anything.config import Options
from clip_anything.errors import InputError
from clip_anything.inputs import discover
from clip_anything.pipeline import run
from clip_anything.probe import preflight, probe

try:
    import resource  # POSIX only; used by the opt-in 3 h test
except ImportError:  # pragma: no cover - Windows
    resource = None

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from make_input_fixtures import EncoderMissing  # noqa: E402
from make_input_fixtures import ensure as _ensure  # noqa: E402


def ensure(root, variant):
    try:
        return _ensure(root, variant)
    except EncoderMissing as exc:
        pytest.skip(str(exc))

FIX = ROOT / "tests" / "fixtures"
QUIET = {"speech": {"captions": False}}


def _opts(out: Path, count: int = 3, dry: bool = True, **extra) -> Options:
    layer = {
        "clips": {"count": count, "min_s": 8.0, "max_s": 15.0},
        "render": {"out_dir": str(out), "dry_run": dry},
        "analysis": {"cache": False},
        **QUIET,
    }
    return Options.from_layers(layer, extra)


def _covers(report, t: float, name: str | None = None):
    return [
        c
        for c in report.clips
        if c.start <= t <= c.end and (name is None or c.source.endswith(name))
    ]


@pytest.fixture(scope="session")
def truth() -> dict:
    ensure(FIX, "short_clips")
    return json.loads((FIX / "inputs" / "inputs.json").read_text())


@pytest.fixture(scope="session")
def caps():
    return preflight()


# --- discovery ----------------------------------------------------------------------------


def test_discover_friendly_errors(tmp_path):
    with pytest.raises(InputError, match="not found"):
        discover([tmp_path / "nope.mp4"])
    (tmp_path / "notes.txt").write_text("x")
    with pytest.raises(InputError, match="unsupported file type"):
        discover([tmp_path / "notes.txt"])
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(InputError, match="no video files"):
        discover([empty])
    steam = tmp_path / "steam"
    (steam / "clips" / "clip_1").mkdir(parents=True)
    (steam / "clips" / "clip_1" / "init-stream0.m4s").write_bytes(b"")
    with pytest.raises(InputError, match="Steam"):
        discover([steam])


def test_discover_folder_and_files(truth):
    folder = ensure(FIX, "short_clips")
    files = discover([folder])
    assert [f.name for f in files] == [f"clip_{k}.mp4" for k in range(6)]
    two = discover([files[0], files[1], files[0]])  # duplicates collapse
    assert len(two) == 2


# --- many files = one session ------------------------------------------------------------


def test_short_clips_ranked_as_whole_files(truth, tmp_path):
    folder = ensure(FIX, "short_clips")
    opts = Options.from_layers(
        {"clips": {"count": 6}, "render": {"out_dir": str(tmp_path), "dry_run": True},
         "analysis": {"cache": False}, **QUIET}
    )  # fmt: skip
    report = run(folder, opts)
    # session order follows creation_time, which runs against the names
    names = [Path(s["path"]).name for s in report.input["sources"]]
    assert names == [f"clip_{k}.mp4" for k in range(5, -1, -1)]
    assert report.input["short_clips"] is True
    assert any(w.code == "short_clips" for w in report.warnings)
    assert len(report.clips) == 6
    for c in report.clips:
        assert (c.start, c.end) == (0.0, truth["short_dur"])  # whole file: 30 s <= --max
        assert c.snap["mode"] == "whole file"
        assert c.session_start == pytest.approx(
            c.start + next(s["offset_s"] for s in report.input["sources"] if s["path"] == c.source)
        )
    ranked = [int(Path(c.source).stem.split("_")[1]) for c in report.clips]
    levels = truth["short_levels"]
    assert ranked[0] == levels.index(max(levels))  # the loudest clip first
    assert set(ranked[:3]) == {0, 2, 4}  # the three loud ones on top
    assert set(ranked[4:]) == {3, 5}  # the near-silent ones last
    data = json.loads((tmp_path / "report.json").read_text())
    assert data["input"]["files"] == 6 and data["clips"][0]["source"].endswith("clip_0.mp4")


def test_session_clips_never_cross_a_file(truth, tmp_path):
    folder = ensure(FIX, "session")
    cache_dir = tmp_path / "cache"
    opts = _opts(tmp_path, count=6, analysis={"cache": True, "cache_dir": str(cache_dir)})
    report = run(folder, opts)
    split = truth["session_split"]
    srcs = {Path(s["path"]).name: s for s in report.input["sources"]}
    assert list(srcs) == ["part_a.mp4", "part_b.mp4"]
    assert srcs["part_b.mp4"]["offset_s"] == pytest.approx(split, abs=0.5)
    assert len(report.clips) >= 4
    hits = set()
    for c in report.clips:
        name = Path(c.source).name
        dur = srcs[name]["duration_s"]
        assert 0.0 <= c.start < c.end <= dur + 1e-6  # inside its own file
        assert c.session_start == pytest.approx(srcs[name]["offset_s"] + c.start)
        for b in truth["session_bursts"]:
            local = b - (split if name == "part_b.mp4" else 0.0)
            if c.start <= local <= c.end:
                hits.add(b)
    assert len(hits) == len(report.clips)  # every clip holds one burst in its own file
    assert {Path(c.source).name for c in report.clips} == {"part_a.mp4", "part_b.mp4"}
    assert len(list(cache_dir.glob("*/signals.npz"))) == 2  # signals cached per file


def test_cli_accepts_several_files(truth, tmp_path):
    folder = ensure(FIX, "session")
    files = sorted(folder.glob("*.mp4"))
    res = subprocess.run(
        [sys.executable, "-m", "clip_anything.cli", *map(str, files), "--dry-run", "--json",
         "--no-cache", "--no-captions", "--count", "2", "--out", str(tmp_path)],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert data["input"]["files"] == 2 and len(data["clips"]) == 2
    res = subprocess.run(
        [sys.executable, "-m", "clip_anything.cli", str(tmp_path), "--dry-run"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert res.returncode == 2 and "no video files" in res.stderr


# --- audio tracks -------------------------------------------------------------------------


def test_two_audio_tracks(truth, tmp_path, caps):
    f = ensure(FIX, "two_tracks")
    info = probe(f, caps)
    assert [a.title for a in info.audio_streams] == ["Game", "Mic"]
    game, mic = truth["two_track_game"], truth["two_track_mic"]

    report = run(f, _opts(tmp_path / "auto", count=3))
    roles = report.input["audio_tracks"][0]
    assert [t["role"] for t in roles["tracks"]] == ["game", "mic"]
    assert roles["used"].startswith("mix of tracks 0,1")
    for t in [*game, mic]:
        assert _covers(report, t), f"{t}s missing from the mix analysis"

    report = run(f, _opts(tmp_path / "mic", count=1, analysis={"audio_track": "1"}))
    assert report.input["audio_tracks"][0]["used"] == "track 1"
    assert _covers(report, mic) and not _covers(report, game[0])

    report = run(f, _opts(tmp_path / "game", count=2, analysis={"audio_track": "game"}))
    assert all(_covers(report, t) for t in game) and not _covers(report, mic)

    with pytest.raises(InputError, match="does not exist"):
        run(f, _opts(tmp_path / "bad", analysis={"audio_track": "7"}))


def test_no_audio_stream(truth, tmp_path, caps):
    f = ensure(FIX, "no_audio")
    report = run(f, _opts(tmp_path, count=2, dry=False, scoring={"min_score": 0.0}))
    assert report.input["has_audio"] is False
    assert any(w.code == "no_audio" for w in report.warnings)
    assert report.clips and report.clips[0].status == "ok"
    assert report.clips[0].components.get("motion", 0) > 0.5
    out = probe(report.clips[0].path, caps)
    assert out.has_audio is False and (out.width, out.height) == (1080, 1920)


# --- geometry -----------------------------------------------------------------------------


@pytest.mark.parametrize("variant", ["vertical", "four_three", "ultrawide"])
def test_geometry_renders_9x16(variant, truth, tmp_path, caps):
    f = ensure(FIX, variant)
    report = run(f, _opts(tmp_path, count=1, dry=False, scoring={"min_score": 0.0}))
    assert len(report.clips) == 1 and report.clips[0].status == "ok", report.warnings
    c = report.clips[0]
    assert c.start <= truth["burst_40s"] <= c.end
    out = probe(c.path, caps)
    assert (out.width, out.height) == (1080, 1920)
    if variant == "vertical":
        assert c.crop["mode"] == "center"  # already 9:16: scale/pad, no crop


# --- containers / codecs ------------------------------------------------------------------


CODEC_CASES = {
    "hdr_hlg": ("hevc", True),
    "hdr_notag": ("vp9", True),
    "prores": ("prores", False),
    "vp9_opus": ("vp9", False),
    "av1": ("av1", False),
    "ts": ("h264", False),
    "truncated": ("h264", False),
}


@pytest.mark.parametrize("variant", sorted(CODEC_CASES))
def test_containers_and_codecs(variant, truth, tmp_path, caps):
    f = ensure(FIX, variant)
    vcodec, hdr = CODEC_CASES[variant]
    info = probe(f, caps)
    assert info.vcodec == vcodec and info.is_hdr is hdr
    if variant == "hdr_notag":
        assert info.hdr_assumed is True
    if variant == "truncated":
        assert info.duration_measured and 15.0 < info.duration_s < 30.0
    report = run(f, _opts(tmp_path, count=1, dry=False, scoring={"min_score": 0.0}))
    assert len(report.clips) == 1 and report.clips[0].status == "ok", report.warnings
    c = report.clips[0]
    burst = 10.0 if variant == "prores" else truth["burst_40s"]
    assert c.start <= burst <= c.end
    out = probe(c.path, caps)
    assert (out.width, out.height, out.pix_fmt) == (1080, 1920, "yuv420p")
    assert out.vcodec == "h264" and out.has_audio
    codes = {w.code for w in report.warnings}
    if hdr:
        assert "hdr" in codes and out.color_transfer == "bt709"
    if variant == "truncated":
        assert "no_index" in codes


# --- resume after an abort ----------------------------------------------------------------


def test_resume_after_abort(synth_video, synth_truth, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "SEGMENT_S", 20.0)
    cache_dir = tmp_path / "cache"
    layer = {"clips": {"count": 6}, "render": {"out_dir": str(tmp_path), "dry_run": True},
             "analysis": {"cache_dir": str(cache_dir)}, **QUIET}  # fmt: skip
    opts = Options.from_layers(layer)

    class Abort(RuntimeError):
        pass

    def killer(ev):
        if ev.stage == "audio" and ev.kind == "progress" and ev.done > 50.0:
            raise Abort("simulated kill")

    with pytest.raises(Abort):
        run(synth_video, opts, on_event=killer)
    partials = sorted(p.name for p in cache_dir.glob("*/*.partial.npz"))
    assert "audio.partial.npz" in partials
    assert not list(cache_dir.glob("*/signals.npz"))

    report = run(synth_video, opts)
    audio = [s for s in report.stages if s.name == "audio"]
    assert audio and audio[0].status == "ok" and "resumed at 40s" in audio[0].detail
    assert not list(cache_dir.glob("*/*.partial.npz")) and not list(cache_dir.glob("*/*.part"))
    clean = run(synth_video, Options.from_layers(layer, {"analysis": {"cache": False}}))
    assert [(c.start, c.end) for c in report.clips] == [(c.start, c.end) for c in clean.clips]


# --- 3 h file: memory and leftovers (slow, on request) --------------------------------------


@pytest.mark.skipif(not os.environ.get("CLIP_ANYTHING_LONG"), reason="set CLIP_ANYTHING_LONG=1")
def test_three_hour_file_memory_and_no_leftovers(tmp_path):
    f = ensure(FIX, "long")
    before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    res = subprocess.run(
        [sys.executable, "-m", "clip_anything.cli", str(f), "--dry-run", "--json", "--no-captions",
         "--count", "5", "--out", str(tmp_path)],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert res.returncode == 0, res.stderr[-2000:]
    peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    peak_bytes = peak if sys.platform == "darwin" else peak * 1024
    assert max(peak_bytes, before) < 1 << 30, f"peak RSS {peak_bytes / 2**20:.0f} MiB"
    data = json.loads(res.stdout)
    assert data["input"]["duration_s"] > 10700 and len(data["clips"]) == 5
    cache = Path(f).parent / ".clipanything"
    leftovers = [p for p in cache.rglob("*") if p.suffix == ".part" or "partial" in p.name]
    assert not leftovers and (cache / data["input"]["id"] / "signals.npz").is_file()
