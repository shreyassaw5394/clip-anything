"""Desktop entry point and the headless job model behind it. `clip-anything-gui` (and
`clip-anything app`) start the local web app in `clip_anything.app`; the `Controller` /
`ProgressModel` here run one job on a worker thread with a queue of messages and know nothing
about any UI, so they are tested headless and reused by the app server."""

from __future__ import annotations

import importlib.util
import os
import queue
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .events import Event

STAGE_LABELS = {
    "probe": "Reading the recording",
    "audio": "Listening for action",
    "video": "Watching for motion",
    "score": "Picking the moments",
    "speech": "Transcribing speech",
    "facecam": "Looking for a facecam",
    "vision": "Asking the vision model",
    "render": "Making the clips",
}
# share of the overall bar per stage (analysis is decode-bound, render is encode-bound)
STAGE_WEIGHTS = {
    "probe": 0.02,
    "audio": 0.20,
    "video": 0.33,
    "score": 0.03,
    "speech": 0.07,
    "facecam": 0.02,
    "vision": 0.03,
    "render": 0.30,
}
STAGE_ORDER = list(STAGE_WEIGHTS)
VIDEO_SUFFIXES = (".mp4", ".mkv", ".mov", ".webm", ".ts", ".m4v", ".avi", ".flv", ".mts")


def captions_available() -> bool:
    """faster-whisper importable in this build (the desktop bundle may leave it out)."""
    return importlib.util.find_spec("faster_whisper") is not None


@dataclass
class JobSettings:
    inputs: list[str] = field(default_factory=list)
    out_dir: str = ""
    count: int = 10
    captions: bool = True
    facecam: str = "auto"  # auto | off
    crop: str = "follow"  # follow | center

    def problem(self) -> str | None:
        """Plain-language reason the job cannot start, or None."""
        if not self.inputs:
            return "Choose a recording (or a folder of recordings) first."
        missing = [p for p in self.inputs if not Path(p).exists()]
        if missing:
            return f"Cannot find: {missing[0]}"
        if not self.out_dir:
            return "Choose where the clips should go."
        if self.count < 1 or self.count > 100:
            return "Number of clips must be between 1 and 100."
        if self.facecam not in ("auto", "off") or self.crop not in ("follow", "center"):
            return "Unknown layout option."
        return None

    def layers(self) -> dict:
        """The CLI-equivalent option layer for Options.from_layers."""
        want_captions = bool(self.captions and captions_available())
        return {
            "clips": {"count": self.count},
            "render": {"out_dir": self.out_dir},
            # the checkbox text says the first captioned run downloads the speech model
            "speech": {"captions": want_captions, "yes": want_captions},
            "layout": {"facecam": self.facecam, "crop": self.crop},
        }


@dataclass
class Progress:
    stage: str = ""
    label: str = ""
    fraction: float = 0.0  # 0..1 overall
    detail: str = ""


class ProgressModel:
    """Turns pipeline events into one overall 0..1 fraction plus a human stage label."""

    def __init__(self) -> None:
        self.done: set[str] = set()
        self.current = ""
        self.current_frac = 0.0

    def update(self, ev: Event) -> Progress:
        if ev.kind in ("done", "cached", "skipped"):
            # optional stages (speech, facecam, vision) may never report: a finished stage
            # closes every earlier one in the pipeline order
            idx = STAGE_ORDER.index(ev.stage) if ev.stage in STAGE_ORDER else -1
            self.done.update(STAGE_ORDER[: idx + 1])
            self.done.add(ev.stage)
            if self.current == ev.stage:
                self.current, self.current_frac = "", 0.0
        elif ev.kind == "start":
            self.current, self.current_frac = ev.stage, 0.0
        elif ev.kind == "progress":
            self.current = ev.stage
            if ev.total:
                self.current_frac = max(0.0, min(1.0, ev.done / ev.total))
        frac = sum(STAGE_WEIGHTS.get(s, 0.0) for s in self.done)
        if self.current:
            frac += STAGE_WEIGHTS.get(self.current, 0.0) * self.current_frac
        label_stage = self.current or ev.stage
        label = STAGE_LABELS.get(label_stage, label_stage.title())
        detail = ev.message
        if ev.kind == "progress" and ev.unit == "clips" and ev.total:
            detail = f"{int(ev.done)}/{int(ev.total)} clips"
        elif ev.kind == "progress" and ev.unit == "s" and ev.total:
            detail = f"{_mmss(ev.done)} of {_mmss(ev.total)}"
        return Progress(label_stage, label, min(0.999, frac), detail)


