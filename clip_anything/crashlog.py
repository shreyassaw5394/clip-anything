"""Crash logs for runs started from the desktop app or the local app server, plus the
packaged-app location check. A log holds the traceback, versions, the frozen bundle path,
the input *basenames* and the run options; never file contents, never keys. The last
`KEEP_LOGS` logs are kept in the per-user state directory."""

from __future__ import annotations

import os
import platform
import sys
import traceback
from datetime import datetime
from pathlib import Path

from . import __version__

KEEP_LOGS = 20
_SECRET_WORDS = ("key", "token", "secret", "password", "authorization")


def log_dir() -> Path:
    """macOS ~/Library/Application Support/clip-anything/logs, Windows %APPDATA%/clip-anything/
    logs, elsewhere $XDG_STATE_HOME (default ~/.local/state)/clip-anything/logs."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    return base / "clip-anything" / "logs"


def _redact(value, depth: int = 0):
    """Options as written to the log: anything whose key smells like a credential is dropped."""
    if depth > 6:
        return "..."
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            secret = any(w in str(k).lower() for w in _SECRET_WORDS)
            out[k] = "<redacted>" if secret else _redact(v, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_redact(v, depth + 1) for v in value]
    return value


def bundle_info() -> dict:
    frozen = bool(getattr(sys, "frozen", False))
    return {
        "frozen": frozen,
        "bundle": getattr(sys, "_MEIPASS", "") if frozen else "",
        "executable": sys.executable,
    }


def write_crash_log(
    exc: BaseException,
    *,
    inputs: list[str] | None = None,
    options: dict | None = None,
    source: str = "",
    directory: Path | None = None,
) -> Path | None:
    """Write run-<timestamp>.log and prune older logs. Returns the path, or None when the log
    directory cannot be written (never raises: the caller is already handling an error)."""
    try:
        d = directory or log_dir()
        d.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
        p = d / f"run-{stamp}.log"
        b = bundle_info()
        lines = [
            f"clip-anything {__version__} crash log",
            f"time: {datetime.now().isoformat(timespec='seconds')}",
            f"source: {source or 'run'}",
            f"python: {sys.version.split()[0]} ({sys.executable})",
            f"platform: {platform.platform()} {platform.machine()}",
            f"frozen: {b['frozen']}  bundle: {b['bundle'] or '-'}",
            f"cwd: {os.getcwd()}",
            "inputs: " + ", ".join(os.path.basename(i.rstrip("/\\")) or i for i in inputs or []),
            f"options: {_redact(options or {})!r}",
            f"error: {type(exc).__module__}.{type(exc).__name__}: {exc}",
            "",
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        ]
        p.write_text("\n".join(lines), encoding="utf-8")
        _prune(d)
        return p
    except Exception:  # noqa: BLE001 - logging must never add a second failure
        return None


def _prune(d: Path, keep: int = KEEP_LOGS) -> None:
    logs = sorted(d.glob("run-*.log"))
    for old in logs[: max(0, len(logs) - keep)]:
        try:
            old.unlink()
        except OSError:
            pass


def error_summary(exc: BaseException, log: Path | None) -> str:
    """The banner text for an unexpected error: the user is told where the details are."""
    where = f" Details saved to {log}" if log else ""
    return f"Unexpected problem.{where}".strip()


# --- packaged-app location --------------------------------------------------------------


def bundle_location_problem(
    path: str | None = None, frozen: bool | None = None, platform_name: str | None = None
) -> str | None:
    """Only in the packaged app: a one-line notice when the app runs from a mounted disk
    image, a read-only volume or a macOS App Translocation path (the first launch of a
    quarantined app from Downloads). Running from there works for a while and then fails in
    odd ways (files unreadable once the image is ejected or the random mount goes away)."""
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if not frozen:
        return None
    plat = platform_name or sys.platform
    p = path or getattr(sys, "_MEIPASS", None) or sys.executable
    text = str(p)
    reason = ""
    if plat == "darwin" and "/AppTranslocation/" in text:
        reason = "it is running from a temporary location (macOS App Translocation)"
    elif plat == "darwin" and text.startswith("/Volumes/"):
        reason = "it is running from a disk image or an external volume"
    elif _read_only(text):
        reason = "it is running from a read-only location"
    if not reason:
        return None
    app = "Clip Anything"
    if plat == "darwin":
        return f"Move {app} to your Applications folder first: {reason}."
    return f"Move {app} to a normal folder first: {reason}."


def _read_only(path: str) -> bool:
    try:
        st = os.statvfs(path)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False
    return bool(st.f_flag & getattr(os, "ST_RDONLY", 1))
