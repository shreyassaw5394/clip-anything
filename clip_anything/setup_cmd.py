"""`clip-anything setup`: one-shot, idempotent environment check with opt-in installs.

Checks in order, one line each (✓ present / → missing): ffmpeg+ffprobe (>= 5, libass for burned
captions), Python, the `[captions]` extra (faster-whisper), the Whisper model, Ollama and a small
vision model. Nothing is installed silently: every fix is printed first, runs only after `--yes`
or a TTY confirmation, and is re-checked afterwards. A second run is all ✓ and exits 0 fast.

Every side effect (which, subprocess, HTTP, imports, downloads) goes through `Tools` so the logic
is unit-tested with fakes; nothing here uses a shell.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated

import typer

EXIT_OK = 0
EXIT_NO_FFMPEG = 3
DEFAULT_WHISPER = "base.en"
DEFAULT_VISION_MODEL = "qwen3-vl:4b"
OLLAMA_BASE = "http://127.0.0.1:11434"
MODEL_SIZES_GB = {"qwen3-vl:4b": 3.3, "qwen2.5vl:3b": 3.2, "gemma3:4b": 3.3, "moondream": 1.7}
OLLAMA_LINUX_NOTE = (
    "curl -fsSL https://ollama.com/install.sh | sh   (run it yourself, then re-run setup)"
)
WINGET_FLAGS = ["-e", "--accept-source-agreements", "--accept-package-agreements"]


def _run(argv: list[str]) -> int:
    """Run a fix command in the foreground (its own output visible). argv only, never a shell."""
    try:
        return subprocess.run(argv, check=False).returncode
    except OSError as exc:
        print(f"  could not run {argv[0]}: {exc}")
        return 127


def _find_spec(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _ffmpeg_caps():
    from .probe import preflight

    return preflight()


def _model_cached(name: str) -> bool:
    from .speech import model_cached

    return model_cached(name)


def _download_whisper(name: str) -> str:
    from .speech import load_model

    model, reason = load_model(name, allow_download=True)
    return "" if model is not None else reason


def _ollama_models(base: str) -> list[str] | None:
    from .vision import list_models

    return list_models(base)


def _confirm_tty(question: str) -> bool:
    if not sys.stdin.isatty():
        return False
    return typer.confirm(question, default=True)


@dataclass
class Tools:
    """Everything with a side effect, injectable for tests."""

    which: Callable[[str], str | None] = shutil.which
    run: Callable[[list[str]], int] = _run
    system: str = field(default_factory=platform.system)
    find_spec: Callable[[str], bool] = _find_spec
    ffmpeg_caps: Callable[[], object] = _ffmpeg_caps
    model_cached: Callable[[str], bool] = _model_cached
    download_whisper: Callable[[str], str] = _download_whisper
    ollama_models: Callable[[str], list[str] | None] = _ollama_models
    executable: str = sys.executable
    frozen: bool = bool(getattr(sys, "frozen", False))
    confirm: Callable[[str], bool] = _confirm_tty
    say: Callable[[str], None] = print
    python_version: tuple[int, int] = sys.version_info[:2]


@dataclass
class Step:
    key: str
    label: str
    ok: bool
    detail: str = ""
    fix: list[str] | None = None  # argv we can run after consent
    note: str = ""  # what to do when we cannot run it
    required: bool = False
    action: Callable[[], str] | None = None  # in-process fix (returns "" or an error)


# ---------------------------------------------------------------- checks


def check_ffmpeg(t: Tools, captions: bool) -> Step:
    from .errors import FFmpegMissing

    try:
        caps = t.ffmpeg_caps()
    except FFmpegMissing as exc:
        fix, note = ffmpeg_fix(t)
        return Step("ffmpeg", "ffmpeg + ffprobe", False, str(exc), fix, note, required=True)
    v = f"{caps.version[0]}.{caps.version[1]}"
    if captions and not caps.captions:
        fix, note = libass_fix(t)
        return Step(
            "ffmpeg",
            "ffmpeg + ffprobe",
            False,
            f"{v} found, but without libass: captions will be written as .ass files, not burned",
            fix,
            note,
        )
    return Step(
        "ffmpeg", "ffmpeg + ffprobe", True, f"{v}, libass {'yes' if caps.captions else 'no'}"
    )


def ffmpeg_fix(t: Tools) -> tuple[list[str] | None, str]:
    if t.system == "Darwin":
        if t.which("brew"):
            return ["brew", "install", "ffmpeg"], ""
        return None, "install Homebrew (https://brew.sh), then: brew install ffmpeg"
    if t.system == "Linux":
        for pm, argv in (
            ("apt-get", ["sudo", "apt-get", "install", "-y", "ffmpeg"]),
            ("dnf", ["sudo", "dnf", "install", "-y", "ffmpeg"]),
            ("pacman", ["sudo", "pacman", "-S", "--noconfirm", "ffmpeg"]),
        ):
            if t.which(pm):
                return argv, ""
        return None, "install ffmpeg with your package manager (https://ffmpeg.org/download.html)"
    if t.system == "Windows":
        if t.which("winget"):
            return [
                "winget",
                "install",
                "--id",
                "Gyan.FFmpeg",
                *WINGET_FLAGS,
            ], "open a new terminal afterwards"
        return (
            None,
            "winget install Gyan.FFmpeg (or ffmpeg.org/download.html), then open a new terminal",
        )
    return None, "https://ffmpeg.org/download.html"


def libass_fix(t: Tools) -> tuple[list[str] | None, str]:
    if t.system == "Darwin" and t.which("brew"):
        return ["brew", "install", "ffmpeg-full"], "keg-only; clip-anything finds it automatically"
    if t.system == "Windows":
        return None, "the Gyan.FFmpeg build includes libass: winget install Gyan.FFmpeg"
    return None, "install an ffmpeg build with libass (most distro packages have it)"


def check_python(t: Tools) -> Step:
    v = f"{t.python_version[0]}.{t.python_version[1]}"
    ok = t.python_version >= (3, 11)
    return Step("python", "Python", ok, v if ok else f"{v} (need 3.11+)", required=True)


def install_kind(executable: str, frozen: bool = False) -> str:
    """How this copy of clip-anything was installed: uv-tool | uvx | pipx | frozen | venv."""
    if frozen:
        return "frozen"
    p = executable.replace("\\", "/")
    if "/uv/tools/" in p or "/uv/tools/" in p.lower():
        return "uv-tool"
    if "/pipx/venvs/" in p:
        return "pipx"
    if "/uv/" in p and ("archive-v" in p or "/cache/" in p):
        return "uvx"
    return "venv"


def captions_fix(kind: str, executable: str) -> tuple[list[str] | None, str]:
    if kind == "uv-tool":
        return (
            ["uv", "tool", "install", "--force", "--with", "faster-whisper", "clip-anything"],
            "installed from git? add the same --from you used",
        )
    if kind == "pipx":
        return ["pipx", "inject", "clip-anything", "faster-whisper"], ""
    if kind == "venv":
        return [executable, "-m", "pip", "install", "faster-whisper"], ""
    if kind == "uvx":
        return (
            None,
            "uvx runs a fresh copy each time: use  uvx --with faster-whisper clip-anything ...",
        )
    return None, "desktop build: captions are not available in this package"


def check_captions_dep(t: Tools) -> Step:
    if t.find_spec("faster_whisper"):
        return Step("captions", "captions extra (faster-whisper)", True, "installed")
    kind = install_kind(t.executable, t.frozen)
    fix, note = captions_fix(kind, t.executable)
    return Step(
        "captions", "captions extra (faster-whisper)", False, f"not installed ({kind})", fix, note
    )


def check_whisper_model(t: Tools, name: str) -> Step:
    from .speech import MODEL_SIZES_MB

    label = f"Whisper model {name}"
    if not t.find_spec("faster_whisper"):
        return Step("whisper", label, False, "needs the captions extra first")
    if t.model_cached(name):
        return Step("whisper", label, True, "downloaded")
    mb = MODEL_SIZES_MB.get(name, "?")
    return Step(
        "whisper",
        label,
        False,
        f"not downloaded (~{mb} MB from huggingface.co)",
        action=lambda: t.download_whisper(name),
    )


def check_ollama(t: Tools) -> Step:
    models = t.ollama_models(OLLAMA_BASE)
    if models is not None:
        return Step("ollama", "Ollama", True, f"running, {len(models)} model(s)")
    if t.which("ollama"):
        return Step(
            "ollama",
            "Ollama",
            False,
            "installed but not running",
            note="start it (open the Ollama app, or: ollama serve), then re-run setup",
        )
    fix, note = ollama_fix(t)
    return Step(
        "ollama",
        "Ollama",
        False,
        "not installed (optional: local AI titles and smarter picks)",
        fix,
        note,
    )


def ollama_fix(t: Tools) -> tuple[list[str] | None, str]:
    if t.system == "Darwin" and t.which("brew"):
        return ["brew", "install", "ollama"], "then start it: ollama serve (or open the app)"
    if t.system == "Windows" and t.which("winget"):
        return [
            "winget",
            "install",
            "--id",
            "Ollama.Ollama",
            *WINGET_FLAGS,
        ], "then open the Ollama app"
    if t.system == "Linux":
        return None, OLLAMA_LINUX_NOTE
    return None, "https://ollama.com/download"


def check_vision_model(t: Tools, model: str) -> Step:
    from .vision import pick_model

    label = f"Ollama vision model {model}"
    models = t.ollama_models(OLLAMA_BASE)
    if models is None:
        return Step("vision", label, False, "needs Ollama running first")
    if pick_model(models, model) or pick_model(models):
        return Step("vision", label, True, pick_model(models, model) or pick_model(models) or "")
    gb = MODEL_SIZES_GB.get(model)
    size = f"~{gb} GB" if gb else "size unknown"
    return Step("vision", label, False, f"not pulled ({size})", ["ollama", "pull", model])


# ---------------------------------------------------------------- the run


def _checks(
    t: Tools, *, captions: bool, whisper: str, ai: bool, vision: str
) -> list[Callable[[], Step]]:
    plan: list[Callable[[], Step]] = [lambda: check_ffmpeg(t, captions), lambda: check_python(t)]
    if captions:
        plan += [lambda: check_captions_dep(t), lambda: check_whisper_model(t, whisper)]
    if ai:
        plan += [lambda: check_ollama(t), lambda: check_vision_model(t, vision)]
    return plan


def _line(step: Step) -> str:
    mark = "✓" if step.ok else "→"
    return f"{mark} {step.label}: {step.detail}"


def _say(t: Tools, text: str) -> None:
    try:
        t.say(text)
    except UnicodeEncodeError:  # legacy Windows console
        t.say(text.replace("✓", "ok").replace("→", "->"))


def run_setup(
    t: Tools | None = None,
    *,
    yes: bool = False,
    captions: bool = True,
    whisper: str = DEFAULT_WHISPER,
    ai: bool = True,
    vision: str = DEFAULT_VISION_MODEL,
) -> int:
    """Print one line per check; offer each fix; re-check. Exit 3 only when ffmpeg is still
    missing (everything else is optional)."""
    t = t or Tools()
    t0 = time.time()
    pending: list[Step] = []
    for check in _checks(t, captions=captions, whisper=whisper, ai=ai, vision=vision):
        step = check()
        _say(t, _line(step))
        if step.ok:
            continue
        if step.fix is None and step.action is None:
            if step.note:
                _say(t, f"    {step.note}")
            pending.append(step)
            continue
        what = " ".join(step.fix) if step.fix else f"download {step.label}"
        _say(t, f"    will run: {what}" + (f"   ({step.note})" if step.note else ""))
        if not (yes or t.confirm("    run it now?")):
            _say(t, "    skipped (re-run with --yes to accept everything)")
            pending.append(step)
            continue
        if step.fix:
            rc = t.run(step.fix)
            err = "" if rc == 0 else f"exit {rc}"
        else:
            err = step.action() if step.action else ""
        again = check()
        if err and not again.ok:
            again.detail = f"{again.detail} ({err})"
        _say(t, "  " + _line(again))
        if not again.ok:
            pending.append(again)
    missing_required = [s for s in pending if s.required]
    if missing_required:
        _say(
            t,
            f"setup incomplete: {', '.join(s.label for s in missing_required)} "
            f"({time.time() - t0:.1f}s)",
        )
        return EXIT_NO_FFMPEG
    if pending:
        _say(
            t,
            f"ready (optional items skipped: {', '.join(s.label for s in pending)}; "
            f"{time.time() - t0:.1f}s)",
        )
    else:
        _say(t, f"all set ({time.time() - t0:.1f}s)")
    return EXIT_OK


# ---------------------------------------------------------------- typer entry

setup_app = typer.Typer(add_completion=False, rich_markup_mode=None)


@setup_app.command()
def setup(
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Accept every install/download")] = False,
    no_ai: Annotated[
        bool, typer.Option("--no-ai", help="Skip the Ollama / vision model part")
    ] = False,
    no_captions: Annotated[
        bool, typer.Option("--no-captions", help="Skip faster-whisper + model")
    ] = False,
    whisper_model: Annotated[
        str, typer.Option("--whisper-model", help="tiny.en | base.en | small ...")
    ] = DEFAULT_WHISPER,
    vision_model: Annotated[
        str, typer.Option("--vision-model", help="Ollama model to pull")
    ] = DEFAULT_VISION_MODEL,
) -> None:
    """Check ffmpeg, captions and (optional) local AI; install what is missing, with consent."""
    if os.name == "nt":  # legacy code pages cannot print ✓
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
            except (AttributeError, ValueError):  # pragma: no cover
                pass
    code = run_setup(
        yes=yes, captions=not no_captions, whisper=whisper_model, ai=not no_ai, vision=vision_model
    )
    raise typer.Exit(code)
