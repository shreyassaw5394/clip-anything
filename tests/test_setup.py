"""`clip-anything setup` logic with fake tools: nothing here touches the real machine."""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass

import pytest

from clip_anything import setup_cmd as sc
from clip_anything.errors import FFmpegMissing


@dataclass
class _Caps:
    version: tuple = (7, 1)
    captions: bool = True


class _World:
    """Mutable fake machine: fixes flip the matching flag when they run."""

    def __init__(self, **state):
        self.s = {
            "ffmpeg": True,
            "libass": True,
            "whisper_dep": True,
            "whisper_model": True,
            "ollama_bin": True,
            "ollama_models": ["qwen3-vl:4b"],
            "system": "Darwin",
            "brew": True,
            "exe": "/Users/me/.local/share/uv/tools/clip-anything/bin/python",
            "confirm": False,
            "rc": 0,
        }
        self.s.update(state)
        self.runs: list[list[str]] = []
        self.out: list[str] = []

    def which(self, name):
        table = {
            "brew": self.s["brew"],
            "ollama": self.s["ollama_bin"],
            "apt-get": True,
            "winget": True,
        }
        return f"/bin/{name}" if table.get(name) else None

    def ffmpeg_caps(self):
        if not self.s["ffmpeg"]:
            raise FFmpegMissing("ffmpeg/ffprobe not found on PATH", "help")
        return _Caps(captions=self.s["libass"])

    def run(self, argv):
        self.runs.append(argv)
        if self.s["rc"]:
            return self.s["rc"]
        if argv[:2] == ["brew", "install"] and argv[2] == "ffmpeg":
            self.s["ffmpeg"] = True
        if argv[:2] == ["brew", "install"] and argv[2] == "ffmpeg-full":
            self.s["libass"] = True
        if "faster-whisper" in argv:
            self.s["whisper_dep"] = True
        if argv[:2] == ["brew", "install"] and argv[2] == "ollama":
            self.s["ollama_bin"] = True
        if argv[:2] == ["ollama", "pull"]:
            self.s["ollama_models"] = [argv[2]]
        return 0

    def download_whisper(self, name):
        self.s["whisper_model"] = True
        return ""

    def tools(self) -> sc.Tools:
        return sc.Tools(
            which=self.which,
            run=self.run,
            system=self.s["system"],
            find_spec=lambda n: self.s["whisper_dep"] if n == "faster_whisper" else False,
            ffmpeg_caps=self.ffmpeg_caps,
            model_cached=lambda n: self.s["whisper_model"],
            download_whisper=self.download_whisper,
            ollama_models=lambda base: self.s["ollama_models"],
            executable=self.s["exe"],
            frozen=False,
            confirm=lambda q: self.s["confirm"],
            say=self.out.append,
            python_version=(3, 11),
        )

    def text(self) -> str:
        return "\n".join(self.out)


def test_all_present_is_all_ticks_fast_and_runs_nothing():
    w = _World()
    t0 = time.time()
    assert sc.run_setup(w.tools()) == 0
    assert time.time() - t0 < 1.0
    lines = [ln for ln in w.out if ln.startswith(("\u2713", "\u2192"))]
    assert len(lines) == 6 and all(ln.startswith("\u2713") for ln in lines)
    assert w.runs == [] and "all set" in w.out[-1]


def test_missing_everything_with_yes_installs_in_order_and_rechecks():
    w = _World(
        ffmpeg=False, whisper_dep=False, whisper_model=False, ollama_bin=False, ollama_models=None
    )
    # after `brew install ollama` the server is still not running: no pull possible
    assert sc.run_setup(w.tools(), yes=True) == 0
    assert w.runs == [
        ["brew", "install", "ffmpeg"],
        ["uv", "tool", "install", "--force", "--with", "faster-whisper", "clip-anything"],
        ["brew", "install", "ollama"],
    ]
    text = w.text()
    assert "will run: brew install ffmpeg" in text
    assert "\u2713 ffmpeg + ffprobe: 7.1, libass yes" in text  # re-check after the install
    assert "\u2713 Whisper model base.en: downloaded" in text  # in-process download ran
    assert "needs Ollama running first" in text and "optional items skipped" in text


