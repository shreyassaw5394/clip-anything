"""ai.py against stub HTTP servers on 127.0.0.1 for all three providers. No Ollama and no API
keys exist on the test machine: real-model behaviour is unverified by design."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from clip_anything import ai
from clip_anything.captions import build_ass, reaction_span
from clip_anything.config import SpeechOptions
from clip_anything.report import Clip, Report
from clip_anything.scoring import Candidate
from clip_anything.speech import Transcript, Word

GOOD = {"score": 9, "title": "Clutch Triple Kill", "hook": "He had no idea.", "reaction": "no way"}


class _Stub:
    """One server that speaks Ollama (/api/tags, /api/generate), OpenAI (/v1/chat/completions)
    and Anthropic (/v1/messages). `behaviour` = ok | bad_json | error | hang | huge."""

    def __init__(self, models=("qwen3-vl:4b",), behaviour="ok"):
        self.models = list(models)
        self.behaviour = behaviour
        self.requests: list[tuple[str, dict, dict]] = []  # path, headers, payload
        stub = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj=None, raw=None):
                body = raw if raw is not None else json.dumps(obj).encode()
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
                stub.requests.append(
                    (self.path, {k.lower(): v for k, v in self.headers.items()}, payload)
                )
                k = len(stub.requests)
                if stub.behaviour == "hang":
                    threading.Event().wait(2.0)
                if stub.behaviour == "error":
                    return self._send(500, {"error": "boom"})
                if stub.behaviour == "huge":
                    return self._send(200, raw=b"{" + b" " * (ai.MAX_RESPONSE_BYTES + 10) + b"}")
                text = (
                    "Sure thing!"
                    if stub.behaviour == "bad_json"
                    else json.dumps(
                        {**GOOD, "score": 3 if k % 2 else 9, "title": f"Big moment number {k}"}
                    )
                )
                if self.path == "/api/generate":
                    return self._send(200, {"response": text})
                if self.path.endswith("/chat/completions"):
                    if "Bearer " not in self.headers.get("Authorization", ""):
                        return self._send(401, {"error": "no key"})
                    return self._send(200, {"choices": [{"message": {"content": text}}]})
                if self.path.endswith("/messages"):
                    if not self.headers.get("x-api-key") or not self.headers.get(
                        "anthropic-version"
                    ):
                        return self._send(401, {"error": "no key"})
                    return self._send(200, {"content": [{"type": "text", "text": text}]})
                self._send(404, {})

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def stub():
    made = []

    def make(*a, **kw):
        s = _Stub(*a, **kw)
        made.append(s)
        return s

    yield make
    for s in made:
        s.close()


FRAME = b"\xff\xd8" + b"\x00" * 64  # pretend jpeg
_WORDS = [
    Word(0.5, 0.8, "oh"),
    Word(0.8, 1.1, "no"),
    Word(1.1, 1.5, "way!"),
    Word(2.0, 2.4, "lets"),
    Word(2.4, 2.9, "go"),
]


def _cands(n=3):
    return [
        Candidate(
            id=i,
            peak_t=20.0 + 60 * i,
            score=round(0.9 - 0.1 * i, 4),
            prominence=0.1,
            components={"loud_rel": 0.5},
            start=10.0 + 60 * i,
            end=30.0 + 60 * i,
        )
        for i in range(n)
    ]


class _Info:
    path = "game.mp4"


def _fake_grab(ffmpeg, video, start, end):
    return [FRAME] * 4


# ---------------------------------------------------------------- providers: request shaping


def test_ollama_provider_sends_frames_and_system(stub):
    s = stub(["llama3.2:3b", "qwen3-vl:4b"])
    p, why = ai.resolve_provider(ai.AISettings(provider="ollama", ollama_base=s.base), env={})
    assert p is not None and why == "" and p.name == "ollama" and p.vision
    assert p.vision_model == "qwen3-vl:4b" and p.model == "qwen3-vl:4b"
    r = p.ask("prompt", [FRAME, FRAME])
    path, _h, payload = s.requests[0]
    assert path == "/api/generate" and payload["model"] == "qwen3-vl:4b"
    assert len(payload["images"]) == 2 and payload["format"] == "json" and payload["system"]
    assert r.score == 3 and r.title == "Big moment number 1" and r.hook == GOOD["hook"]


def test_ollama_text_only_model_has_no_vision(stub):
    s = stub(["llama3.2:3b"])
    p, _ = ai.resolve_provider(ai.AISettings(provider="auto", ollama_base=s.base), env={})
    assert p.name == "ollama" and not p.vision and p.model == "llama3.2:3b"
    r = p.ask("prompt", [FRAME])
    assert "images" not in s.requests[0][2]
    assert r.error is None and r.score is None and r.title


def test_openai_provider_shapes_chat_completion(stub):
    s = stub()
    p, why = ai.resolve_provider(
        ai.AISettings(provider="openai", key="sk-test", openai_base=s.base), env={}
    )
    assert p is not None and p.name == "openai" and p.model == ai.OPENAI_DEFAULT_MODEL
    r = p.ask("prompt", [FRAME])
    path, headers, payload = s.requests[0]
    assert path == "/chat/completions" and headers["authorization"] == "Bearer sk-test"
    assert payload["response_format"] == {"type": "json_object"}
    user = payload["messages"][1]["content"]
    assert user[0] == {"type": "text", "text": "prompt"}
    assert user[1]["type"] == "image_url"
    assert user[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert payload["messages"][0]["role"] == "system"
    assert r.score == 3 and r.title == "Big moment number 1"


def test_anthropic_provider_shapes_messages(stub):
    s = stub()
    p, _ = ai.resolve_provider(
        ai.AISettings(provider="anthropic", model="claude-x", anthropic_base=s.base),
        env={"ANTHROPIC_API_KEY": "ak-test"},
    )
    assert p.name == "anthropic" and p.model == "claude-x"
    r = p.ask("prompt", [FRAME, FRAME])
    path, headers, payload = s.requests[0]
    assert path == "/messages" and headers["x-api-key"] == "ak-test"
    assert headers["anthropic-version"] == ai.ANTHROPIC_VERSION
    content = payload["messages"][0]["content"]
    assert [c["type"] for c in content] == ["image", "image", "text"]
    assert content[0]["source"]["media_type"] == "image/jpeg"
    assert payload["system"] and payload["max_tokens"] > 0
    assert r.score == 3 and r.reaction == "no way"


def test_key_never_leaks_in_repr_or_errors(stub):
    s = stub(behaviour="error")
    settings = ai.AISettings(provider="openai", key="sk-SECRET", openai_base=s.base)
    assert "sk-SECRET" not in repr(settings) and "set" in repr(settings)
    p, _ = ai.resolve_provider(settings, env={})
    r = p.ask("prompt", [])
    assert r.error == "openai: HTTP 500" and "SECRET" not in repr(r)
    assert "SECRET" not in p.disclosure(3) and "SECRET" not in repr(settings)


def test_remote_bases_must_be_https_unless_local():
    with pytest.raises(ai.AIError):
        ai.OpenAIProvider("k", base="http://api.example.com/v1")
    with pytest.raises(ai.AIError):
        ai.AnthropicProvider("k", base="http://10.0.0.5/v1")
    with pytest.raises(ai.AIError):
        ai.OllamaProvider("m", None, base="http://10.0.0.5:11434")
    assert ai.OpenAIProvider("k", base="https://api.openai.com/v1").host == "api.openai.com"


# ---------------------------------------------------------------- resolve + parse


def test_resolve_auto_prefers_ollama_then_env_keys(stub):
    s = stub(["gemma3:4b"])
    p, _ = ai.resolve_provider(ai.AISettings(ollama_base=s.base), env={"OPENAI_API_KEY": "sk-x"})
    assert p.name == "ollama"
    dead = ai.AISettings(ollama_base="http://127.0.0.1:9")
    assert ai.resolve_provider(dead, env={"OPENAI_API_KEY": "sk-x"})[0].name == "openai"
    assert ai.resolve_provider(dead, env={"ANTHROPIC_API_KEY": "a"})[0].name == "anthropic"
    p, why = ai.resolve_provider(dead, env={})
    assert p is None and "clip-anything setup" in why
    assert ai.resolve_provider(ai.AISettings(provider="none"), env={}) == (None, "")
    p, why = ai.resolve_provider(ai.AISettings(provider="ollama", ollama_base=dead.ollama_base))
    assert p is None and "not reachable" in why
    p, why = ai.resolve_provider(ai.AISettings(provider="openai"), env={})
    assert p is None and "OPENAI_API_KEY" in why
    p, why = ai.resolve_provider(ai.AISettings(provider="bogus"), env={})
    assert p is None and "unknown" in why
    p, why = ai.resolve_provider(
        ai.AISettings(provider="ollama", vision_model="moondream", ollama_base=s.base), env={}
    )
    assert p is None and "not installed" in why


def test_parse_reply_tolerant():
    r = ai.parse_reply('```json\n{"score": "12", "title": " Big  win ", "hook": "x"}\n```', True)
    assert r.score == 10 and r.title == "Big win" and r.hook == "x" and r.reaction is None
    assert ai.parse_reply('{"title": "t"}', need_score=True).error == "no numeric score"
    assert ai.parse_reply('{"title": "t"}', need_score=False).title == "t"
    assert ai.parse_reply('{"score": 5}', need_score=True).error == "no title"
    assert ai.parse_reply("nope", True).error == "bad JSON"
    assert ai.parse_reply("", True).error == "empty reply"


# ---------------------------------------------------------------- the pipeline hook


def _rerank(stub_server, provider_settings, cands, transcripts=None, env=None):
    p, why = ai.resolve_provider(provider_settings, env=env or {})
    assert p is not None, why
    rr = ai.Reranker(p, "ffmpeg", grab=_fake_grab)
    report = Report(input={"path": "game.mp4"}, options={})
    out = rr(cands, _Info(), report, transcripts or {})
    return rr, report, out


def test_reranker_blends_and_attaches_ai(stub):
    s = stub(["qwen3-vl:4b"])
    cands = _cands(3)
    rr, report, out = _rerank(s, ai.AISettings(ollama_base=s.base), cands)
    assert rr.outcome.status == "ok" and rr.outcome.reranked and len(s.requests) == 3
    # stub: 3, 9, 3 -> candidate 1 (0.8 action) overtakes 0 (0.9): 0.7*0.8+0.3*0.889
    assert out[0].id == 1 and out[0].score == pytest.approx(0.8267, abs=1e-3)
    assert out[0].features["ai"]["title"] == "Big moment number 2"
    assert out[0].features["ai"]["ai_generated"] is True and "action" in out[0].components
    assert report.stages[-1].name == "ai" and report.stages[-1].status == "ok"
    assert report.warnings == []


def test_reranker_text_model_titles_without_rerank(stub):
    s = stub(["llama3.2:3b"])
    cands = _cands(2)
    rr, report, out = _rerank(s, ai.AISettings(ollama_base=s.base), cands)
    assert rr.outcome.status == "ok" and not rr.outcome.reranked
    assert [c.id for c in out] == [0, 1] and all("ai" in c.features for c in out)
    assert "no re-rank" in report.stages[-1].detail and report.warnings == []


def test_reranker_passes_transcript_lines_only_when_speech(stub):
    s = stub(["qwen3-vl:4b"])
    tr = Transcript(words=_WORDS, speech=True)
    quiet = Transcript(words=_WORDS, speech=False)
    _rerank(s, ai.AISettings(ollama_base=s.base), _cands(2), {0: tr, 1: quiet})
    assert "oh no way!" in s.requests[0][2]["prompt"]
    assert "Nothing was spoken" in s.requests[1][2]["prompt"]
    assert "game.mp4" not in s.requests[0][2]["prompt"]


@pytest.mark.parametrize("behaviour", ["bad_json", "error", "huge"])
def test_reranker_degrades_keeps_action_order(stub, behaviour):
    s = stub(["qwen3-vl:4b"], behaviour)
    cands = _cands(4)
    rr, report, out = _rerank(s, ai.AISettings(ollama_base=s.base), cands)
    assert rr.outcome.status == "skipped" and not rr.outcome.reranked
    assert len(s.requests) == 2  # two consecutive failures stop the pass
    assert [c.id for c in out] == [0, 1, 2, 3] and all("ai" not in c.features for c in out)
    assert report.warnings[0].stage == "ai" and "action-only" in report.warnings[0].message


def test_reranker_timeout_degrades(stub, monkeypatch):
    s = stub(behaviour="hang")
    monkeypatch.setattr(ai, "REQUEST_TIMEOUT_S", 0.3)
    p, _ = ai.resolve_provider(ai.AISettings(provider="openai", key="k", openai_base=s.base))
    rr = ai.Reranker(p, "ffmpeg", grab=_fake_grab)
    out = rr(_cands(2), _Info(), Report(input={}, options={}), {})
    assert rr.outcome.status == "skipped" and [c.id for c in out] == [0, 1]
    assert "timeout" in rr.outcome.reason.lower() or "timed" in rr.outcome.reason.lower()


def test_reranker_internal_error_is_a_warning(stub):
    s = stub()
    p, _ = ai.resolve_provider(ai.AISettings(provider="openai", key="k", openai_base=s.base))

    def boom(*a):
        raise RuntimeError("frame grabber died")

    rr = ai.Reranker(p, "ffmpeg", grab=boom)
    report = Report(input={}, options={})
    out = rr(_cands(2), _Info(), report, {})
    assert [c.id for c in out] == [0, 1] and report.stages[-1].status == "failed"
    assert "RuntimeError" in report.warnings[-1].message


def test_pipeline_run_calls_rerank_before_render(synth_video, tmp_path, stub):
    from clip_anything.config import Options
    from clip_anything.pipeline import run

    s = stub(["qwen3-vl:4b"])
    p, _ = ai.resolve_provider(ai.AISettings(ollama_base=s.base))
    seen = {}

    class Spy(ai.Reranker):
        def __call__(self, cands, info, report, transcripts):
            seen["n"] = len(cands)
            return super().__call__(cands, info, report, transcripts)

    rr = Spy(p, "ffmpeg", grab=_fake_grab)
    opts = Options.from_layers(
        {
            "clips": {"count": 2},
            "render": {"out_dir": str(tmp_path), "dry_run": True},
            "analysis": {"cache": False},
        }
    )
    report = run(synth_video, opts, rerank=rr)
    assert seen["n"] > 2  # the hook saw more than N candidates (up to 3N)
    assert len(report.clips) == 2 and all(c.ai and c.title for c in report.clips)
    assert [s_.name for s_ in report.stages if s_.name == "ai"] == ["ai"]
    data = json.loads((tmp_path / "report.json").read_text())
    assert data["clips"][0]["ai"]["ai_generated"] is True


# ---------------------------------------------------------------- after the run


def test_finish_report_renames_and_writes_sidecars(tmp_path):
    from clip_anything.render import clip_filename

    r = Report(input={"path": str(tmp_path / "game.mp4")}, options={})
    for i in range(2):
        p = tmp_path / clip_filename("game", i + 1, 10.0 + 60 * i)
        p.write_bytes(b"x")
        r.clips.append(
            Clip(
                rank=i + 1,
                candidate_id=i,
                start=10.0 + 60 * i,
                end=30.0 + 60 * i,
                duration_s=20.0,
                score=0.5,
                status="ok",
                path=str(p),
                title="Clutch Triple Kill" if i == 0 else None,
                ai={
                    "title": "Clutch Triple Kill",
                    "hook": "He had no idea.",
                    "reaction": "no way",
                    "provider": "ollama",
                    "model": "m",
                    "ai_generated": True,
                }
                if i == 0
                else None,
            )
        )
    assert ai.finish_report(r) == 1
    names = sorted(p.name for p in tmp_path.iterdir())
    assert "game_01_00-10_clutch-triple-kill.mp4" in names
    assert "game_01_00-10_clutch-triple-kill.txt" in names
    assert "game_02_01-10.mp4" in names
    text = Path(r.clips[0].ai["text_path"]).read_text()
    assert text.startswith("Clutch Triple Kill\n") and "He had no idea." in text
    assert 'Reaction line: "no way"' in text and "AI-generated" in text
    assert ai.finish_report(Report(input={}, options={})) == 0


# ---------------------------------------------------------------- reaction caption


def test_reaction_span_and_big_caption():
    assert reaction_span(_WORDS, "No way") == pytest.approx((0.8, 1.9))
    assert reaction_span(_WORDS, "lets go!") == pytest.approx((2.0, 3.3))
    assert reaction_span(_WORDS, "never said") is None
    assert reaction_span([], "no") is None
    text = build_ass(_WORDS, SpeechOptions(), 1080, 1920, 20.0, reaction="no way")
    assert "Style: Big," in text and "Dialogue: 1,0:00:00.80,0:00:01.90,Big,,0,0,0,,NO WAY" in text
    plain = build_ass(_WORDS, SpeechOptions(), 1080, 1920, 20.0)
    assert ",Big,," not in plain
    unfaithful = build_ass(_WORDS, SpeechOptions(), 1080, 1920, 20.0, reaction="made up")
    assert ",Big,," not in unfaithful
