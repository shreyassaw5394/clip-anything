"""Jobs for the app server: a request dataclass that becomes `Options`, one worker thread per
job around `pipeline.run`, a replayable event log for Server-Sent Events, and the result shaping
(clip rows with a why-picked line and post text). No HTTP here; tested headless."""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..events import Event
from ..gui import STAGE_LABELS, ProgressModel, captions_available, friendly_error

LENGTHS = {"short": (15.0, 30.0), "normal": (15.0, 45.0), "long": (30.0, 60.0)}
MAX_COUNT = 20
WHY_WORDS = (
    ("loud_rel", 0.35, "a loud burst"),
    ("onset", 0.35, "a sudden sound"),
    ("motion", 0.35, "fast motion"),
    ("cut", 0.5, "quick cuts"),
    ("rms_db", 0.5, "sustained noise"),
)


@dataclass
class JobRequest:
    inputs: list[str] = field(default_factory=list)
    out_dir: str = ""
    count: int = 10
    length: str = "normal"  # short | normal | long
    captions: bool = True
    facecam: str = "auto"  # auto | off
    crop: str = "follow"  # follow | center
    ai: bool = False
    ai_provider: str = "auto"  # auto | ollama | openai | anthropic

    @classmethod
    def from_json(cls, data: dict) -> JobRequest:
        """Strict parse of the POST body: unknown keys ignored, wrong types rejected."""
        if not isinstance(data, dict):
            raise ValueError("body must be an object")
        inputs = data.get("inputs", [])
        if not isinstance(inputs, list) or not all(isinstance(p, str) for p in inputs):
            raise ValueError("inputs must be a list of paths")
        req = cls(inputs=[p for p in inputs if p][:200])
        req.out_dir = str(data.get("out_dir") or "")
        try:
            req.count = int(data.get("count", 10))
        except (TypeError, ValueError):
            raise ValueError("count must be a number") from None
        req.length = str(data.get("length", "normal"))
        req.captions = bool(data.get("captions", True))
        req.facecam = str(data.get("facecam", "auto"))
        req.crop = str(data.get("crop", "follow"))
        req.ai = bool(data.get("ai", False))
        req.ai_provider = str(data.get("ai_provider", "auto"))
        return req

    def problem(self) -> str | None:
        if not self.inputs:
            return "Choose a recording (or a folder of recordings) first."
        missing = [p for p in self.inputs if not Path(p).exists()]
        if missing:
            return f"Cannot find: {missing[0]}"
        if not self.out_dir:
            return "Choose where the clips should go."
        if not 1 <= self.count <= MAX_COUNT:
            return f"Number of clips must be between 1 and {MAX_COUNT}."
        if self.length not in LENGTHS:
            return "Unknown clip length."
        if self.facecam not in ("auto", "off") or self.crop not in ("follow", "center"):
            return "Unknown layout option."
        if self.ai_provider not in ("auto", "ollama", "openai", "anthropic"):
            return "Unknown AI provider."
        return None

    def default_out_dir(self) -> str:
        if not self.inputs:
            return ""
        first = Path(self.inputs[0])
        base = first if first.is_dir() else first.parent
        return str(base / "clips")

    def layers(self) -> dict:
        want_captions = bool(self.captions and captions_available())
        lo, hi = LENGTHS[self.length]
        return {
            "clips": {"count": self.count, "min_s": lo, "max_s": hi},
            "render": {"out_dir": self.out_dir, "force": True},
            "speech": {"captions": want_captions, "yes": want_captions},
            "layout": {"facecam": self.facecam, "crop": self.crop},
        }

    def options(self):
        from ..config import Options

        return Options.from_layers(self.layers())


def default_runner(target, opts, on_event, cancel, rerank=None):
    from ..pipeline import run

    return run(target, opts, on_event=on_event, cancel=cancel, rerank=rerank)