def test_nothing_runs_without_consent():
    w = _World(ffmpeg=False, whisper_dep=False)
    assert sc.run_setup(w.tools()) == 3  # ffmpeg is required
    assert w.runs == [] and "skipped (re-run with --yes" in w.text()
    assert "setup incomplete: ffmpeg + ffprobe" in w.out[-1]
    w2 = _World(ffmpeg=False, confirm=True)
    assert sc.run_setup(w2.tools()) == 0 and w2.runs == [["brew", "install", "ffmpeg"]]


def test_failed_fix_is_reported_not_hidden():
    w = _World(whisper_dep=False, rc=1)
    assert sc.run_setup(w.tools(), yes=True) == 0  # captions are optional
    assert "(exit 1)" in w.text() and "optional items skipped" in w.out[-1]


def test_no_ai_and_no_captions_skip_their_checks():
    w = _World(ollama_bin=False, ollama_models=None, whisper_dep=False)
    assert sc.run_setup(w.tools(), ai=False, captions=False) == 0
    assert "Ollama" not in w.text() and "faster-whisper" not in w.text()
    assert w.runs == [] and "all set" in w.out[-1]


def test_vision_model_pull_shows_size_and_runs_with_yes():
    w = _World(ollama_models=["llama3.2:3b"])
    assert sc.run_setup(w.tools(), yes=True) == 0
    assert w.runs == [["ollama", "pull", "qwen3-vl:4b"]]
    assert (
        "~3.3 GB" in w.text() and "\u2713 Ollama vision model qwen3-vl:4b: qwen3-vl:4b" in w.text()
    )


def test_libass_missing_offers_ffmpeg_full_on_mac_only():
    w = _World(libass=False)
    assert sc.run_setup(w.tools(), yes=True) == 0
    assert w.runs == [["brew", "install", "ffmpeg-full"]]
    lin = _World(libass=False, system="Linux")
    assert sc.run_setup(lin.tools(), yes=True) == 0 and lin.runs == []
    assert "without libass" in lin.text()


def test_linux_ollama_is_a_note_never_curl_pipe_sh():
    w = _World(system="Linux", ollama_bin=False, ollama_models=None)
    assert sc.run_setup(w.tools(), yes=True) == 0
    assert w.runs == [] and "ollama.com/install.sh" in w.text()


def test_windows_uses_winget_ids():
    w = _World(system="Windows", ffmpeg=False, ollama_bin=False, ollama_models=None)
    sc.run_setup(w.tools(), yes=True)
    assert w.runs[0][:4] == ["winget", "install", "--id", "Gyan.FFmpeg"]
    assert ["winget", "install", "--id", "Ollama.Ollama", *sc.WINGET_FLAGS] in w.runs


@pytest.mark.parametrize(
    "exe,kind",
    [
        ("/Users/me/.local/share/uv/tools/clip-anything/bin/python", "uv-tool"),
        (
            "C:\\Users\\me\\AppData\\Roaming\\uv\\tools\\clip-anything\\Scripts\\python.exe",
            "uv-tool",
        ),
        ("/Users/me/.cache/uv/archive-v0/abc123/bin/python", "uvx"),
        ("/Users/me/.local/pipx/venvs/clip-anything/bin/python", "pipx"),
        ("/Users/me/proj/.venv/bin/python", "venv"),
    ],
)
def test_install_kind(exe, kind):
    assert sc.install_kind(exe) == kind
    assert sc.install_kind(exe, frozen=True) == "frozen"


def test_captions_fix_per_kind():
    assert sc.captions_fix("pipx", "x")[0] == ["pipx", "inject", "clip-anything", "faster-whisper"]
    assert sc.captions_fix("venv", "/v/bin/python")[0] == [
        "/v/bin/python",
        "-m",
        "pip",
        "install",
        "faster-whisper",
    ]
    assert (
        sc.captions_fix("uvx", "x")[0] is None
        and "uvx --with faster-whisper" in sc.captions_fix("uvx", "x")[1]
    )
    assert sc.captions_fix("frozen", "x")[0] is None


def test_cli_dispatch_setup_help_and_main_untouched():
    """`clip-anything setup --help` reaches the setup command; the plain command still parses."""
    r = subprocess.run(
        [sys.executable, "-m", "clip_anything.cli", "setup", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0 and "--no-ai" in r.stdout and "--yes" in r.stdout
    r = subprocess.run(
        [sys.executable, "-m", "clip_anything.cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0 and "--ai" in r.stdout and "--count" in r.stdout
    assert "setup" in r.stdout