def _mmss(t: float) -> str:
    m, s = divmod(int(t), 60)
    return f"{m:02d}:{s:02d}"


def friendly_error(exc: BaseException) -> str:
    """One or two sentences a non-technical user can act on."""
    from .errors import FFmpegMissing, InputError, StageError

    text = str(exc)
    if isinstance(exc, FFmpegMissing):
        return (
            "The video tools (ffmpeg) were not found. The downloadable app includes them; if "
            "you installed from source, install ffmpeg and start again.\n" + exc.help_text
        )
    if isinstance(exc, InputError):
        if "could not read" in text or "invalid JSON" in text:
            return "This file could not be read as a video. Try re-exporting it as MP4."
        if "no video" in text or "no audio or video" in text:
            return "This file has no video in it. Choose a recording with picture."
        if "not found" in text:
            return "That file could not be found. It may have been moved or renamed."
        return f"There is a problem with the input: {text}"
    if isinstance(exc, StageError):
        if "cancelled" in text:
            return "Stopped."
        return (
            f"Something went wrong while {STAGE_LABELS.get(exc.stage, exc.stage).lower()}: {text}"
        )
    if isinstance(exc, PermissionError):
        return "Cannot write to that output folder. Choose another folder."
    return f"Unexpected problem: {type(exc).__name__}: {text}"


def clip_rows(report) -> list[tuple[str, str, str, str]]:
    """(rank, time, score, file-or-status) rows for the finished list."""
    rows = []
    for c in report.clips:
        name = os.path.basename(c.path) if c.path else f"({c.status})"
        if c.status == "failed":
            name = "failed"
        rows.append((str(c.rank), f"{_mmss(c.start)}-{_mmss(c.end)}", f"{c.score:.2f}", name))
    return rows


def open_folder(path: str | os.PathLike) -> None:
    """Show the folder in Finder / Explorer / the desktop's file manager."""
    p = os.fspath(path)
    if sys.platform == "win32":
        os.startfile(p)  # type: ignore[attr-defined]  # noqa: S606
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def default_runner(target, opts, on_event, cancel):
    from .pipeline import run

    return run(target, opts, on_event=on_event, cancel=cancel)


Message = tuple[str, object]  # ("progress", Progress) | ("warn", str) | ("done", Report)
#                              | ("error", str) | ("cancelled", None)


class Controller:
    """Runs one job at a time on a worker thread; the widget layer polls `drain()`."""

    def __init__(self, runner: Callable | None = None) -> None:
        self.runner = runner or default_runner
        self.queue: queue.Queue[Message] = queue.Queue()
        self.cancel_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.model = ProgressModel()
        self.report = None

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self, settings: JobSettings) -> str | None:
        """Start the job; returns a problem text instead when the settings are not usable."""
        if self.running:
            return "A job is already running."
        problem = settings.problem()
        if problem:
            return problem
        from .config import Options

        opts = Options.from_layers(settings.layers())
        target = settings.inputs[0] if len(settings.inputs) == 1 else list(settings.inputs)
        self.cancel_event = threading.Event()
        self.model = ProgressModel()
        self.report = None
        self.thread = threading.Thread(
            target=self._work, args=(target, opts), name="clip-anything-job", daemon=True
        )
        self.thread.start()
        return None

    def _work(self, target, opts) -> None:
        try:
            report = self.runner(target, opts, self._on_event, self.cancel_event)
        except Exception as exc:  # noqa: BLE001 - every failure becomes a message
            if self.cancel_event.is_set():
                self.queue.put(("cancelled", None))
            else:
                self.queue.put(("error", friendly_error(exc)))
            return
        self.report = report
        self.queue.put(("cancelled", None) if self.cancel_event.is_set() else ("done", report))

    def _on_event(self, ev: Event) -> None:
        if ev.kind == "warn":
            self.queue.put(("warn", f"{ev.stage}: {ev.message}"))
        self.queue.put(("progress", self.model.update(ev)))

    def cancel(self) -> None:
        self.cancel_event.set()

    def drain(self) -> list[Message]:
        out: list[Message] = []
        while True:
            try:
                out.append(self.queue.get_nowait())
            except queue.Empty:
                return out