class Job:
    """One run. `events` is the full log (replayed to late SSE subscribers); `cond` wakes
    the streaming threads."""

    def __init__(self, request: JobRequest, runner: Callable | None = None) -> None:
        self.id = uuid.uuid4().hex
        self.request = request
        self.runner = runner or default_runner
        self.state = "queued"  # queued | running | done | error | cancelled
        self.created = time.time()
        self.finished: float | None = None
        self.events: list[dict] = []
        self.cond = threading.Condition()
        self.cancel_event = threading.Event()
        self.model = ProgressModel()
        self.report = None
        self.error = ""
        self.warnings: list[str] = []
        self.disclosure = ""
        self.ai_cloud = False
        self._reranker = None
        self.thread: threading.Thread | None = None

    # -- lifecycle --
    def prepare_ai(self) -> str | None:
        """Resolve the AI provider now (fail fast). Returns a problem text or None."""
        if not self.request.ai:
            return None
        from ..ai import AISettings, Reranker, resolve_provider
        from ..probe import preflight

        provider, why = resolve_provider(AISettings(provider=self.request.ai_provider))
        if provider is None:
            return f"AI mode is not ready: {why}"
        self._reranker = Reranker(provider, preflight().ffmpeg)
        self.disclosure = provider.disclosure(self.request.count * 3)
        self.ai_cloud = bool(getattr(provider, "host", ""))
        return None

    def start(self) -> None:
        self.state = "running"
        self.thread = threading.Thread(target=self._work, name=f"job-{self.id[:8]}", daemon=True)
        self.thread.start()

    def _work(self) -> None:
        req = self.request
        target = req.inputs[0] if len(req.inputs) == 1 else list(req.inputs)
        try:
            report = self.runner(
                target, req.options(), self._on_event, self.cancel_event, self._reranker
            )
            if self._reranker is not None:
                from ..ai import finish_report

                if finish_report(report) and report.report_path:
                    report.write(report.report_path)
        except Exception as exc:  # noqa: BLE001 - every failure becomes a message
            self.report = None
            if self.cancel_event.is_set():
                self._finish("cancelled")
            else:
                self.error = friendly_error(exc)
                self._finish("error")
            return
        self.report = report
        self._finish("cancelled" if self.cancel_event.is_set() else "done")

    def _finish(self, state: str) -> None:
        self.finished = time.time()
        self.state = state
        self._push({"kind": "finished", "state": state, "error": self.error})

    def _on_event(self, ev: Event) -> None:
        p = self.model.update(ev)
        if ev.kind == "warn":
            self.warnings.append(f"{ev.stage}: {ev.message}")
        self._push(
            {
                "kind": ev.kind,
                "stage": ev.stage,
                "done": ev.done,
                "total": ev.total,
                "unit": ev.unit,
                "message": ev.message,
                "extra": ev.extra,
                "fraction": round(p.fraction, 4),
                "label": p.label,
                "detail": p.detail,
            }
        )

    def _push(self, data: dict) -> None:
        with self.cond:
            data["seq"] = len(self.events)
            data["t"] = round(time.time() - self.created, 2)
            self.events.append(data)
            self.cond.notify_all()

    def cancel(self) -> None:
        self.cancel_event.set()

    @property
    def running(self) -> bool:
        return self.state in ("queued", "running")

    def wait_events(self, since: int, timeout: float) -> list[dict]:
        """Events with seq >= since, blocking up to `timeout` for new ones (SSE loop)."""
        with self.cond:
            if len(self.events) <= since:
                self.cond.wait(timeout)
            return self.events[since:]

    # -- results --
    def out_dir(self) -> Path | None:
        d = self.report.out_dir if self.report and self.report.out_dir else self.request.out_dir
        return Path(d).resolve() if d else None

    def status(self) -> dict:
        last = self.events[-1] if self.events else {}
        return {
            "id": self.id,
            "state": self.state,
            "request": asdict(self.request),
            "fraction": last.get("fraction", 0.0),
            "label": last.get("label", ""),
            "detail": last.get("detail", ""),
            "elapsed": round((self.finished or time.time()) - self.created, 1),
            "warnings": self.warnings,
            "error": self.error,
            "disclosure": self.disclosure,
            "ai_cloud": self.ai_cloud,
            "seq": len(self.events),
            "result": self.result() if self.report is not None else None,
        }

    def result(self) -> dict:
        r = self.report
        out = self.out_dir()
        clips = []
        for c in r.clips:
            name = os.path.basename(c.path) if c.path else ""
            inside = bool(out and c.path and Path(c.path).resolve().parent == out)
            clips.append(
                {
                    "rank": c.rank,
                    "start": c.start,
                    "end": c.end,
                    "duration_s": c.duration_s,
                    "score": c.score,
                    "status": c.status,
                    "error": c.error,
                    "file": name if inside else "",
                    "source": os.path.basename(c.source) if c.source else "",
                    "layout": c.layout,
                    "captions": bool(c.captions),
                    "why": why_line(c),
                    "title": (c.ai or {}).get("title") or c.title,
                    "hook": (c.ai or {}).get("hook"),
                    "post": post_text(c),
                }
            )
        return {
            "out_dir": str(out) if out else "",
            "report_file": "report.json" if r.report_path else "",
            "clips": clips,
            "ok": len(r.ok_clips),
            "total": len(r.clips),
            "candidates": r.candidates_total,
            "input": {
                "duration_s": r.input.get("duration_s"),
                "name": os.path.basename(str(r.input.get("path", ""))) or r.input.get("files", ""),
            },
            "timings": r.timings,
            "warnings": [f"{w.stage}: {w.message}" for w in r.warnings],
            "cached": any(s.status == "cached" for s in r.stages),
        }


def why_line(clip) -> str:
    """One plain sentence from the components: what made this moment score."""
    comps = clip.components or {}
    parts = [word for key, floor, word in WHY_WORDS if comps.get(key, 0.0) >= floor][:2]
    speech = clip.speech or {}
    if speech.get("shouts"):
        parts.append("shouting")
    elif speech.get("phrases"):
        parts.append("excited speech")
    if comps.get("agree", 0.0) >= 0.5 and len(parts) >= 2:
        text = f"{parts[0]} and {parts[1]} at the same time"
        if len(parts) > 2:
            text += f", plus {parts[2]}"
    elif parts:
        text = ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1]
        text = text[0].upper() + text[1:]
    else:
        text = "Above the action bar"
    if clip.status == "failed":
        return f"Render failed: {clip.error or 'unknown error'}"
    return text


def post_text(clip) -> str:
    """Text for the clipboard: the AI title/hook when there is one, else time and reason."""
    if clip.ai:
        from ..ai import sidecar_text

        return sidecar_text(clip)
    m, s = divmod(int(clip.start), 60)
    return f"{why_line(clip)} at {m:02d}:{s:02d} in the recording.\n"


def stage_label(stage: str) -> str:
    return STAGE_LABELS.get(stage, stage.title())
