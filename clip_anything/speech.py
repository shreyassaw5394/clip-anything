"""Speech on the chosen clip windows only: faster-whisper (optional extra `captions`, lazy
import, never at startup), word timestamps, a cheap energy gate before the model, and the
excitement bonus (exclamation words + shouts) used to re-rank candidates."""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .config import SpeechOptions
from .probe import FFmpegCaps, _popen_kwargs

INSTALL_HINT = (
    'pip install "clip-anything[captions]"  (or: uvx --with faster-whisper clip-anything)'
)
MODEL_SIZES_MB = {
    "tiny": 75,
    "tiny.en": 75,
    "base": 145,
    "base.en": 145,
    "small": 480,
    "small.en": 480,
}


@dataclass
class Word:
    start: float  # seconds, relative to the clip start
    end: float
    text: str
    prob: float = 1.0


@dataclass
class Transcript:
    words: list[Word] = field(default_factory=list)
    speech: bool = False  # enough confident words to burn captions
    avg_logprob: float = 0.0
    no_speech_prob: float = 1.0
    model_s: float = 0.0  # wall time spent in the model
    reason: str = ""  # why speech is False

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


# ----------------------------------------------------------------------------- model status


def hf_cache_dir() -> Path:
    home = os.environ.get("HF_HOME")
    base = Path(home) if home else Path.home() / ".cache" / "huggingface"
    return Path(os.environ.get("HF_HUB_CACHE", base / "hub"))


def model_cached(name: str) -> bool:
    """True when the CTranslate2 weights for `name` sit in the Hugging Face cache (no imports)."""
    repo = hf_cache_dir() / f"models--Systran--faster-whisper-{name}"
    return any(repo.glob("snapshots/*/model.bin"))


def model_status(name: str) -> str:
    """'ready' | 'download' (dependency present, weights missing) | 'missing_dep'."""
    try:
        import importlib.util

        if importlib.util.find_spec("faster_whisper") is None:
            return "missing_dep"
    except (ImportError, ValueError):
        return "missing_dep"
    return "ready" if model_cached(name) else "download"


@contextlib.contextmanager
def _quiet_stderr():
    """Point fd 2 at /dev/null for the block. Importing faster-whisper loads a second
    libavdevice next to opencv's and the objc runtime prints a duplicate-class notice
    straight to fd 2 (not via sys.stderr), which tears the progress display. Harmless, so
    it is hidden. Fails open if fds cannot be duplicated."""
    try:
        sys.stderr.flush()
        saved = os.dup(2)
        devnull = os.open(os.devnull, os.O_WRONLY)
    except OSError:
        yield
        return
    try:
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(saved, 2)
        os.close(saved)
        os.close(devnull)


