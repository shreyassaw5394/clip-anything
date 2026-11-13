"""Advanced AI mode (`--ai`): one provider abstraction over a local Ollama, OpenAI or Anthropic.

What the AI does, and nothing else: re-rank the top 3N action candidates (0.7 action / 0.3 AI),
a 4-6 word title per clip, a one-line hook for the post text, and - when captions exist - the
single best spoken line to feature as a big "reaction" caption. All prompts live in
`ai_prompts.py`. Every AI text in the report carries `ai_generated: true`.

Plain mode never imports this module. Keys come from the environment or `--ai-key`, live only in
the provider object for the length of the run, and never appear in the report, logs or errors.
Everything degrades to the action-only order with one warning, exactly like vision.py (whose
Ollama client, frame grabber, blend and file renaming are reused here, not copied).

Real-model output is UNVERIFIED on this machine (no Ollama, no API keys): tests use stub servers.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .ai_prompts import HOOK_CHARS, SYSTEM, clip_prompt
from .events import Event, OnEvent, emit
from .report import Report, Stage, Warning
from .vision import (
    OLLAMA_BASE,
    _post_json,
    _rename_clip_files,
    blend,
    grab_frames,
    is_local_base,
    list_models,
    pick_model,
)

OPENAI_BASE = "https://api.openai.com/v1"
ANTHROPIC_BASE = "https://api.anthropic.com/v1"
OPENAI_DEFAULT_MODEL = "gpt-4o-mini"
ANTHROPIC_DEFAULT_MODEL = "claude-haiku-4-5"
ANTHROPIC_VERSION = "2023-06-01"
PREFERRED_TEXT_MODELS = ("llama3.2", "qwen3", "qwen2.5", "gemma3", "llama3.1", "mistral", "phi4")
PROVIDERS = ("auto", "ollama", "openai", "anthropic", "none")
REQUEST_TIMEOUT_S = 30.0
MAX_ITEMS = 30
MAX_CONSECUTIVE_FAILURES = 2
MAX_RESPONSE_BYTES = 1 << 20
MAX_FRAME_BYTES = 200_000  # a 320 px proxy jpeg is ~15 KB; anything larger is not sent
AI_WEIGHT = 0.3
SETUP_HINT = (
    "no AI provider available: run `clip-anything setup` for a local Ollama, or set "
    "OPENAI_API_KEY / ANTHROPIC_API_KEY (or pass --ai-key) and choose --ai-provider"
)


class AIError(Exception):
    """A provider call failed. The message never contains a key."""


@dataclass
class AISettings:
    provider: str = "auto"  # auto | ollama | openai | anthropic | none
    model: str | None = None  # text model (Ollama) or the API model (OpenAI/Anthropic)
    vision_model: str | None = None  # Ollama only; OpenAI/Anthropic models see frames natively
    key: str | None = None  # overrides the environment; never stored
    ollama_base: str = OLLAMA_BASE
    openai_base: str = OPENAI_BASE
    anthropic_base: str = ANTHROPIC_BASE

    def __repr__(self) -> str:  # keep keys out of tracebacks and logs
        return (
            f"AISettings(provider={self.provider!r}, model={self.model!r}, "
            f"vision_model={self.vision_model!r}, key={'set' if self.key else None})"
        )


@dataclass
class Reply:
    score: float | None = None  # 1..10 when frames were rated
    title: str | None = None
    hook: str | None = None
    reaction: str | None = None
    error: str | None = None


@dataclass
class AIOutcome:
    status: str = "skipped"  # ok | partial | skipped | failed
    provider: str = ""
    model: str = ""
    reason: str = ""
    asked: int = 0
    answered: int = 0
    reranked: bool = False
    wall_s: float = 0.0


# ---------------------------------------------------------------- http (stdlib only)


def _remote_base_ok(base: str) -> bool:
    """https anywhere, or plain http only on this machine (stub servers in tests)."""
    try:
        u = urllib.parse.urlsplit(base)
    except ValueError:
        return False
    return u.scheme == "https" or is_local_base(base)


def _post(url: str, payload: dict, headers: dict[str, str], timeout: float) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json", **headers}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            body = resp.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise AIError(f"HTTP {exc.code}") from None
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise AIError(exc.__class__.__name__) from None
    if len(body) > MAX_RESPONSE_BYTES:
        raise AIError("response too large")
    try:
        obj = json.loads(body.decode("utf-8"))
    except ValueError:
        raise AIError("invalid JSON body") from None
    if not isinstance(obj, dict):
        raise AIError("unexpected body")
    return obj


def _b64_frames(frames: list[bytes]) -> list[str]:
    return [base64.b64encode(f).decode("ascii") for f in frames if 0 < len(f) <= MAX_FRAME_BYTES]


# ---------------------------------------------------------------- providers


class Provider:
    """Base: `ask(prompt, frames) -> Reply`. Subclasses only shape the request/response."""

    name = "none"
    model = ""
    vision = False  # True when frames can be sent
    host = ""  # where data goes; "" = this machine

    def ask(self, prompt: str, frames: list[bytes]) -> Reply:  # pragma: no cover - abstract
        raise NotImplementedError

    def disclosure(self, n: int) -> str:
        if not self.host:
            return (
                f"AI mode: {self.model} via Ollama on this machine; nothing left 127.0.0.1. "
                "Titles and hooks are AI-generated (marked ai_generated in report.json)."
            )
        return (
            f"AI mode: frames and spoken lines of {n} candidate moment(s) were sent to "
            f"{self.host} ({self.model}); your key was used for this run only. Titles and "
            "hooks are AI-generated (marked ai_generated in report.json)."
        )


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self, text_model: str | None, vision_model: str | None, base: str = OLLAMA_BASE):
        if not is_local_base(base):
            raise AIError("Ollama base must be a local http URL")
        self.base = base
        self.text_model = text_model or vision_model
        self.vision_model = vision_model
        self.model = self.vision_model or self.text_model or ""
        self.vision = bool(vision_model)

    def ask(self, prompt: str, frames: list[bytes]) -> Reply:
        images = _b64_frames(frames) if self.vision_model else []
        model = self.vision_model if images else self.text_model
        payload = {
            "model": model,
            "system": SYSTEM,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0, "num_predict": 160},
        }
        if images:
            payload["images"] = images
        try:
            data = _post_json(f"{self.base}/api/generate", payload, REQUEST_TIMEOUT_S)
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
            return Reply(error=f"ollama: {exc.__class__.__name__}")
        return parse_reply(data.get("response", ""), need_score=bool(images))


class OpenAIProvider(Provider):
    name = "openai"
    vision = True

    def __init__(self, key: str, model: str | None = None, base: str = OPENAI_BASE):
        if not key:
            raise AIError("OpenAI needs a key")
        if not _remote_base_ok(base):
            raise AIError("OpenAI base must be https")
        self._key = key
        self.base = base.rstrip("/")
        self.model = model or OPENAI_DEFAULT_MODEL
        self.host = urllib.parse.urlsplit(self.base).hostname or "openai"

    def ask(self, prompt: str, frames: list[bytes]) -> Reply:
        content: list[dict] = [{"type": "text", "text": prompt}]
        images = _b64_frames(frames)
        for b in images:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b}", "detail": "low"},
                }
            )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": content},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": 200,
        }
        try:
            data = _post(
                f"{self.base}/chat/completions",
                payload,
                {"Authorization": f"Bearer {self._key}"},
                REQUEST_TIMEOUT_S,
            )
        except AIError as exc:
            return Reply(error=f"openai: {exc}")
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return Reply(error="openai: unexpected response shape")
        return parse_reply(text, need_score=bool(images))


class AnthropicProvider(Provider):
    name = "anthropic"
    vision = True

    def __init__(self, key: str, model: str | None = None, base: str = ANTHROPIC_BASE):
        if not key:
            raise AIError("Anthropic needs a key")
        if not _remote_base_ok(base):
            raise AIError("Anthropic base must be https")
        self._key = key
        self.base = base.rstrip("/")
        self.model = model or ANTHROPIC_DEFAULT_MODEL
        self.host = urllib.parse.urlsplit(self.base).hostname or "anthropic"

    def ask(self, prompt: str, frames: list[bytes]) -> Reply:
        images = _b64_frames(frames)
        content: list[dict] = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": b},
            }
            for b in images
        ]
        content.append({"type": "text", "text": prompt})
        payload = {
            "model": self.model,
            "max_tokens": 200,
            "temperature": 0,
            "system": SYSTEM,
            "messages": [{"role": "user", "content": content}],
        }
        try:
            data = _post(
                f"{self.base}/messages",
                payload,
                {"x-api-key": self._key, "anthropic-version": ANTHROPIC_VERSION},
                REQUEST_TIMEOUT_S,
            )
        except AIError as exc:
            return Reply(error=f"anthropic: {exc}")
        try:
            text = "".join(
                blk.get("text", "") for blk in data["content"] if blk.get("type") == "text"
            )
        except (KeyError, TypeError, AttributeError):
            return Reply(error="anthropic: unexpected response shape")
        return parse_reply(text, need_score=bool(images))


# ---------------------------------------------------------------- parsing


def _clean(value, limit: int) -> str | None:
    if value is None:
        return None
    s = " ".join(str(value).split())
    return s[:limit] or None


def parse_reply(text, need_score: bool) -> Reply:
    """Tolerant parse of the model's JSON (also inside prose or code fences)."""
    if not isinstance(text, str) or not text.strip():
        return Reply(error="empty reply")
    candidates = [text]
    m = re.search(r"\{.*\}", text, flags=re.S)
    if m:
        candidates.append(m.group(0))
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        score = None
        if need_score:  # a score is only meaningful when frames were rated
            try:
                score = min(10.0, max(1.0, float(obj.get("score"))))
            except (TypeError, ValueError):
                return Reply(error="no numeric score")
        title = _clean(obj.get("title"), 60)
        if not title:
            return Reply(error="no title")
        return Reply(
            score=round(score, 2) if score is not None else None,
            title=title,
            hook=_clean(obj.get("hook"), HOOK_CHARS + 40),
            reaction=_clean(obj.get("reaction"), 160),
        )
    return Reply(error="bad JSON")


