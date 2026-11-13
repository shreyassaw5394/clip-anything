"""A run started from the app never dies silently: crash logs with the traceback, optional
modules that fail to load (zlib.error from a damaged bundle, say) become warnings, a damaged
cache or a corrupt recent.json is treated as empty, and the packaged app says so when it runs
from a disk image or a translocated path."""

from __future__ import annotations

import http.client
import importlib.machinery
import json
import sys
import time
import types
import zlib
from pathlib import Path

import numpy as np
import pytest

from clip_anything import crashlog
from clip_anything.app.data import Prefs, Recent
from clip_anything.app.jobs import Job, JobRequest
from clip_anything.app.server import AppServer
from clip_anything.cache import SignalCache
from clip_anything.config import Options
from clip_anything.gui import Controller, JobSettings, headless
from clip_anything.report import Report

ZLIB_MSG = "Error -3 while decompressing data: incorrect header check"
_real_log_dir = crashlog.log_dir  # captured before the conftest fixture redirects it


def _boom(*_a, **_k):
    raise zlib.error(ZLIB_MSG)


@pytest.fixture
def logs(tmp_path, monkeypatch) -> Path:
    d = tmp_path / "logs"
    monkeypatch.setattr(crashlog, "log_dir", lambda: d)
    return d


def _fake_faster_whisper(monkeypatch) -> None:
    """A `faster_whisper` that is importable (find_spec succeeds, as in the bundle) but whose
    attribute access blows up with zlib.error, like a module whose code will not inflate."""

    class Broken(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            raise zlib.error(ZLIB_MSG)

    mod = Broken("faster_whisper")
    mod.__spec__ = importlib.machinery.ModuleSpec("faster_whisper", loader=None)
    mod.__path__ = []
    monkeypatch.setitem(sys.modules, "faster_whisper", mod)
    import clip_anything.speech as speech

    monkeypatch.setattr(speech, "model_cached", lambda name: True)


# --- crash log -------------------------------------------------------------------------------


def test_crash_log_contents_and_pruning(tmp_path):
    d = tmp_path / "logs"
    try:
        raise zlib.error(ZLIB_MSG)
    except zlib.error as exc:
        p = crashlog.write_crash_log(
            exc,
            inputs=["/Users/me/Movies/secret folder/six-hours.mkv"],
            options={"render": {"out_dir": "/x"}, "ai": {"api_key": "sk-123"}},
            source="gui",
            directory=d,
        )
    assert p is not None and p.parent == d and p.name.startswith("run-")
    text = p.read_text()
    assert "zlib.error: Error -3" in text and "Traceback" in text
    assert "six-hours.mkv" in text and "/Users/me/Movies" not in text  # basename only
    assert "sk-123" not in text and "<redacted>" in text
    assert "frozen: False" in text and sys.version.split()[0] in text
    for i in range(25):
        (d / f"run-2000010{i:02d}-000000-000.log").write_text("old")
    crashlog.write_crash_log(RuntimeError("x"), directory=d)
    assert len(list(d.glob("run-*.log"))) == crashlog.KEEP_LOGS
    assert not (d / "run-20000100-000000-000.log").exists()  # the oldest went first


def test_crash_log_never_raises(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    assert crashlog.write_crash_log(RuntimeError("x"), directory=blocker / "logs") is None


def test_log_dir_per_platform(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(sys, "platform", "darwin")
    assert _real_log_dir() == tmp_path / "Library/Application Support/clip-anything/logs"
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert _real_log_dir() == tmp_path / "Roaming/clip-anything/logs"
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    assert _real_log_dir() == tmp_path / ".local/state/clip-anything/logs"


def test_controller_unexpected_error_points_at_log(tmp_path, logs):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    c = Controller(runner=_boom)
    assert c.start(JobSettings(inputs=[str(v)], out_dir=str(tmp_path))) is None
    c.thread.join(10)
    kinds = dict(c.drain())
    assert kinds["error"].startswith("Unexpected problem. Details saved to ")
    assert ZLIB_MSG not in kinds["error"]  # internals live in the log, not the banner
    log = Path(kinds["log"])
    assert log.parent == logs and ZLIB_MSG in log.read_text() and "source: gui" in log.read_text()
    assert c.crash_log == str(log)


def test_headless_prints_log_path(tmp_path, logs, capsys, monkeypatch):
    import clip_anything.gui as gui

    monkeypatch.setattr(gui, "default_runner", _boom)
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    assert headless([str(v)], str(tmp_path), 2) == 1
    out = capsys.readouterr().out
    assert "log: " in out and "error: Unexpected problem. Details saved to" in out


def test_expected_errors_keep_their_text_but_still_log(tmp_path, logs):
    from clip_anything.errors import InputError

    def bad(*_a, **_k):
        raise InputError("input not found: nope.mp4")

    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    c = Controller(runner=bad)
    c.start(JobSettings(inputs=[str(v)], out_dir=str(tmp_path)))
    c.thread.join(10)
    kinds = dict(c.drain())
    assert kinds["error"] == "That file could not be found. It may have been moved or renamed."
    assert Path(kinds["log"]).is_file()


# --- app server --------------------------------------------------------------------------


def _req(s, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", s.port, timeout=10)
    h = {"Authorization": f"Bearer {s.token}"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    conn.request(method, path, body=data, headers=h)
    res = conn.getresponse()
    raw = res.read()
    conn.close()
    return res, json.loads(raw)


def _wait(s, job_id, timeout=120.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        _res, st = _req(s, "GET", f"/api/jobs/{job_id}")
        if st["state"] not in ("queued", "running"):
            return st
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_job_error_json_carries_log_path(tmp_path, logs):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    job = Job(JobRequest(inputs=[str(v)], out_dir=str(tmp_path)), runner=_boom)
    job.start()
    job.thread.join(10)
    st = job.status()
    assert st["state"] == "error" and st["error"].startswith("Unexpected problem. Details saved")
    assert Path(st["log"]).is_file() and job.events[-1]["log"] == st["log"]
    assert "source: app" in Path(st["log"]).read_text()


def test_server_handler_crash_is_a_500_with_log(tmp_path, logs, monkeypatch):
    s = AppServer(
        runner=_boom, recent=Recent(tmp_path / "r.json"), prefs=Prefs(tmp_path / "p.json")
    ).start()
    try:
        res, caps = _req(s, "GET", "/api/caps")
        assert res.status == 200 and caps["notice"] == "" and caps["log_dir"] == str(logs)
        monkeypatch.setattr(AppServer, "inspect", lambda self, paths: _boom())
        res, data = _req(s, "POST", "/api/inspect", body={"inputs": [str(tmp_path)]})
        assert res.status == 500 and data["ok"] is False
        assert data["error"].startswith("Unexpected problem. Details saved to ")
        assert Path(data["log"]).is_file() and "POST /api/inspect" in Path(data["log"]).read_text()
        # a job that dies the same way: the finished event and the status carry the path
        v = tmp_path / "v.mp4"
        v.write_bytes(b"x")
        res, data = _req(s, "POST", "/api/jobs", body={"inputs": [str(v)]})
        assert res.status == 201
        st = _wait(s, data["id"])
        assert st["state"] == "error" and Path(st["log"]).is_file()
    finally:
        s.stop()


# --- optional modules never kill a run -------------------------------------------------


def _opts(tmp_path, **layers):
    base = {
        "clips": {"count": 1},
        "render": {"out_dir": str(tmp_path / "clips")},
        "analysis": {"cache": False},
    }
    base.update(layers)
    return Options.from_layers(base)


def _warnings(report: Report) -> list[str]:
    return [f"{w.stage}: {w.message}" for w in report.warnings]


def test_speech_import_failure_is_a_reason_not_a_crash(monkeypatch):
    _fake_faster_whisper(monkeypatch)
    from clip_anything.speech import load_model

    model, reason = load_model("base.en", allow_download=True)
    assert model is None and ZLIB_MSG in reason and "could not load Whisper model" in reason


def test_run_completes_when_captions_module_breaks(synth_video, tmp_path, monkeypatch):
    import clip_anything.speech as speech

    monkeypatch.setattr(speech, "load_model", _boom)
    opts = _opts(tmp_path, speech={"captions": True, "yes": True})
    opts.render.dry_run = True
    events = []
    report = run_pipeline(synth_video, opts, events.append)
    assert report.clips
    w = [x for x in _warnings(report) if x.startswith("speech: captions off: zlib.error")]
    assert w and ZLIB_MSG in w[0]
    assert any(e.stage == "speech" and e.kind == "warn" for e in events)
    assert any(e.stage == "speech" and e.kind == "skipped" for e in events)


def test_run_completes_when_facecam_breaks(synth_video, tmp_path, monkeypatch):
    import clip_anything.facecam as facecam

    monkeypatch.setattr(facecam, "detect_facecam", _boom)
    report = run_pipeline(synth_video, _opts(tmp_path, layout={"facecam": "auto"}))
    assert report.ok_clips and report.clips[0].layout == "gameplay"
    assert any("facecam: facecam off: zlib.error" in x for x in _warnings(report))


def test_facecam_stage_survives_cascade_load_failure(synth_video, tmp_path, monkeypatch):
    import cv2

    import clip_anything.facecam as facecam
    from clip_anything.pipeline import _facecam_stage
    from clip_anything.probe import preflight, probe

    region = {"x": 0, "y": 0, "w": 160, "h": 120, "frac": 0.1, "corner": "top-left"}
    monkeypatch.setattr(facecam, "static_regions", lambda frames: [region])
    monkeypatch.setattr(cv2, "CascadeClassifier", _boom)  # the Haar xml will not load
    caps = preflight()
    report = Report(input={}, options={})
    events = []
    fc = _facecam_stage(probe(synth_video, caps), caps, _opts(tmp_path), report, events.append)
    assert fc is None
    assert any("facecam off: zlib.error" in x for x in _warnings(report))
    assert [e.kind for e in events if e.stage == "facecam"] == ["start", "warn", "done"]


def test_run_completes_when_ai_rerank_breaks(synth_video, tmp_path):
    opts = _opts(tmp_path)
    opts.render.dry_run = True
    report = run_pipeline(synth_video, opts, rerank=_boom)
    assert len(report.clips) == 1
    assert any("ai: AI off: zlib.error" in x for x in _warnings(report))


def run_pipeline(video, opts, on_event=None, rerank=None):
    from clip_anything.pipeline import run

    return run(video, opts, on_event=on_event, rerank=rerank)


def test_headless_app_run_with_broken_whisper_finishes_with_warning(
    synth_video, tmp_path, monkeypatch, logs
):
    """The owner's case, driven through `clip-anything app`'s server with the real pipeline:
    faster-whisper raises zlib.error inside the run -> the run ends `done` with a captions
    warning, not the "Unexpected problem" banner."""
    _fake_faster_whisper(monkeypatch)
    s = AppServer(recent=Recent(tmp_path / "r.json"), prefs=Prefs(tmp_path / "p.json")).start()
    try:
        res, caps = _req(s, "GET", "/api/caps")
        assert caps["captions"] is True  # the bundle believes captions are available
        body = {
            "inputs": [str(synth_video)],
            "out_dir": str(tmp_path / "clips"),
            "count": 1,
            "captions": True,
            "facecam": "off",
        }
        res, data = _req(s, "POST", "/api/jobs", body=body)
        assert res.status == 201, data
        st = _wait(s, data["id"])
        assert st["state"] == "done", st["error"]
        assert st["error"] == "" and st["log"] == ""
        assert st["result"]["ok"] == 1
        joined = " | ".join(st["warnings"] + st["result"]["warnings"])
        assert "captions" in joined and ZLIB_MSG in joined
    finally:
        s.stop()
    assert not list(logs.glob("*.log"))  # nothing crashed, nothing logged


# --- damaged cache / user files ----------------------------------------------------------


def test_truncated_npz_is_a_miss(tmp_path):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"\0" * 4096)
    c = SignalCache(v, None, enabled=True)
    full = c.put_npz("signals.npz", "fp", {"audio.rms_db": np.zeros(400, dtype=np.float32)})
    assert full is not None
    data = full.read_bytes()
    full.write_bytes(data[:100])
    assert c.get_npz("signals.npz", "fp") is None
    part = c.put_npz("audio.partial.npz", "fp", {"audio.rms_db": np.zeros(50, dtype=np.float32)})
    part.write_bytes(part.read_bytes()[:100])
    assert c.get_npz("audio.partial.npz", "fp") is None
    c.path("video.partial.npz").write_bytes(b"PK\x03\x04garbage")
    assert c.get_npz("video.partial.npz", "fp") is None


def test_run_with_truncated_cache_files(synth_video, tmp_path):
    from clip_anything.pipeline import _analysis_fingerprint

    opts = Options.from_layers(
        {
            "clips": {"count": 1},
            "render": {"out_dir": str(tmp_path / "clips"), "dry_run": True},
            "analysis": {"cache_dir": str(tmp_path / "cache")},
        }
    )
    cache = SignalCache(synth_video, opts.analysis.cache_dir, True)
    fp = _analysis_fingerprint(opts) + "-atrack0"
    for name in ("signals.npz", "audio.partial.npz", "video.partial.npz"):
        p = cache.put_npz(name, fp, {"audio.rms_db": np.zeros(400, dtype=np.float32)})
        p.write_bytes(p.read_bytes()[:100])
    report = run_pipeline(synth_video, opts)
    assert report.clips and {s.name: s.status for s in report.stages}["audio"] == "ok"
    assert cache.get_npz("signals.npz", fp) is not None  # rewritten whole
    assert not cache.path("audio.partial.npz").exists()


def test_corrupt_recent_and_prefs_reset(tmp_path):
    r = tmp_path / "recent.json"
    r.write_text('{"inputs": [')  # cut off mid-write
    recent = Recent(r)
    assert recent.load() == []
    recent.add({"inputs": ["/a.mp4"], "out_dir": "/o"})
    assert recent.load()[0]["inputs"] == ["/a.mp4"]
    r.write_bytes(b"\xff\xfe\x00garbage")
    assert Recent(r).load() == []
    p = tmp_path / "prefs.json"
    p.write_text("[1, 2")
    prefs = Prefs(p)
    assert prefs.load() == {} and prefs.out_dir() == "" and prefs.window() is None
    prefs.set(out_dir=str(tmp_path))
    assert Prefs(p).out_dir() == str(tmp_path)


# --- packaged-app location ---------------------------------------------------------------


def test_bundle_location_notice():
    f = crashlog.bundle_location_problem
    assert f("/Applications/Clip Anything.app/Contents/Frameworks", frozen=False) is None
    assert f("/Applications/Clip Anything.app/Contents/Frameworks", True, "darwin") is None
    tl = "/private/var/folders/zz/T/AppTranslocation/9F2C-1/d/Clip Anything.app/Contents/Frameworks"
    msg = f(tl, True, "darwin")
    assert msg and msg.startswith("Move Clip Anything to your Applications folder first")
    msg = f("/Volumes/Clip Anything/Clip Anything.app/Contents/Frameworks", True, "darwin")
    assert msg and "disk image" in msg
    assert f("C:\\Users\\me\\Downloads\\Clip Anything\\_internal", True, "win32") is None


def test_startup_notice_reaches_caps_and_gui(tmp_path, monkeypatch, capsys):
    import clip_anything.gui as gui

    notice = "Move Clip Anything to your Applications folder first: test."
    monkeypatch.setattr(gui, "startup_notice", lambda: notice)
    s = AppServer(recent=Recent(tmp_path / "r.json"), prefs=Prefs(tmp_path / "p.json")).start()
    try:
        _res, caps = _req(s, "GET", "/api/caps")
        assert caps["notice"].startswith("Move Clip Anything")
    finally:
        s.stop()
    import clip_anything.app.launch as launch

    monkeypatch.setattr(launch, "launch", lambda **kw: 0)
    assert gui.main(["--browser", "--no-open"]) == 0
    assert "Move Clip Anything" in capsys.readouterr().out
