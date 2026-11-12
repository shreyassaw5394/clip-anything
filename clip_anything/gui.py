"""Desktop window over `pipeline.run`: tkinter from the stdlib, one worker thread, a queue of
messages. The `Controller` knows nothing about tkinter so it can be tested headless; `App`
is the thin widget layer. Run with `clip-anything-gui` or `python -m clip_anything.gui`."""

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


# --- tkinter layer ------------------------------------------------------------------------


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


class App:
    POLL_MS = 100

    def __init__(self, root, controller: Controller | None = None, inputs=None) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.ttk = tk, ttk
        self.root = root
        self.controller = controller or Controller()
        root.title("Clip Anything")
        root.minsize(560, 520)
        icon = asset_path("icon.png")
        if icon is not None:
            try:
                self._icon = tk.PhotoImage(file=str(icon))
                root.iconphoto(True, self._icon)
            except tk.TclError:
                pass

        self.inputs: list[str] = list(inputs or [])
        default_out = (
            Path(self.inputs[0]).parent / "clips" if self.inputs else Path.home() / "clips"
        )
        self.out_var = tk.StringVar(value=str(default_out))
        self.count_var = tk.IntVar(value=10)
        self.captions_var = tk.BooleanVar(value=captions_available())
        self.facecam_var = tk.StringVar(value="auto")
        self.crop_var = tk.StringVar(value="follow")
        self.status_var = tk.StringVar(value="Pick a recording to begin.")
        self.detail_var = tk.StringVar(value="")
        self.input_var = tk.StringVar(value=self._input_text())

        pad = {"padx": 12, "pady": 6}
        frame = ttk.Frame(root, padding=12)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Clip Anything", font=("TkDefaultFont", 20, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text="Long gameplay recording in, the best vertical clips out. "
            "Everything stays on this computer.",
        ).pack(anchor="w", pady=(0, 10))

        row = ttk.Frame(frame)
        row.pack(fill="x", **pad)
        ttk.Button(row, text="Choose recording...", command=self.pick_file).pack(side="left")
        ttk.Button(row, text="Choose folder of recordings...", command=self.pick_folder).pack(
            side="left", padx=(8, 0)
        )
        ttk.Label(frame, textvariable=self.input_var, wraplength=520).pack(anchor="w", padx=12)

        row = ttk.Frame(frame)
        row.pack(fill="x", **pad)
        ttk.Button(row, text="Clips go to...", command=self.pick_out).pack(side="left")
        ttk.Label(row, textvariable=self.out_var, wraplength=380).pack(side="left", padx=(8, 0))

        opts = ttk.LabelFrame(frame, text="Options", padding=8)
        opts.pack(fill="x", **pad)
        r1 = ttk.Frame(opts)
        r1.pack(fill="x")
        ttk.Label(r1, text="Number of clips").pack(side="left")
        ttk.Spinbox(r1, from_=1, to=100, width=5, textvariable=self.count_var).pack(
            side="left", padx=(6, 18)
        )
        cap_text = "Captions when there is speech"
        if captions_available():
            cap_text += " (first run downloads a ~150 MB speech model)"
        else:
            cap_text += " (not included in this build)"
        cap = ttk.Checkbutton(r1, text=cap_text, variable=self.captions_var)
        cap.pack(side="left")
        if not captions_available():
            cap.state(["disabled"])
        r2 = ttk.Frame(opts)
        r2.pack(fill="x", pady=(6, 0))
        ttk.Label(r2, text="Facecam").pack(side="left")
        ttk.Combobox(
            r2, values=["auto", "off"], textvariable=self.facecam_var, width=6, state="readonly"
        ).pack(side="left", padx=(6, 18))
        ttk.Label(r2, text="Vertical crop").pack(side="left")
        ttk.Combobox(
            r2, values=["follow", "center"], textvariable=self.crop_var, width=7, state="readonly"
        ).pack(side="left", padx=(6, 0))

        row = ttk.Frame(frame)
        row.pack(fill="x", **pad)
        self.start_btn = ttk.Button(row, text="Make clips", command=self.start)
        self.start_btn.pack(side="left")
        self.cancel_btn = ttk.Button(row, text="Cancel", command=self.cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=(8, 0))
        self.open_btn = ttk.Button(
            row, text="Open clips folder", command=self.open_out, state="disabled"
        )
        self.open_btn.pack(side="right")

        self.bar = ttk.Progressbar(frame, maximum=1000, length=520)
        self.bar.pack(fill="x", padx=12, pady=(6, 0))
        ttk.Label(frame, textvariable=self.status_var).pack(anchor="w", padx=12)
        ttk.Label(frame, textvariable=self.detail_var, foreground="#666").pack(anchor="w", padx=12)

        cols = ("rank", "time", "score", "file")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", height=8)
        for c, w in zip(cols, (40, 110, 60, 300), strict=True):
            self.tree.heading(c, text=c.title())
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=12, pady=(8, 0))
        self.warnings: list[str] = []
        root.protocol("WM_DELETE_WINDOW", self.close)

    # -- pickers --
    def _input_text(self) -> str:
        if not self.inputs:
            return "No recording chosen yet."
        if len(self.inputs) == 1:
            return self.inputs[0]
        return f"{len(self.inputs)} recordings"

    def _set_inputs(self, paths: list[str]) -> None:
        self.inputs = [p for p in paths if p]
        self.input_var.set(self._input_text())
        if self.inputs:
            self.out_var.set(str(Path(self.inputs[0]).parent / "clips"))

    def pick_file(self) -> None:
        from tkinter import filedialog

        types = [("Recordings", " ".join("*" + s for s in VIDEO_SUFFIXES)), ("All files", "*")]
        paths = filedialog.askopenfilenames(title="Choose recording(s)", filetypes=types)
        if paths:
            self._set_inputs(list(paths))

    def pick_folder(self) -> None:
        from tkinter import filedialog

        path = filedialog.askdirectory(title="Choose a folder of recordings")
        if path:
            self._set_inputs([path])

    def pick_out(self) -> None:
        from tkinter import filedialog

        path = filedialog.askdirectory(title="Where should the clips go?")
        if path:
            self.out_var.set(path)

    # -- job --
    def settings(self) -> JobSettings:
        try:
            count = int(self.count_var.get())
        except (ValueError, self.tk.TclError):
            count = 0
        return JobSettings(
            inputs=list(self.inputs),
            out_dir=self.out_var.get(),
            count=count,
            captions=bool(self.captions_var.get()),
            facecam=self.facecam_var.get(),
            crop=self.crop_var.get(),
        )

    def start(self) -> None:
        problem = self.controller.start(self.settings())
        if problem:
            self.status_var.set(problem)
            return
        self.tree.delete(*self.tree.get_children())
        self.warnings = []
        self.bar["value"] = 0
        self.status_var.set("Starting...")
        self.detail_var.set("")
        self.start_btn.state(["disabled"])
        self.cancel_btn.state(["!disabled"])
        self.open_btn.state(["disabled"])
        self.root.after(self.POLL_MS, self.poll)

    def cancel(self) -> None:
        self.controller.cancel()
        self.status_var.set("Stopping after the current step...")
        self.cancel_btn.state(["disabled"])

    def poll(self) -> None:
        for kind, payload in self.controller.drain():
            if kind == "progress":
                p = payload
                self.bar["value"] = int(p.fraction * 1000)
                self.status_var.set(p.label)
                self.detail_var.set(p.detail)
            elif kind == "warn":
                self.warnings.append(str(payload))
            elif kind == "done":
                self._finish(payload)
                return
            elif kind == "error":
                self._idle(str(payload))
                return
            elif kind == "cancelled":
                self._idle("Stopped. Nothing was left half-written.")
                return
        if self.controller.running or not self.controller.queue.empty():
            self.root.after(self.POLL_MS, self.poll)

    def _idle(self, status: str) -> None:
        self.status_var.set(status)
        self.detail_var.set("")
        self.start_btn.state(["!disabled"])
        self.cancel_btn.state(["disabled"])

    def _finish(self, report) -> None:
        for row in clip_rows(report):
            self.tree.insert("", "end", values=row)
        ok, total = len(report.ok_clips), len(report.clips)
        self.bar["value"] = 1000
        if total == 0:
            msg = "No moments cleared the action bar in this recording."
        else:
            msg = f"Done: {ok} of {total} clips are in {report.out_dir}"
        if self.warnings:
            msg += f"  ({len(self.warnings)} note{'s' if len(self.warnings) > 1 else ''})"
        self._idle(msg)
        self.detail_var.set(" | ".join(self.warnings[:3]))
        if ok:
            self.open_btn.state(["!disabled"])

    def open_out(self) -> None:
        try:
            open_folder(self.out_var.get())
        except OSError as exc:
            self.status_var.set(f"Could not open the folder: {exc}")

    def close(self) -> None:
        if self.controller.running:
            self.controller.cancel()
        self.root.destroy()


def selftest() -> int:
    """Build the window without showing it, or exit 0 with a note when there is no display."""
    try:
        import tkinter as tk
    except ImportError as exc:
        print(f"selftest: tkinter not available ({exc})")
        return 0
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"selftest: no display ({exc})")
        return 0
    try:
        root.withdraw()
        app = App(root)
        root.update_idletasks()
        assert app.settings().count == 10
        print("selftest: window built")
    finally:
        root.destroy()
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if "--selftest" in argv:
        return selftest()
    if "--version" in argv:
        from . import __version__

        print(f"clip-anything-gui {__version__}")
        return 0
    inputs = [a for a in argv if not a.startswith("-")]
    import tkinter as tk

    root = tk.Tk()
    App(root, inputs=inputs)
    root.mainloop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