# ---------------------------------------------------------------- choosing a provider


def pick_text_model(models: list[str], wanted: str | None = None) -> str | None:
    if wanted:
        return pick_model(models, wanted)
    for pref in PREFERRED_TEXT_MODELS:
        for m in models:
            if m == pref or m.split(":", 1)[0] == pref:
                return m
    return models[0] if models else None


def resolve_provider(
    settings: AISettings,
    env: dict[str, str] | None = None,
    *,
    models_fn: Callable[[str], list[str] | None] = list_models,
) -> tuple[Provider | None, str]:
    """(provider, reason). `auto` = Ollama when reachable, else a key found in the environment.
    An explicit provider that is not usable gives (None, why)."""
    env = os.environ if env is None else env
    want = (settings.provider or "auto").lower()
    if want not in PROVIDERS:
        return None, f"unknown --ai-provider {settings.provider!r} (use {', '.join(PROVIDERS)})"
    if want == "none":
        return None, ""
    if want in ("auto", "ollama"):
        models = models_fn(settings.ollama_base) if is_local_base(settings.ollama_base) else None
        if models:
            vis = pick_model(models, settings.vision_model)
            if vis is None and settings.vision_model:
                return None, f"Ollama vision model {settings.vision_model!r} is not installed"
            txt = None
            if settings.model:
                txt = pick_model(models, settings.model)
                if txt is None:
                    return None, f"Ollama model {settings.model!r} is not installed"
            elif vis is None:
                txt = pick_text_model(models)  # a vision model answers text prompts too
            if vis is None and txt is None:
                return None, "Ollama has no usable model (try: ollama pull qwen3-vl:4b)"
            return OllamaProvider(txt, vis, settings.ollama_base), ""
        if want == "ollama":
            return None, "Ollama not reachable at 127.0.0.1:11434 (run `clip-anything setup`)"
    if want in ("auto", "openai"):
        key = (settings.key if want == "openai" else None) or env.get("OPENAI_API_KEY", "")
        if key:
            return OpenAIProvider(key, settings.model, settings.openai_base), ""
        if want == "openai":
            return None, "OpenAI: set OPENAI_API_KEY or pass --ai-key"
    if want in ("auto", "anthropic"):
        key = (settings.key if want == "anthropic" else None) or env.get("ANTHROPIC_API_KEY", "")
        if key:
            return AnthropicProvider(key, settings.model, settings.anthropic_base), ""
        if want == "anthropic":
            return None, "Anthropic: set ANTHROPIC_API_KEY or pass --ai-key"
    return None, SETUP_HINT


