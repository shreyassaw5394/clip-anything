"""Optional vision re-rank + titles via a local Ollama (step 9). Degrades silently.

Talks only to http://127.0.0.1:11434 with stdlib urllib: GET /api/tags (1 s) to find a vision
model, then POST /api/generate per clip with 3-4 small proxy jpegs (20 s timeout each). The
model returns {"score": 1-10, "title": "4-6 words"}. Final score = 0.7 action + 0.3 vision.
Anything that goes wrong (no Ollama, no VL model, timeout, bad JSON) keeps the action-only
order and leaves one warning in the report. No other network use; never a hard failure.

Real-model output is UNVERIFIED on this machine (Ollama not installed): tests use a stub server.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .events import Event, OnEvent, emit
from .report import Report, Stage, Warning

OLLAMA_BASE = "http://127.0.0.1:11434"
PREFERRED_MODELS = ("qwen3-vl:4b", "qwen2.5vl:3b", "gemma3:4b", "minicpm-v", "moondream")
VL_HINTS = ("vl", "vision", "llava", "moondream", "minicpm-v", "gemma3", "bakllava", "llama3.2-v")
TAGS_TIMEOUT_S = 1.0
GENERATE_TIMEOUT_S = 20.0
FRAME_TIMEOUT_S = 15.0
MAX_ITEMS = 30
FRAMES_PER_CLIP = 4
VISION_WEIGHT = 0.3
MAX_CONSECUTIVE_FAILURES = 2

PROMPT = (
    "These frames are from one moment of a video game recording. Rate how clip-worthy the "
    "moment is for a short vertical highlight: 1 = menu, loading screen, map, inventory, idle "
    "or empty scene; 5 = ordinary play; 10 = intense action, a kill, a win, a crash, a big "
    'reveal. Reply with JSON only: {"score": <integer 1-10>, "title": "<4 to 6 word title>"}'
)


@dataclass
class VisionScore:
    score: float | None = None  # 1..10 from the model
    title: str | None = None
    error: str | None = None


@dataclass
class VisionOutcome:
    status: str  # ok | skipped | partial
    model: str | None
    reason: str = ""
    scored: int = 0
    failed: int = 0
    reranked: bool = False
    wall_s: float = 0.0
    results: list[VisionScore] = field(default_factory=list)


# ---------------------------------------------------------------- Ollama (localhost only)


def _get_json(url: str, timeout: float) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (localhost)
        return json.loads(resp.read().decode("utf-8"))


def _post_json(url: str, payload: dict, timeout: float) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (localhost)
        return json.loads(resp.read().decode("utf-8"))


def list_models(base: str = OLLAMA_BASE, timeout: float = TAGS_TIMEOUT_S) -> list[str] | None:
    """Installed model names, or None when Ollama is not reachable."""
    try:
        data = _get_json(f"{base}/api/tags", timeout)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return None
    return [str(m.get("name", "")) for m in models if isinstance(m, dict) and m.get("name")]


def pick_model(models: list[str], wanted: str | None = None) -> str | None:
    """`wanted` if present (exact or without tag), else the first preferred, else any VL model."""
    if wanted:
        for m in models:
            if m == wanted or m.split(":", 1)[0] == wanted.split(":", 1)[0]:
                return m
        return None
    for pref in PREFERRED_MODELS:
        for m in models:
            if m == pref or m.split(":", 1)[0] == pref.split(":", 1)[0]:
                return m
    for m in models:
        low = m.lower()
        if any(h in low for h in VL_HINTS):
            return m
    return None


def parse_reply(text: str) -> VisionScore:
    """Tolerant parse of the model's JSON (also inside prose or code fences)."""
    if not isinstance(text, str) or not text.strip():
        return VisionScore(error="empty reply")
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
        raw = obj.get("score")
        try:
            score = float(raw)
        except (TypeError, ValueError):
            return VisionScore(error="no numeric score")
        score = min(10.0, max(1.0, score))
        title = obj.get("title")
        title = " ".join(str(title).split())[:60] if title else None
        return VisionScore(score=round(score, 2), title=title or None)
    return VisionScore(error="bad JSON")


def ask_model(
    model: str,
    frames_jpeg: list[bytes],
    base: str = OLLAMA_BASE,
    timeout: float = GENERATE_TIMEOUT_S,
) -> VisionScore:
    payload = {
        "model": model,
        "prompt": PROMPT,
        "images": [base64.b64encode(f).decode("ascii") for f in frames_jpeg],
        "format": "json",
        "stream": False,
        "options": {"temperature": 0, "num_predict": 80},
    }
    try:
        data = _post_json(f"{base}/api/generate", payload, timeout)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        return VisionScore(error=f"ollama: {exc.__class__.__name__}")
    return parse_reply(data.get("response", "") if isinstance(data, dict) else "")


# ---------------------------------------------------------------- frames


def sample_times(start: float, end: float, n: int = FRAMES_PER_CLIP) -> list[float]:
    """n times spread over the clip, biased away from the fades at both ends."""
    n = max(1, n)
    span = max(0.0, end - start)
    if span <= 0:
        return [start]
    return [round(start + span * (i + 1) / (n + 1), 3) for i in range(n)]