def load_model(name: str, allow_download: bool):
    """Return (model, reason). model is None when captions must be skipped."""
    status = model_status(name)
    if status == "missing_dep":
        return None, f"faster-whisper not installed: {INSTALL_HINT}"
    if status == "download" and not allow_download:
        mb = MODEL_SIZES_MB.get(name, "?")
        return None, f"Whisper model '{name}' (~{mb} MB) not downloaded: rerun with --yes"
    try:
        with _quiet_stderr():
            from faster_whisper import WhisperModel

            try:  # silence the "MPS backend" tip ctranslate2 prints on Apple Silicon
                import ctranslate2

                ctranslate2.set_log_level(40)  # ERROR
            except Exception:
                pass
            cpu = os.cpu_count() or 4
            model = WhisperModel(
                name,
                device="cpu",
                compute_type="int8",
                cpu_threads=max(1, cpu // 2),
                local_files_only=not allow_download,
            )
    except Exception as exc:  # download failure, bad model name, broken install
        return None, f"could not load Whisper model '{name}': {str(exc)[:160]}"
    return model, ""


# ----------------------------------------------------------------------------- audio


def clip_audio(
    path: str | os.PathLike, caps: FFmpegCaps, start: float, dur: float, sr: int = 16000
) -> np.ndarray:
    """float32 mono PCM of one clip window (seek, never the whole file)."""
    cmd = [
        caps.ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{dur:.3f}",
        "-i",
        os.fspath(path),
        "-vn",
        "-sn",
        "-dn",
        "-map",
        "0:a:0",
        "-ac",
        "1",
        "-ar",
        str(sr),
        "-f",
        "f32le",
        "-",
    ]
    res = subprocess.run(cmd, capture_output=True, check=False, **_popen_kwargs())
    if res.returncode != 0:
        return np.zeros(0, dtype=np.float32)
    return np.frombuffer(res.stdout, dtype=np.float32)


def energy_gate(pcm: np.ndarray, sr: int = 16000, floor_db: float = -45.0) -> bool:
    """Cheap pre-check: any 100 ms frame above `floor_db` dBFS? False -> skip the model."""
    if pcm.size < sr // 10:
        return False
    n = sr // 10
    frames = pcm[: pcm.size // n * n].reshape(-1, n).astype(np.float64)
    rms = np.sqrt((frames**2).mean(axis=1) + 1e-12)
    return bool((20 * np.log10(rms)).max() > floor_db)


# ----------------------------------------------------------------------------- transcription


def transcribe(model, pcm: np.ndarray, opts: SpeechOptions, sr: int = 16000) -> Transcript:
    """Word-timestamped transcript of one clip's audio; speech=True only when enough confident
    words exist (avg logprob above the floor, no_speech_prob below the ceiling)."""
    tr = Transcript()
    if not energy_gate(pcm, sr):
        tr.reason = "silent"
        return tr
    t0 = time.time()
    lang = "en" if opts.model.endswith(".en") else None
    segments, _info = model.transcribe(
        pcm,
        beam_size=1,
        word_timestamps=True,
        vad_filter=True,
        language=lang,
        condition_on_previous_text=False,
    )
    logprobs: list[float] = []
    nsp: list[float] = []
    for seg in segments:
        logprobs.append(float(seg.avg_logprob))
        nsp.append(float(seg.no_speech_prob))
        if float(seg.no_speech_prob) > opts.max_no_speech:
            continue
        for w in seg.words or []:
            text = w.word.strip()
            if not text:
                continue
            tr.words.append(Word(float(w.start), float(w.end), text, float(w.probability)))
    tr.model_s = round(time.time() - t0, 3)
    if logprobs:
        tr.avg_logprob = float(np.mean(logprobs))
        tr.no_speech_prob = float(np.mean(nsp))
    good = [w for w in tr.words if w.prob >= opts.min_word_prob]
    if len(good) >= opts.min_words and tr.avg_logprob >= opts.min_logprob:
        tr.speech = True
    else:
        tr.reason = "no confident speech" if tr.words else "no speech"
        tr.words = []
    return tr


# ----------------------------------------------------------------------------- excitement


_WORD_RE = re.compile(r"[^a-z' ]+")


def _norm(text: str) -> str:
    return _WORD_RE.sub(" ", text.lower()).strip()


def excitement_bonus(
    tr: Transcript, opts: SpeechOptions, rms_db: np.ndarray | None = None, hop_s: float = 0.5
) -> tuple[float, dict]:
    """0..1 bonus: exclamation phrases from the config list (each 0.25, capped) + shouts
    (a word spoken while the clip's RMS sits >= shout_db above its own median)."""
    if not tr.words:
        return 0.0, {"phrases": 0, "shouts": 0}
    text = " " + _norm(tr.text) + " "
    phrases = sum(text.count(" " + _norm(p) + " ") for p in opts.excitement_words)
    shouts = 0
    if rms_db is not None and rms_db.size > 2:
        r = np.asarray(rms_db, dtype=np.float64)
        r = np.where(np.isfinite(r), r, np.nan)
        med = np.nanmedian(r)
        if np.isfinite(med):
            for w in tr.words:
                i = int(np.clip(round((w.start + w.end) / 2 / hop_s), 0, r.size - 1))
                if np.isfinite(r[i]) and r[i] - med >= opts.shout_db:
                    shouts += 1
    bonus = min(1.0, 0.25 * phrases + 0.15 * min(shouts, 4))
    return round(bonus, 4), {"phrases": int(phrases), "shouts": int(shouts)}
