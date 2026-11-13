"""The local app server: request guards, token, clip file confinement, jobs over SSE, setup
API. A fake runner stands in for the pipeline; nothing here needs ffmpeg."""

from __future__ import annotations

import http.client
import json
import re
import socket
import time
from pathlib import Path

import pytest

from clip_anything.app.jobs import JobRequest, why_line
from clip_anything.app.server import AppServer, is_loopback_host, origin_is_self
from clip_anything.events import Event
from clip_anything.report import Clip, Report


def _report(out: Path, n=2):
    r = Report(
        input={"path": str(out / "v.mp4"), "duration_s": 100.0}, options={}, out_dir=str(out)
    )
    for i in range(1, n + 1):
        f = out / f"c{i}.mp4"
        f.write_bytes(bytes(range(256)) * 4)
        r.clips.append(
            Clip(
                rank=i, candidate_id=i, start=10.0 * i, end=10.0 * i + 20, duration_s=20.0,
                score=0.9 - i / 10, path=str(f), status="ok", source=str(out / "v.mp4"),
                components={"loud_rel": 0.8, "motion": 0.6, "agree": 0.7},
            )
        )  # fmt: skip
    r.write(out / "report.json")
    return r


def _runner_for(out: Path, delay: float = 0.0):
    def runner(target, opts, on_event, cancel, rerank=None):
        on_event(Event("probe", "start"))
        on_event(Event("probe", "done", message="100s 1920x1080"))
        on_event(Event("audio", "progress", 50, 100, "s", extra={"level_db": -20.0}))
        on_event(Event("audio", "done", 100, 100, "s"))
        on_event(
            Event(
                "score",
                "done",
                message="2 clips",
                extra={
                    "curve": [0.1, 0.9, 0.2],
                    "step_s": 33.3,
                    "spans": [{"start": 10, "end": 30, "peak_t": 20, "score": 0.8}],
                },
            )
        )
        if delay:
            t0 = time.time()
            while time.time() - t0 < delay and not cancel.is_set():
                time.sleep(0.01)
        if cancel.is_set():
            from clip_anything.errors import StageError

            raise StageError("render", "cancelled")
        on_event(Event("render", "done", 2, 2, "clips"))
        return _report(out)

    return runner


@pytest.fixture
def server(tmp_path):
    out = tmp_path / "clips"
    out.mkdir()
    recent = tmp_path / "recent.json"
    from clip_anything.app.data import Prefs, Recent

    s = AppServer(
        runner=_runner_for(out),
        recent=Recent(recent),
        prefs=Prefs(tmp_path / "prefs.json"),
        picker=lambda kind, initial="": [str(tmp_path / ("picked.mp4" if not initial else "x"))],
    )
    s.start()
    yield s, out, tmp_path
    s.stop()


