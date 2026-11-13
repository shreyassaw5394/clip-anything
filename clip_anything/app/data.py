"""Small per-user state for the app: recent sessions (paths and settings only) in the user
data directory. Nothing else is stored; nothing leaves the machine."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

MAX_RECENT = 8


def data_dir() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return base / "clip-anything"


class Recent:
    """`recent.json`: the last few runs (inputs, output folder, settings, clip count)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or data_dir() / "recent.json"

    def load(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        out = []
        for item in data[:MAX_RECENT]:
            if isinstance(item, dict) and isinstance(item.get("inputs"), list):
                out.append(item)
        return out

    def _save(self, items: list[dict]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".part")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(items[:MAX_RECENT], fh, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            pass  # a read-only home is not worth an error in the UI

    def add(self, entry: dict) -> None:
        entry = dict(entry)
        entry["when"] = int(time.time())
        items = [
            i
            for i in self.load()
            if not (
                i.get("inputs") == entry.get("inputs") and i.get("out_dir") == entry.get("out_dir")
            )
        ]
        self._save([entry, *items])

    def clear(self) -> None:
        self._save([])


class Prefs:
    """`prefs.json`: window size and the last output folder the user chose. Local only."""

    KEYS = ("window", "out_dir")

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or data_dir() / "prefs.json"

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def set(self, **values) -> dict:
        data = self.load()
        for k, v in values.items():
            if k in self.KEYS and v is not None:
                data[k] = v
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".part")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            pass
        return data

    def window(self) -> tuple[int, int] | None:
        w = self.load().get("window")
        if isinstance(w, dict):
            try:
                width, height = int(w.get("width", 0)), int(w.get("height", 0))
            except (TypeError, ValueError):
                return None
            if 760 <= width <= 8000 and 560 <= height <= 8000:
                return width, height
        return None

    def out_dir(self) -> str:
        d = self.load().get("out_dir")
        return d if isinstance(d, str) and Path(d).is_dir() else ""
