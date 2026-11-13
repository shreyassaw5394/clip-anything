"""Report dataclasses and report.json writer."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__

SCHEMA_VERSION = 1


@dataclass
class Clip:
    rank: int
    candidate_id: int
    start: float
    end: float
    duration_s: float
    score: float
    components: dict[str, float] = field(default_factory=dict)
    peak_t: float = 0.0
    title: str | None = None
    vision_score: float | None = None
    layout: str = "gameplay"
    captions: bool = False
    crop: dict = field(default_factory=lambda: {"mode": "center", "keyframes": []})
    path: str | None = None
    status: str = "pending"  # ok | failed | skipped | pending
    error: str | None = None
    render_s: float | None = None
    snap: dict = field(default_factory=dict)
    facecam: dict | None = None  # {x,y,w,h fractions, corner, confidence} when layout=facecam
    captions_path: str | None = None  # sidecar .ass next to the clip (also when libass missing)
    transcript: str | None = None
    speech: dict = field(default_factory=dict)  # {words, bonus, phrases, shouts, model_s, reason}
    source: str | None = None  # the file this clip is cut from (sessions: one of several)
    source_index: int = 0  # position of that file in the session order
    session_start: float | None = None  # start/end on the session timeline (== start for 1 file)
    session_end: float | None = None
    ai: dict | None = None  # --ai: {title, hook, reaction, score, provider, model, ai_generated}


@dataclass
class Stage:
    name: str
    status: str  # ok | cached | skipped | failed
    wall_s: float
    detail: str = ""


@dataclass
class Warning:
    stage: str
    code: str
    message: str


@dataclass
class Report:
    input: dict[str, Any]
    options: dict[str, Any]
    stages: list[Stage] = field(default_factory=list)
    warnings: list[Warning] = field(default_factory=list)
    candidates_total: int = 0
    clips: list[Clip] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    out_dir: str | None = None
    report_path: str | None = None
    ai: dict[str, Any] = field(default_factory=dict)  # --ai run: {brief, provider, model, status}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "tool": "clip-anything",
            "version": __version__,
            "created": datetime.now(UTC).isoformat(timespec="seconds"),
            "input": self.input,
            "options": self.options,
            "stages": [asdict(s) for s in self.stages],
            "warnings": [asdict(w) for w in self.warnings],
            "candidates_total": self.candidates_total,
            "clips": [asdict(c) for c in self.clips],
            "signals": self.signals,
            "timings": self.timings,
            "out_dir": self.out_dir,
            "ai": self.ai,
        }

    @property
    def ok_clips(self) -> list[Clip]:
        return [c for c in self.clips if c.status == "ok"]

    def write(self, path: str | os.PathLike) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".part")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)
        os.replace(tmp, p)
        self.report_path = str(p)
        return p