def _req(s, method, path, body=None, headers=None, token=True, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", s.port, timeout=10)
    h = dict(headers or {})
    if token:
        h["Authorization"] = f"Bearer {s.token}"
    if host:
        h["Host"] = host
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    conn.request(method, path, body=data, headers=h)
    res = conn.getresponse()
    raw = res.read()
    conn.close()
    try:
        return res, json.loads(raw)
    except ValueError:
        return res, raw


def test_guards_unit():
    assert (
        is_loopback_host("127.0.0.1:5000")
        and is_loopback_host("localhost")
        and is_loopback_host("[::1]:80")
    )
    assert not is_loopback_host("evil.example") and not is_loopback_host("127.0.0.1.evil.example")
    assert origin_is_self(None, 5000) and origin_is_self("http://127.0.0.1:5000", 5000)
    assert not origin_is_self("http://127.0.0.1:5001", 5000)
    assert not origin_is_self("https://evil.example", 5000)
    assert not origin_is_self("null", 5000)


def test_foreign_host_origin_and_missing_token(server):
    s, out, _ = server
    res, _ = _req(s, "GET", "/api/caps", host="evil.example")
    assert res.status == 403
    res, _ = _req(s, "POST", "/api/jobs", body={}, headers={"Origin": "https://evil.example"})
    assert res.status == 403
    res, _ = _req(s, "POST", "/api/jobs", body={}, headers={"Sec-Fetch-Site": "cross-site"})
    assert res.status == 403
    res, _ = _req(s, "GET", "/api/caps", token=False)
    assert res.status == 401
    res, _ = _req(s, "GET", "/", token=False)
    assert res.status == 401
    res, _ = _req(
        s, "POST", "/api/jobs", body={}, headers={"Authorization": "Bearer nope"}, token=False
    )
    assert res.status == 401
    # the static files need no token; everything carries the CSP and nosniff
    res, body = _req(s, "GET", "/static/app.css", token=False)
    assert res.status == 200 and b"--paper" in body
    assert res.getheader("Content-Security-Policy", "").startswith("default-src 'self'")
    assert res.getheader("X-Content-Type-Options") == "nosniff"
    res, _ = _req(s, "GET", "/static/../pyproject.toml", token=False)
    assert res.status == 404
    res, _ = _req(s, "GET", "/static/fonts/OFL-Barlow.txt", token=False)
    assert res.status == 200


def test_binds_loopback_only(server):
    s, _, _ = server
    assert s.httpd.server_address[0] == "127.0.0.1"
    # the port is not reachable on a non-loopback address of this machine
    hostname_ip = None
    try:
        hostname_ip = socket.gethostbyname(socket.gethostname())
    except OSError:
        pass
    if hostname_ip and not hostname_ip.startswith("127."):
        with pytest.raises(OSError):
            socket.create_connection((hostname_ip, s.port), timeout=1).close()


def _run_job(s, body):
    res, data = _req(s, "POST", "/api/jobs", body=body)
    assert res.status == 201, data
    job_id = data["id"]
    for _ in range(200):
        res, st = _req(s, "GET", f"/api/jobs/{job_id}")
        if st["state"] not in ("queued", "running"):
            return job_id, st
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_job_runs_streams_and_serves_clips(server):
    s, out, tmp = server
    v = tmp / "v.mp4"
    v.write_bytes(b"x")
    res, data = _req(s, "POST", "/api/jobs", body={"inputs": [str(v)], "count": 99})
    assert res.status == 400 and "between 1" in data["error"]
    res, data = _req(s, "POST", "/api/jobs", body={"inputs": [str(tmp / "nope.mp4")]})
    assert res.status == 400 and "Cannot find" in data["error"]

    job_id, st = _run_job(s, {"inputs": [str(v)], "count": 2, "length": "short"})
    assert st["state"] == "done" and st["result"]["ok"] == 2
    clip = st["result"]["clips"][0]
    assert clip["file"] == "c1.mp4" and "loud burst" in clip["why"] and clip["post"]
    assert st["request"]["out_dir"] == str(tmp / "clips")  # default next to the recording

    # SSE replays the whole log, ends with `finished`, carries the curve extra
    conn = http.client.HTTPConnection("127.0.0.1", s.port, timeout=10)
    conn.request("GET", f"/api/jobs/{job_id}/events?t={s.token}")
    res = conn.getresponse()
    assert res.status == 200 and res.getheader("Content-Type", "").startswith("text/event-stream")
    text = res.read().decode()
    conn.close()
    kinds = [line.split(": ", 1)[1] for line in text.splitlines() if line.startswith("event: ")]
    assert kinds[0] == "start" and kinds[-1] == "finished" and "done" in kinds
    assert '"curve":[0.1,0.9,0.2]' in text and '"level_db":-20.0' in text

    # clips: whole, ranged, HEAD; traversal and foreign names are 404
    res, body = _req(s, "GET", f"/clips/{job_id}/c1.mp4")
    assert res.status == 200 and len(body) == 1024 and res.getheader("Accept-Ranges") == "bytes"
    res, body = _req(s, "GET", f"/clips/{job_id}/c1.mp4", headers={"Range": "bytes=10-19"})
    assert res.status == 206 and body == bytes(range(10, 20))
    assert res.getheader("Content-Range") == "bytes 10-19/1024"
    res, body = _req(s, "GET", f"/clips/{job_id}/c1.mp4", headers={"Range": "bytes=2000-"})
    assert res.status == 416
    res, _ = _req(s, "GET", f"/clips/{job_id}/report.json")
    assert res.status == 200
    (tmp / "secret.txt").write_text("no")
    for bad in (
        "..%2Fsecret.txt",
        "../secret.txt",
        "%2e%2e/secret.txt",
        "secret.txt",
        ".hidden.mp4",
    ):
        res, _ = _req(s, "GET", f"/clips/{job_id}/{bad}")
        assert res.status == 404, bad
    res, _ = _req(s, "GET", f"/clips/{job_id}/c1.mp4", token=False)
    assert res.status == 401
    res, _ = _req(s, "GET", "/clips/nope/c1.mp4")
    assert res.status == 404

    # delete confined to the folder; recent remembers the run
    res, data = _req(s, "POST", f"/api/jobs/{job_id}/delete", body={"file": "c2.mp4"})
    assert res.status == 200 and data["removed"] == ["c2.mp4"] and not (out / "c2.mp4").exists()
    res, data = _req(s, "POST", f"/api/jobs/{job_id}/delete", body={"file": "report.json"})
    assert res.status == 400
    time.sleep(0.1)
    res, caps = _req(s, "GET", "/api/caps")
    assert caps["recent"] and caps["recent"][0]["inputs"] == [str(v)]
    res, data = _req(s, "POST", "/api/recent/clear", body={})
    res, caps = _req(s, "GET", "/api/caps")
    assert caps["recent"] == []


def test_cancel_and_one_job_at_a_time(tmp_path):
    out = tmp_path / "clips"
    out.mkdir()
    from clip_anything.app.data import Recent

    s = AppServer(runner=_runner_for(out, delay=5.0), recent=Recent(tmp_path / "r.json")).start()
    try:
        v = tmp_path / "v.mp4"
        v.write_bytes(b"x")
        res, data = _req(s, "POST", "/api/jobs", body={"inputs": [str(v)]})
        assert res.status == 201
        res, _ = _req(s, "POST", "/api/jobs", body={"inputs": [str(v)]})
        assert res.status == 409
        res, _ = _req(s, "POST", f"/api/jobs/{data['id']}/cancel", body={})
        assert res.status == 200
        for _ in range(200):
            res, st = _req(s, "GET", f"/api/jobs/{data['id']}")
            if st["state"] == "cancelled":
                break
            time.sleep(0.02)
        assert st["state"] == "cancelled"
    finally:
        s.stop()


def test_pick_setup_and_body_limits(server, monkeypatch):
    s, out, tmp = server
    res, data = _req(s, "POST", "/api/pick", body={"kind": "files"})
    assert data["paths"] == [str(tmp / "picked.mp4")]
    res, _ = _req(s, "POST", "/api/pick", body={"kind": "shell"})
    assert res.status == 400
    conn = http.client.HTTPConnection("127.0.0.1", s.port, timeout=10)
    conn.request(
        "POST",
        "/api/jobs",
        body=b"x" * 300_000,
        headers={"Authorization": f"Bearer {s.token}", "Content-Type": "application/json"},
    )
    assert conn.getresponse().status == 413
    conn.close()
    res, _ = _req(s, "POST", "/api/jobs", body=[1, 2])
    assert res.status == 400

    from clip_anything import setup_cmd as sc

    class _Caps:
        version = (7, 1)
        captions = True

    monkeypatch.setattr(sc.Tools, "ffmpeg_caps", lambda self: _Caps(), raising=False)
    res, data = _req(s, "GET", "/api/setup")
    keys = [st["key"] for st in data["steps"]]
    assert keys == ["ffmpeg", "python", "captions", "whisper", "ollama", "vision"]
    res, data = _req(s, "POST", "/api/setup/install", body={"key": "nope"})
    assert res.status == 400


def test_request_parsing_and_why_line():
    with pytest.raises(ValueError):
        JobRequest.from_json({"inputs": "x"})
    r = JobRequest.from_json({"inputs": ["/a.mp4"], "count": "3", "length": "long", "ai": 1})
    assert (
        r.count == 3
        and r.ai is True
        and r.layers()["clips"] == {"count": 3, "min_s": 30.0, "max_s": 60.0}
    )
    assert r.default_out_dir().endswith("clips")
    c = Clip(
        rank=1,
        candidate_id=1,
        start=0,
        end=20,
        duration_s=20,
        score=0.5,
        components={"motion": 0.9},
        speech={"shouts": 2},
    )
    assert why_line(c) == "Fast motion and shouting"
    c.components = {}
    c.speech = {}
    assert why_line(c) == "Above the action bar"


def test_about_screen_and_first_run_line(server):
    """The page carries the About screen, the one-time privacy line and only safe outbound links."""
    s, _, _ = server
    res, body = _req(s, "GET", "/")
    assert res.status == 200
    html = body.decode()
    assert 'id="screen-about"' in html and 'id="about"' in html
    assert "Everything stays on this computer unless you turn on cloud AI" in html
    assert "docs/privacy.md" in html and "docs/terms.md" in html and "SHA256SUMS.txt" in html
    for href in re.findall(r'href="([^"]+)"', html):
        assert href.startswith(("https://", "mailto:", "/static/", "#")), href
    res, body = _req(s, "GET", "/static/app.js", token=False)
    assert b'"about"' in body and b"about-version" in body


def test_inspect_prefs_and_bar(server, monkeypatch):
    s, out, tmp = server
    import clip_anything.app.server as srv

    monkeypatch.setattr(srv.AppServer, "_ffmpeg_caps", lambda self: None)
    (tmp / "a.mp4").write_bytes(b"\0" * 1234)
    (tmp / "notes.txt").write_text("x")
    empty = tmp / "empty"
    empty.mkdir()
    res, data = _req(s, "POST", "/api/inspect", body={"inputs": [str(tmp / "a.mp4")]})
    assert data["items"][0]["kind"] == "file" and data["items"][0]["size_bytes"] == 1234
    assert data["problem"] == "" and data["videos"] == 1
    res, data = _req(s, "POST", "/api/inspect", body={"inputs": [str(tmp / "notes.txt")]})
    assert data["items"][0]["kind"] == "unsupported" and "not a video" in data["problem"]
    res, data = _req(s, "POST", "/api/inspect", body={"inputs": [str(empty)]})
    assert data["items"][0]["kind"] == "folder" and "No recordings" in data["problem"]
    res, data = _req(s, "POST", "/api/inspect", body={"inputs": [str(tmp)]})
    assert data["items"][0]["videos"] == 1 and data["problem"] == ""
    res, data = _req(s, "POST", "/api/inspect", body={"inputs": [str(tmp / "gone.mp4")]})
    assert data["items"][0]["kind"] == "missing" and "Cannot find" in data["problem"]
    res, _ = _req(s, "POST", "/api/inspect", body={"inputs": "x"})
    assert res.status == 400

    # the action bar reaches the scoring options; an unknown bar is refused
    low = JobRequest.from_json({"inputs": [str(tmp / "a.mp4")], "bar": "low"})
    assert low.options().scoring.min_evidence == 0.3
    normal = JobRequest.from_json({"inputs": [str(tmp / "a.mp4")]})
    assert normal.options().scoring.min_evidence == 0.5
    assert JobRequest.from_json({"inputs": [str(tmp / "a.mp4")], "bar": "x"}).problem()

    # prefs: the last chosen output folder is remembered and offered to the folder picker
    res, data = _req(s, "POST", "/api/prefs", body={"out_dir": str(out)})
    assert res.status == 200
    res, data = _req(s, "GET", "/api/caps")
    assert data["last_out_dir"] == str(out)
    res, data = _req(s, "POST", "/api/pick", body={"kind": "out"})
    assert data["paths"] == [str(tmp / "x")]
    res, _ = _req(s, "POST", "/api/prefs", body={"out_dir": 5})
    assert res.status == 400
    from clip_anything.app.data import Prefs

    pr = Prefs(tmp / "p2.json")
    pr.set(window={"width": 1000, "height": 700})
    assert pr.window() == (1000, 700)
    pr.set(window={"width": 10, "height": 10})
    assert pr.window() is None
