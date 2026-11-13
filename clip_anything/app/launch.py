"""Start the local server and show the UI: a native window when pywebview is installed
(`pip install clip-anything[app]`), else the default browser. Native file pickers run on the
main thread in both modes (pywebview's dialog, or tkinter when there is no window)."""

from __future__ import annotations

import importlib.util
import queue
import sys
import threading
import webbrowser
from pathlib import Path

from .server import AppServer

VIDEO_SUFFIXES = (".mp4", ".mkv", ".mov", ".webm", ".ts", ".m4v", ".avi", ".flv", ".mts")
WINDOW_TITLE = "Clip Anything"


def webview_available() -> bool:
    try:
        return importlib.util.find_spec("webview") is not None
    except (ImportError, ValueError):
        return False


class MainThreadPicker:
    """Browser mode: tkinter dialogs must run on the main thread (macOS), so request threads
    queue a job and the main loop executes it."""

    def __init__(self) -> None:
        self.requests: queue.Queue[tuple[str, queue.Queue]] = queue.Queue()

    def __call__(self, kind: str) -> list[str]:
        reply: queue.Queue = queue.Queue()
        self.requests.put((kind, reply))
        try:
            return reply.get(timeout=600)
        except queue.Empty:
            return []

    def serve(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                kind, reply = self.requests.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                reply.put(tk_pick(kind))
            except Exception:  # noqa: BLE001 - no tkinter / no display: the UI says so
                reply.put([])


def tk_pick(kind: str) -> list[str]:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass
    try:
        if kind == "files":
            types = [("Recordings", " ".join("*" + s for s in VIDEO_SUFFIXES)), ("All files", "*")]
            paths = filedialog.askopenfilenames(title="Choose recording(s)", filetypes=types)
            return [str(p) for p in paths]
        title = (
            "Choose a folder of recordings" if kind == "folder" else "Where should the clips go?"
        )
        path = filedialog.askdirectory(title=title)
        return [path] if path else []
    finally:
        root.destroy()


class WebviewPicker:
    def __init__(self) -> None:
        self.window = None

    def wire_drop(self) -> None:
        """Dropped files reach the page as paths: pywebview exposes the full path only to a
        Python-side DOM handler, so forward them to the page's `caDrop`."""
        import json

        win = self.window
        if win is None:
            return
        try:
            drop = win.dom.get_element("#drop")
        except Exception:  # noqa: BLE001 - no DOM yet / no bridge: the page falls back to Choose
            return
        if drop is None:
            return

        def on_drop(event) -> None:
            files = (event.get("dataTransfer") or {}).get("files") or []
            paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
            if paths:
                win.evaluate_js(f"window.caDrop && window.caDrop({json.dumps(paths)})")

        drop.events.drop += on_drop

    def __call__(self, kind: str) -> list[str]:
        import webview

        if self.window is None:
            return []
        if kind == "files":
            res = self.window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=True,
                file_types=(
                    "Recordings (" + ";".join("*" + s for s in VIDEO_SUFFIXES) + ")",
                    "All files (*.*)",
                ),
            )
        else:
            res = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        return [str(p) for p in (res or [])]


def launch(*, window: str = "auto", port: int = 0, open_ui: bool = True) -> int:
    """Run until the window closes (webview) or Ctrl-C / Quit (browser). Returns an exit code."""
    use_webview = window == "webview" or (window == "auto" and webview_available())
    stop = threading.Event()

    if use_webview:
        import webview

        picker = WebviewPicker()
        server = AppServer(
            port=port, picker=picker, window="webview", on_quit=lambda: _close(picker)
        )
        server.start()
        icon = _icon()
        win = webview.create_window(
            WINDOW_TITLE, server.url, width=1280, height=820, min_size=(760, 560),
            background_color="#f1efe9", text_select=True,
        )  # fmt: skip
        picker.window = win
        win.events.loaded += picker.wire_drop
        try:
            webview.start(icon=str(icon) if icon else None)
        finally:
            server.stop()
        return 0

    picker = MainThreadPicker()
    server = AppServer(port=port, picker=picker, window="browser", on_quit=stop.set)
    server.start()
    print(f"Clip Anything is running at {server.url}", flush=True)
    print("Leave this window open while you use it; press Ctrl-C to quit.", flush=True)
    if open_ui:
        webbrowser.open(server.url)
    try:
        picker.serve(stop)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0


def _close(picker: WebviewPicker) -> None:
    if picker.window is not None:
        picker.window.destroy()


def _icon() -> Path | None:
    from ..gui import asset_path

    return asset_path("icon.png")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(launch())