# ---------------------------------------------------------------- the pipeline hook


@dataclass
class Reranker:
    """Callable handed to `pipeline.run(..., rerank=...)`: receives the top 3N candidates
    before render, asks the provider once per candidate, blends scores and attaches
    `features["ai"]`. Never raises; `outcome` tells what happened."""

    provider: Provider
    ffmpeg: str
    on_event: OnEvent | None = None
    max_items: int = MAX_ITEMS
    weight: float = AI_WEIGHT
    grab: Callable[..., list[bytes]] = grab_frames
    outcome: AIOutcome = field(default_factory=AIOutcome)

    def __call__(self, cands: list, info, report: Report, transcripts: dict) -> list:
        t0 = time.time()
        try:
            out = self._run(cands, info, transcripts)
        except Exception as exc:  # noqa: BLE001 - optional stage must never kill a run
            msg = f"{exc.__class__.__name__}: {exc}"
            self.outcome = AIOutcome("failed", self.provider.name, self.provider.model, msg)
            out = cands
        self.outcome.wall_s = round(time.time() - t0, 3)
        o = self.outcome
        detail = f"{o.provider} {o.model} {o.answered}/{o.asked}".strip()
        if o.reason:
            detail = f"{detail} ({o.reason})"
        report.stages.append(Stage("ai", o.status, o.wall_s, detail))
        if o.status != "ok":
            report.warnings.append(Warning("ai", o.status, f"{o.reason}; action-only order kept"))
        emit(
            self.on_event,
            Event("ai", "done" if o.answered else "skipped", o.answered, o.asked, "clips"),
        )
        return out

    def _run(self, cands: list, info, transcripts: dict) -> list:
        p = self.provider
        cands = list(cands)
        work = cands[: self.max_items]
        o = self.outcome = AIOutcome("skipped", p.name, p.model, asked=len(work))
        if not work:
            o.reason = "no candidates"
            return cands
        emit(self.on_event, Event("ai", "start", 0, len(work), "clips", message=p.model))
        replies: list[Reply] = []
        streak = 0
        for i, c in enumerate(work):
            frames = self.grab(self.ffmpeg, info.path, c.start, c.end) if p.vision else []
            tr = transcripts.get(c.id) if transcripts else None
            text = tr.text if tr is not None and getattr(tr, "speech", False) else None
            hint = f"action score {c.score:.2f} of 1"
            if p.vision and not frames:
                r = Reply(error="no frames")
            else:
                r = p.ask(clip_prompt(text, bool(frames), hint), frames)
            replies.append(r)
            if r.error:
                streak += 1
                if streak >= MAX_CONSECUTIVE_FAILURES:
                    break
            else:
                streak = 0
                o.answered += 1
            emit(self.on_event, Event("ai", "progress", i + 1, len(work), "clips"))
        replies += [Reply(error="not asked")] * (len(work) - len(replies))
        for c, r in zip(work, replies, strict=True):
            if r.error:
                continue
            c.features["ai"] = {
                "title": r.title,
                "hook": r.hook,
                "reaction": r.reaction or None,
                "score": r.score,
                "provider": p.name,
                "model": p.model,
                "ai_generated": True,
            }
        can_rerank = p.vision and all(r.score is not None for r in replies)
        if can_rerank:
            for c, r in zip(work, replies, strict=True):
                c.components["action"] = c.score
                c.components["ai"] = round((r.score - 1.0) / 9.0, 4)
                c.score = blend(c.score, r.score, self.weight)
            cands.sort(key=lambda c: c.score, reverse=True)
            o.reranked = True
        if o.answered == len(work):
            o.status = "ok"
            if not p.vision:
                o.reason = "text model: titles and hooks only, no re-rank"
        else:
            o.status = "partial" if o.answered else "skipped"
            last = next((r.error for r in reversed(replies) if r.error != "not asked"), None)
            o.reason = f"{o.answered}/{len(work)} answered" + (f" ({last})" if last else "")
        return cands