def grab_frame(ffmpeg: str, video: str | os.PathLike, t: float, width: int = 320) -> bytes | None:
    """One jpeg at time t, `width` px wide, via a seek (no full decode). None on failure."""
    args = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-ss",
        f"{max(0.0, t):.3f}",
        "-i",
        os.fspath(video),
        "-frames:v",
        "1",
        "-vf",
        f"scale={width}:-2",
        "-q:v",
        "5",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "-",
    ]
    try:
        out = subprocess.run(args, capture_output=True, timeout=FRAME_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 and out.stdout.startswith(b"\xff\xd8") else None


def grab_frames(ffmpeg: str, video: str | os.PathLike, start: float, end: float) -> list[bytes]:
    frames = [grab_frame(ffmpeg, video, t) for t in sample_times(start, end)]
    return [f for f in frames if f]


# ---------------------------------------------------------------- scoring


def blend(action: float, vision_1_10: float | None, w: float = VISION_WEIGHT) -> float:
    """0.7 action + 0.3 vision (vision mapped 1..10 -> 0..1). None keeps the action score."""
    if vision_1_10 is None:
        return action
    v = (min(10.0, max(1.0, vision_1_10)) - 1.0) / 9.0
    return round((1.0 - w) * action + w * v, 4)


def slug(title: str | None, max_len: int = 40) -> str:
    if not title:
        return ""
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:max_len].rstrip("-")


def score_spans(
    spans: list[tuple[float, float]],
    video: str | os.PathLike,
    ffmpeg: str,
    *,
    model: str | None = None,
    base: str = OLLAMA_BASE,
    on_event: OnEvent | None = None,
    max_items: int = MAX_ITEMS,
) -> VisionOutcome:
    """Score (start, end) spans with the local vision model. Never raises."""
    t0 = time.time()
    spans = list(spans)[:max_items]
    results = [VisionScore(error="not scored") for _ in spans]
    models = list_models(base)
    if models is None:
        return VisionOutcome(
            "skipped", None, "Ollama not reachable at 127.0.0.1:11434", results=results
        )
    chosen = pick_model(models, model)
    if chosen is None:
        why = f"model {model!r} not installed" if model else "no vision model installed"
        why += " (try: ollama pull qwen3-vl:4b)"
        return VisionOutcome("skipped", None, why, results=results)
    emit(on_event, Event("vision", "start", 0, len(spans), "clips", message=chosen))
    scored = failed = streak = 0
    for i, (start, end) in enumerate(spans):
        frames = grab_frames(ffmpeg, video, start, end)
        res = ask_model(chosen, frames, base) if frames else VisionScore(error="no frames")
        results[i] = res
        if res.score is None:
            failed += 1
            streak += 1
            if streak >= MAX_CONSECUTIVE_FAILURES:
                break
        else:
            scored += 1
            streak = 0
        emit(on_event, Event("vision", "progress", i + 1, len(spans), "clips"))
    status = "ok" if scored == len(spans) else ("partial" if scored else "skipped")
    reason = ""
    if status != "ok":
        last_err = next((r.error for r in reversed(results) if r.error != "not scored"), None)
        reason = f"{scored}/{len(spans)} scored" + (f" ({last_err})" if last_err else "")
    out = VisionOutcome(status, chosen, reason, scored, failed, False, time.time() - t0, results)
    emit(on_event, Event("vision", "done" if scored else "skipped", scored, len(spans), "clips"))
    return out


# ---------------------------------------------------------------- report application


def _rename_clip_files(report: Report) -> None:
    """Rename rendered files to their new rank + title slug (two-phase, never clobbers)."""
    from .render import clip_filename

    stem = Path(report.input.get("path", "clip")).stem if report.input else "clip"
    moves: list[tuple[Path, Path]] = []
    for c in report.clips:
        if not c.path or not Path(c.path).exists():
            continue
        old = Path(c.path)
        new_name = clip_filename(stem, c.rank, c.start)
        if c.title:
            new_name = new_name[: -len(".mp4")] + "_" + slug(c.title) + ".mp4"
        new = old.with_name(new_name)
        if new != old:
            moves.append((old, new))
            c.path = str(new)
            if c.captions_path and Path(c.captions_path).exists():
                old_ass = Path(c.captions_path)
                new_ass = new.with_suffix(".ass")
                moves.append((old_ass, new_ass))
                c.captions_path = str(new_ass)
    tmp = [(old, old.with_name(f".{i}.{old.name}.tmp")) for i, (old, _new) in enumerate(moves)]
    for old, t in tmp:
        os.replace(old, t)
    for (_old, t), (_o, new) in zip(tmp, moves, strict=True):
        os.replace(t, new)


def rerank_report(
    report: Report,
    video: str | os.PathLike,
    ffmpeg: str,
    *,
    model: str | None = None,
    base: str = OLLAMA_BASE,
    on_event: OnEvent | None = None,
    rename_files: bool = True,
) -> VisionOutcome:
    """Apply the vision pass to report.clips: titles + vision_score always when scored; the
    order (rank) changes only when every clip was scored. Adds a `vision` stage and at most
    one warning. Rendered files are renamed to the new rank + title slug when present."""
    spans = [(c.start, c.end) for c in report.clips]
    out = score_spans(spans, video, ffmpeg, model=model, base=base, on_event=on_event)
    for c, r in zip(report.clips, out.results, strict=True):
        if r.score is not None:
            c.vision_score = r.score
            c.title = r.title
    if out.status == "ok" and report.clips:
        for c in report.clips:
            c.components["action"] = c.score
            c.components["vision"] = round((c.vision_score - 1.0) / 9.0, 4)
            c.score = blend(c.score, c.vision_score)
        report.clips.sort(key=lambda c: c.score, reverse=True)
        for i, c in enumerate(report.clips, start=1):
            c.rank = i
        out.reranked = True
        if rename_files:
            try:
                _rename_clip_files(report)
            except OSError as exc:
                report.warnings.append(Warning("vision", "rename", f"could not rename: {exc}"))
    detail = out.model or ""
    if out.reason:
        detail = f"{detail} {out.reason}".strip()
    report.stages.append(Stage("vision", out.status, round(out.wall_s, 3), detail))
    if out.status != "ok":
        report.warnings.append(
            Warning("vision", out.status, f"{out.reason}; action-only order kept")
        )
    return out
