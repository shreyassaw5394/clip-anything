"""GUI controller without tkinter, plus a headless-safe selftest of the window."""

from __future__ import annotations

import subprocess
import sys
import threading
import time

from clip_anything.errors import FFmpegMissing, InputError, StageError
from clip_anything.events import Event
from clip_anything.gui import (
    Controller,
    JobSettings,
    ProgressModel,
    clip_rows,
    friendly_error,
)
from clip_anything.report import Clip, Report


def _report(tmp_path, n=2):
    r = Report(input={}, options={}, out_dir=str(tmp_path))
    for i in range(1, n + 1):
        r.clips.append(
            Clip(
                rank=i, candidate_id=i, start=10.0 * i, end=10.0 * i + 20, duration_s=20.0,
                score=0.9 - i / 10, path=str(tmp_path / f"c{i}.mp4"), status="ok",
            )
        )  # fmt: skip
    return r


def test_settings_problems(tmp_path):
    assert "Choose a recording" in JobSettings().problem()
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    s = JobSettings(inputs=[str(v)], out_dir="")
    assert "where" in s.problem()
    s = JobSettings(inputs=[str(tmp_path / "nope.mp4")], out_dir=str(tmp_path))
    assert "Cannot find" in s.problem()
    s = JobSettings(inputs=[str(v)], out_dir=str(tmp_path), count=0)
    assert "between 1 and 100" in s.problem()
    s = JobSettings(inputs=[str(v)], out_dir=str(tmp_path), count=5, crop="center")
    assert s.problem() is None
    layers = s.layers()
    assert layers["clips"]["count"] == 5 and layers["layout"]["crop"] == "center"
    from clip_anything.config import Options

    assert Options.from_layers(layers).clips.count == 5  # every key is a real option


def test_progress_model_is_monotonic_and_labelled():
    m = ProgressModel()
    p = m.update(Event("probe", "start"))
    assert p.label == "Reading the recording" and p.fraction == 0.0
    m.update(Event("probe", "done"))
    p = m.update(Event("audio", "progress", 30.0, 60.0, "s"))
    assert 0.1 < p.fraction < 0.2 and p.detail == "00:30 of 01:00"
    last = p.fraction
    for ev in (
        Event("audio", "done"),
        Event("video", "done"),
        Event("score", "done"),
        Event("render", "progress", 1, 4, "clips"),
        Event("render", "done", 4, 4, "clips"),
    ):
        p = m.update(ev)
        assert p.fraction >= last
        last = p.fraction
    assert p.fraction > 0.9 and p.fraction < 1.0


def test_controller_runs_job_and_reports(tmp_path):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    seen = {}

    def fake_runner(target, opts, on_event, cancel):
        seen["target"], seen["count"] = target, opts.clips.count
        on_event(Event("probe", "start"))
        on_event(Event("probe", "done"))
        on_event(Event("audio", "warn", message="one note"))
        on_event(Event("render", "done", 2, 2, "clips"))
        return _report(tmp_path)

    c = Controller(runner=fake_runner)
    assert c.start(JobSettings(inputs=[str(v)], out_dir=str(tmp_path), count=3)) is None
    c.thread.join(5)
    kinds = [k for k, _ in c.drain()]
    assert kinds[-1] == "done" and "warn" in kinds and "progress" in kinds
    assert seen == {"target": str(v), "count": 3}
    assert clip_rows(c.report)[0] == ("1", "00:10-00:30", "0.80", "c1.mp4")
    assert "already" not in (c.start(JobSettings(inputs=[str(v)], out_dir=str(tmp_path))) or "")


def test_controller_cancel_and_errors(tmp_path):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    started = threading.Event()

    def slow(target, opts, on_event, cancel):
        started.set()
        while not cancel.is_set():
            time.sleep(0.01)
        raise StageError("audio", "cancelled")

    c = Controller(runner=slow)
    assert c.start(JobSettings(inputs=[str(v)], out_dir=str(tmp_path))) is None
    started.wait(5)
    assert c.running
    assert "already running" in c.start(JobSettings(inputs=[str(v)], out_dir=str(tmp_path)))
    c.cancel()
    c.thread.join(5)
    assert c.drain()[-1][0] == "cancelled"

    def boom(target, opts, on_event, cancel):
        raise InputError("ffprobe could not read v.mp4: moov atom not found")

    c = Controller(runner=boom)
    c.start(JobSettings(inputs=[str(v)], out_dir=str(tmp_path)))
    c.thread.join(5)
    kind, text = c.drain()[-1]
    assert kind == "error" and "could not be read" in text


def test_friendly_errors_have_no_tracebacks():
    assert "ffmpeg" in friendly_error(FFmpegMissing("x", "brew install ffmpeg"))
    assert friendly_error(InputError("input file not found: a")).startswith("That file")
    assert friendly_error(StageError("render", "cancelled")) == "Stopped."
    assert "Making the clips".lower() in friendly_error(StageError("render", "boom")).lower()
    assert "Unexpected" in friendly_error(RuntimeError("?"))


def test_gui_selftest_exits_zero():
    res = subprocess.run(
        [sys.executable, "-m", "clip_anything.gui", "--selftest"],
        capture_output=True, text=True, check=False, timeout=120,
    )  # fmt: skip
    assert res.returncode == 0, res.stderr
    assert "selftest" in res.stdout