# ---------------------------------------------------------------- after the run


def sidecar_text(clip) -> str:
    ai = clip.ai or {}
    lines = [ai.get("title") or "", ""]
    if ai.get("hook"):
        lines += [ai["hook"], ""]
    if ai.get("reaction"):
        lines += [f'Reaction line: "{ai["reaction"]}"', ""]
    lines.append(
        f"AI-generated ({ai.get('provider', '?')} {ai.get('model', '')}). Check it before you post."
    )
    return "\n".join(lines).rstrip() + "\n"


def finish_report(report: Report, *, rename: bool = True) -> int:
    """After render: rename clip files to rank + title slug and write a `<clip>.txt` sidecar
    with title / hook / reaction for every clip that has AI text. Returns sidecars written."""
    if not any(c.ai for c in report.clips):
        return 0
    if rename:
        try:
            _rename_clip_files(report)
        except OSError as exc:
            report.warnings.append(Warning("ai", "rename", f"could not rename: {exc}"))
    n = 0
    for c in report.clips:
        if not c.ai or not c.path or not Path(c.path).exists():
            continue
        side = Path(c.path).with_suffix(".txt")
        try:
            side.write_text(sidecar_text(c), encoding="utf-8")
            c.ai["text_path"] = str(side)
            n += 1
        except OSError as exc:
            report.warnings.append(Warning("ai", "sidecar", f"could not write {side.name}: {exc}"))
    return n
