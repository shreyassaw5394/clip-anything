"""vision.py against a stub Ollama on 127.0.0.1 (Ollama itself is not installed here)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from clip_anything import vision
from clip_anything.probe import preflight
from clip_anything.report import Clip, Report


class _Stub:
    """Minimal /api/tags + /api/generate. `behaviour` = ok | bad_json | hang | error."""

    def __init__(self, models: list[str], behaviour: str = "ok"):
        self.models = models
        self.behaviour = behaviour
        self.requests: list[dict] = []
        stub = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silence
                pass

            def _send(self, code: int, obj: dict):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/api/tags":
                    self._send(200, {"models": [{"name": m} for m in stub.models]})
                else:
                    self._send(404, {})

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(n))
                stub.requests.append(payload)
                if stub.behaviour == "hang":
                    threading.Event().wait(3.0)
                    self._send(200, {"response": ""})
                    return
                if stub.behaviour == "error":
                    self._send(500, {"error": "boom"})
                    return
                if stub.behaviour == "bad_json":
                    self._send(200, {"response": "Sure! The score is high."})
                    return
                # score grows with how many images arrived; title echoes the index
                k = len(stub.requests)
                score = 3 if k % 2 else 9
                self._send(
                    200,
                    {"response": json.dumps({"score": score, "title": f"Big moment number {k}"})},
                )

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def stub():
    servers = []

    def make(models, behaviour="ok"):
        s = _Stub(models, behaviour)
        servers.append(s)
        return s

    yield make
    for s in servers:
        s.close()


def _report(n: int) -> Report:
    r = Report(input={"path": "game.mp4"}, options={})
    for i in range(n):
        r.clips.append(
            Clip(
                rank=i + 1,
                candidate_id=i,
                start=10.0 + 60 * i,
                end=30.0 + 60 * i,
                duration_s=20.0,
                score=round(0.9 - 0.1 * i, 4),
                components={"loud_rel": 0.5},
                status="skipped",
            )
        )
    return r


def test_pick_model_preference_and_hints():
    assert vision.pick_model(["llama3:8b", "gemma3:4b", "qwen3-vl:4b"]) == "qwen3-vl:4b"
    assert vision.pick_model(["llama3:8b", "llava:7b"]) == "llava:7b"
    assert vision.pick_model(["llama3:8b"]) is None
    assert vision.pick_model(["moondream:latest"], "moondream") == "moondream:latest"
    assert vision.pick_model(["moondream:latest"], "gemma3") is None


def test_parse_reply_tolerant():
    assert vision.parse_reply('{"score": 7, "title": "Clutch  win"}').title == "Clutch win"
    assert vision.parse_reply('text {"score": "12"} more').score == 10.0
    assert vision.parse_reply("nonsense").error == "bad JSON"
    assert vision.parse_reply("").error == "empty reply"
    assert vision.parse_reply('{"title": "x"}').error == "no numeric score"


def test_blend_and_slug():
    assert vision.blend(0.5, None) == 0.5
    assert vision.blend(0.5, 10) == pytest.approx(0.65)
    assert vision.blend(0.5, 1) == pytest.approx(0.35)
    assert vision.slug("Big Moment: Number 1!") == "big-moment-number-1"


def test_sample_times_inside_clip():
    ts = vision.sample_times(10.0, 30.0)
    assert len(ts) == 4 and all(10.0 < t < 30.0 for t in ts)


def test_no_ollama_degrades_silently():
    # nothing listens on this port
    out = vision.score_spans([(0, 10)], "x.mp4", "ffmpeg", base="http://127.0.0.1:9")
    assert out.status == "skipped" and out.model is None
    r = _report(2)
    before = [(c.rank, c.score) for c in r.clips]
    out = vision.rerank_report(r, "x.mp4", "ffmpeg", base="http://127.0.0.1:9")
    assert not out.reranked
    assert [(c.rank, c.score) for c in r.clips] == before
    assert [s.name for s in r.stages] == ["vision"] and r.stages[0].status == "skipped"
    assert len(r.warnings) == 1 and "action-only" in r.warnings[0].message


def test_no_vision_model_skips(stub):
    s = stub(["llama3:8b"])
    out = vision.score_spans([(0, 10)], "x.mp4", "ffmpeg", base=s.base)
    assert out.status == "skipped" and "no vision model" in out.reason
    assert s.requests == []


def test_rerank_with_stub_frames(stub, synth_video, monkeypatch):
    s = stub(["qwen3-vl:4b"])
    ffmpeg = preflight().ffmpeg
    r = _report(3)
    out = vision.rerank_report(r, synth_video, ffmpeg, base=s.base, rename_files=False)
    assert out.status == "ok" and out.model == "qwen3-vl:4b" and out.reranked
    assert len(s.requests) == 3
    req = s.requests[0]
    assert req["model"] == "qwen3-vl:4b" and req["format"] == "json" and req["stream"] is False
    assert len(req["images"]) == 4  # 4 real proxy jpegs from the synthetic video
    # stub gives 3,9,3 -> clip 2 (action 0.8) overtakes clip 1 (0.9): 0.7*0.8+0.3*0.889 = 0.827
    assert r.clips[0].candidate_id == 1 and r.clips[0].rank == 1
    assert r.clips[0].score == pytest.approx(0.8267, abs=1e-3)
    assert r.clips[0].title == "Big moment number 2" and r.clips[0].vision_score == 9
    assert all(c.components["action"] > 0 and "vision" in c.components for c in r.clips)
    assert r.stages[-1].name == "vision" and r.stages[-1].status == "ok"
    assert r.warnings == []


def test_bad_json_keeps_action_order(stub, synth_video):
    s = stub(["gemma3:4b"], "bad_json")
    ffmpeg = preflight().ffmpeg
    r = _report(3)
    out = vision.rerank_report(r, synth_video, ffmpeg, base=s.base)
    assert out.status == "skipped" and not out.reranked
    assert len(s.requests) == 2  # stops after two consecutive failures
    assert [c.candidate_id for c in r.clips] == [0, 1, 2]
    assert all(c.title is None for c in r.clips)
    assert r.warnings[0].stage == "vision" and "bad JSON" in r.warnings[0].message


def test_timeout_keeps_action_order(stub, synth_video, monkeypatch):
    s = stub(["gemma3:4b"], "hang")
    monkeypatch.setattr(vision, "GENERATE_TIMEOUT_S", 0.5)
    ffmpeg = preflight().ffmpeg
    r = _report(2)
    out = vision.rerank_report(r, synth_video, ffmpeg, base=s.base)
    assert out.status == "skipped" and not out.reranked
    assert [c.candidate_id for c in r.clips] == [0, 1]


def test_rename_files_two_phase(tmp_path, stub, synth_video):
    s = stub(["qwen3-vl:4b"])
    ffmpeg = preflight().ffmpeg
    r = _report(2)
    r.input = {"path": str(synth_video)}
    from clip_anything.render import clip_filename

    for c in r.clips:
        p = tmp_path / clip_filename(synth_video.stem, c.rank, c.start)
        p.write_bytes(b"x")
        c.path, c.status = str(p), "ok"
    vision.rerank_report(r, synth_video, ffmpeg, base=s.base)
    # stub: clip 1 -> 3, clip 2 -> 9: order swaps, files follow the new ranks + slugs
    assert r.clips[0].candidate_id == 1
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == sorted(
        [
            "synth_01_01-10_big-moment-number-2.mp4",
            "synth_02_00-10_big-moment-number-1.mp4",
        ]
    )
    assert all(Path(c.path).exists() for c in r.clips)


def test_internal_error_becomes_warning(stub, synth_video, monkeypatch):
    s = stub(["qwen3-vl:4b"])
    monkeypatch.setattr(vision, "_rename_clip_files", lambda r: 1 / 0)
    r = _report(2)
    out = vision.rerank_report(r, synth_video, preflight().ffmpeg, base=s.base)
    assert out.status == "skipped" and r.stages[-1].status == "failed"
    assert "ZeroDivisionError" in r.warnings[-1].message


def test_vision_base_must_be_local(tmp_path):
    from clip_anything.vision import is_local_base, score_spans

    assert is_local_base("http://127.0.0.1:11434")
    assert is_local_base("http://localhost:11434")
    assert not is_local_base("https://127.0.0.1:11434")
    assert not is_local_base("http://example.com:11434")
    out = score_spans([(0.0, 1.0)], tmp_path / "x.mp4", "ffmpeg", base="http://example.com")
    assert out.status == "skipped" and "local" in out.reason