# --- entry points -------------------------------------------------------------------------


def asset_path(name: str) -> Path | None:
    """assets/<name> from the source tree or the packaged bundle, if present."""
    roots = [Path(__file__).resolve().parents[1]]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.insert(0, Path(meipass))
    for r in roots:
        p = r / "assets" / name
        if p.is_file():
            return p
    return None


def selftest() -> int:
    """Start the app server on a free port, fetch the page with the token, stop. No window."""
    import urllib.request

    from .app.server import AppServer

    server = AppServer().start()
    try:
        with urllib.request.urlopen(server.url, timeout=10) as res:  # noqa: S310 - our own loopback URL
            html = res.read(4096).decode("utf-8", "replace")
            ok = res.status == 200 and "Clip Anything" in html
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/api/caps",
            headers={"Authorization": f"Bearer {server.token}"},
        )
        with urllib.request.urlopen(req, timeout=30) as res:  # noqa: S310
            ok = ok and res.status == 200
    finally:
        server.stop()
    print("selftest: app server ok" if ok else "selftest: app server FAILED")
    return 0 if ok else 1


def headless(inputs: list[str], out_dir: str, count: int, captions: bool = False) -> int:
    """Run the same Controller without a window (packaged-app smoke test): prints the stage
    lines and the clip list, exit 1 on error."""
    c = Controller()
    problem = c.start(JobSettings(inputs=inputs, out_dir=out_dir, count=count, captions=captions))
    if problem:
        print(problem)
        return 2
    last = ""
    while c.running or not c.queue.empty():
        for kind, payload in c.drain():
            if kind == "progress" and payload.label != last:
                last = payload.label
                print(f"{payload.fraction * 100:3.0f}%  {payload.label}")
            elif kind == "warn":
                print(f"note: {payload}")
            elif kind == "error":
                print(f"error: {payload}")
                return 1
            elif kind == "cancelled":
                print("cancelled")
                return 130
            elif kind == "done":
                for row in clip_rows(payload):
                    print("  ".join(row))
                print(f"{len(payload.ok_clips)}/{len(payload.clips)} clips -> {payload.out_dir}")
                return 0 if payload.ok_clips or not payload.clips else 1
        threading.Event().wait(0.05)
    return 1


def main(argv: list[str] | None = None) -> int:
    """clip-anything-gui [--browser | --window] [--port N] | --selftest | --version |
    --run <recording> --out <folder> [--count N] [--captions]"""
    argv = sys.argv[1:] if argv is None else list(argv)
    if "--selftest" in argv:
        return selftest()
    if "--version" in argv:
        from . import __version__

        print(f"clip-anything-gui {__version__}")
        return 0

    def _opt(name: str, default: str | None = None) -> str | None:
        return (
            argv[argv.index(name) + 1]
            if name in argv and argv.index(name) + 1 < len(argv)
            else default
        )

    if "--run" in argv:
        video = _opt("--run")
        out = _opt("--out") or str(Path(video or ".").resolve().parent / "clips")
        count = int(_opt("--count", "10") or 10)
        return headless([video] if video else [], out, count, captions="--captions" in argv)
    from .app.launch import launch

    window = "browser" if "--browser" in argv else ("webview" if "--window" in argv else "auto")
    return launch(
        window=window, port=int(_opt("--port", "0") or 0), open_ui="--no-open" not in argv
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
