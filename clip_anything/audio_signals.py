"""Streaming audio features per 0.5 s hop from a 16 kHz mono PCM stream.

Raw signals (normalisation is scoring's job):
  audio.rms_db   window RMS in dBFS
  audio.flux     max spectral flux (onset strength) inside the window
  audio.onset    same as flux but half-wave rectified against the previous window (sharpness)
  audio.loud_rel rms_db minus rolling 60 s median (dB above the local baseline), computed at the end
  audio.centroid spectral centroid (Hz) of the window, energy-weighted over its STFT frames
  audio.flat     spectral flatness (0 tone .. 1 noise) at the frame with the strongest flux
  audio.mod      share of the frame-energy envelope's AC power between 3 and 8 Hz (laughter
                 syllable rate; automatic fire sits above 10 Hz, music swells below 2 Hz)
  audio.voice_react laughter / shout 0..1 (finalize): loud over the baseline, centroid in the
                 voice band, voiced (low flatness) and either modulated like laughter or
                 sustained like a shout. Cheap and approximate; a bonus, never a gate.
  audio.stinger  tonal onset 0..1 (finalize): a level jump with a near-tonal spectrum (a music
                 hit, a level-up chime), not broadband noise (shots, impacts)
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

import numpy as np

EXTRACTOR_VERSION = 2
N_FFT = 1024
HOP = 256


@dataclass
class Signals:
    hop_s: float
    t0: float
    n: int
    duration_s: float
    arrays: dict[str, np.ndarray] = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    def times(self) -> np.ndarray:
        return self.t0 + np.arange(self.n, dtype=np.float64) * self.hop_s

    def index_of(self, t: float) -> int:
        return int(np.clip(round((t - self.t0) / self.hop_s), 0, max(self.n - 1, 0)))


class AudioExtractor:
    """Feed int16 PCM chunks of any size; results are identical regardless of chunking."""

    def __init__(self, sample_rate: int = 16000, hop_s: float = 0.5, window_s: float = 1.0):
        self.sr = sample_rate
        self.hop_s = hop_s
        self.hop = int(round(sample_rate * hop_s))
        self.win = int(round(sample_rate * window_s))
        self._buf = np.zeros(0, dtype=np.float32)
        self._consumed = 0  # samples already dropped from the front of _buf
        self._prev_mag: np.ndarray | None = None  # last STFT magnitude frame seen
        self._hann = np.hanning(N_FFT).astype(np.float32)
        self.rms_db: list[float] = []
        self.flux: list[float] = []
        self.onset: list[float] = []
        self.centroid: list[float] = []
        self.flat: list[float] = []
        self.mod: list[float] = []
        self._freqs = np.fft.rfftfreq(N_FFT, 1.0 / sample_rate).astype(np.float32)
        self._prev_flux = 0.0
        self._hops_done = 0

    def feed(self, pcm: bytes) -> None:
        x = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        self._buf = np.concatenate([self._buf, x]) if self._buf.size else x
        self._drain(final=False)

    def finish(self) -> None:
        self._drain(final=True)

    def _drain(self, final: bool) -> None:
        # window i covers samples [i*hop, i*hop + win); emit when complete (or at end, padded)
        while True:
            start = len(self.rms_db) * self.hop - self._consumed
            end = start + self.win
            if end > self._buf.size:
                if not final or start >= self._buf.size:
                    break
                seg = np.zeros(self.win, dtype=np.float32)
                seg[: self._buf.size - start] = self._buf[start:]
            else:
                seg = self._buf[start:end]
            self._emit(seg)
            # drop fully consumed samples (keep one window of overlap)
            next_start = len(self.rms_db) * self.hop - self._consumed
            if next_start > 0:
                self._buf = self._buf[next_start:]
                self._consumed += next_start

    def _emit(self, seg: np.ndarray) -> None:
        i = len(self.rms_db)
        rms = float(np.sqrt(np.mean(seg * seg) + 1e-12))
        self.rms_db.append(20.0 * np.log10(rms + 1e-6))
        # flux per hop j (material [j*hop, (j+1)*hop)), stored at index j so that rms[i] and
        # flux[i] both start at t = i*hop. Hop j lives in this window at offset (j - i)*hop.
        last_hop = i + self.win // self.hop - 1
        while self._hops_done <= last_hop:
            j = self._hops_done
            off = (j - i) * self.hop
            self._emit_hop(seg[off : off + self.hop])
            self._hops_done += 1

    def _emit_hop(self, hop_seg: np.ndarray) -> None:
        if hop_seg.size < N_FFT:
            hop_seg = np.pad(hop_seg, (0, N_FFT - hop_seg.size))
        frames = np.lib.stride_tricks.sliding_window_view(hop_seg, N_FFT)[::HOP]
        mag = np.log1p(10.0 * np.abs(np.fft.rfft(frames * self._hann, axis=1)))
        prev = self._prev_mag if self._prev_mag is not None else mag[:1]
        diff = np.diff(np.concatenate([prev, mag], axis=0), axis=0)
        flux_frames = np.sum(np.maximum(diff, 0.0), axis=1) / N_FFT
        f = float(flux_frames.max()) if flux_frames.size else 0.0
        self.flux.append(f)
        self.onset.append(max(0.0, f - self._prev_flux))
        self._prev_flux = f
        self._prev_mag = mag[-1:]
        self._emit_timbre(mag, flux_frames)

    def _emit_timbre(self, mag: np.ndarray, flux_frames: np.ndarray) -> None:
        """Centroid / flatness / 3-8 Hz envelope modulation of one hop from its log-magnitude
        frames (frame rate sample_rate / HOP = 62.5 Hz)."""
        lin = np.expm1(mag) * 0.1  # back to linear magnitude
        energy = lin.sum(axis=1) + 1e-9
        cen = float(((lin @ self._freqs) / energy * energy).sum() / energy.sum())
        self.centroid.append(cen)
        k = int(np.argmax(flux_frames)) if flux_frames.size else 0
        spec = lin[min(k, lin.shape[0] - 1)][1:] + 1e-9
        self.flat.append(float(np.exp(np.mean(np.log(spec))) / np.mean(spec)))
        env = energy - energy.mean()
        if env.size >= 8 and float(np.abs(env).max()) > 0:
            spec_env = np.abs(np.fft.rfft(env * np.hanning(env.size))) ** 2
            fr = np.fft.rfftfreq(env.size, HOP / self.sr)
            ac = spec_env[1:].sum() + 1e-12
            band = spec_env[(fr >= 3.0) & (fr <= 8.0)].sum()
            self.mod.append(float(band / ac))
        else:
            self.mod.append(0.0)

    def result(self, duration_s: float) -> dict[str, np.ndarray]:
        n = len(self.rms_db)
        return {
            "audio.rms_db": np.asarray(self.rms_db, dtype=np.float32),
            "audio.flux": np.asarray(self.flux[:n], dtype=np.float32),
            "audio.onset": np.asarray(self.onset[:n], dtype=np.float32),
            "audio.centroid": np.asarray(self.centroid[:n], dtype=np.float32),
            "audio.flat": np.asarray(self.flat[:n], dtype=np.float32),
            "audio.mod": np.asarray(self.mod[:n], dtype=np.float32),
        }


def rolling_median(x: np.ndarray, size: int) -> np.ndarray:
    from scipy.ndimage import median_filter

    size = max(3, int(size) | 1)
    return median_filter(x, size=size, mode="nearest")


def _ramp(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return np.clip((x - lo) / max(hi - lo, 1e-9), 0.0, 1.0)


# voice band for laughter / shouts (centroid, Hz): full weight inside, fading to 0 outside
VOICE_BAND = (300.0, 700.0, 2200.0, 3400.0)


def voice_react(
    loud_rel: np.ndarray, centroid: np.ndarray, flat: np.ndarray, mod: np.ndarray
) -> np.ndarray:
    """Laughter / shout 0..1 per window from the raw timbre signals.
    laugh = clearly over the baseline x voiced x 3-8 Hz envelope modulation
    shout = well over the baseline x voiced, sustained for two windows
    Gunfire is broadband (flatness high, centroid high) and auto fire modulates above 10 Hz;
    music swells are tonal but barely modulated and rarely in the band for long."""
    lo, a, b, hi = VOICE_BAND
    band = np.minimum(_ramp(centroid, lo, a), 1.0 - _ramp(centroid, b, hi))
    # voiced = harmonic but rough (0.1-0.3); a pure tone or chord (< 0.05) is music, not a voice
    voiced = _ramp(flat, 0.04, 0.1) * (1.0 - _ramp(flat, 0.25, 0.55))
    laugh = _ramp(loud_rel, 3.0, 10.0) * _ramp(mod, 0.3, 0.6)
    shout = _ramp(loud_rel, 6.0, 14.0)
    if shout.size > 1:  # sustained: both this window and a neighbour
        shout = np.maximum(
            np.minimum(shout, np.concatenate([shout[1:], shout[-1:]])),
            np.minimum(shout, np.concatenate([shout[:1], shout[:-1]])),
        )
    return np.clip(band * voiced * np.maximum(laugh, shout), 0.0, 1.0).astype(np.float32)


def stinger(rms_db: np.ndarray, flat: np.ndarray) -> np.ndarray:
    """Tonal onset 0..1: a level jump of 6-15 dB on one window whose spectrum is near-tonal
    (spectral flux hardly moves for a clean chord, so the jump is read from the level)."""
    jump = np.diff(rms_db, prepend=rms_db[:1])
    # the 1 s level window sees the jump one hop before the hop whose spectrum is the hit
    flat_now = np.minimum(flat, np.concatenate([flat[1:], flat[-1:]])) if flat.size > 1 else flat
    return (_ramp(jump, 6.0, 15.0) * (1.0 - _ramp(flat_now, 0.08, 0.25))).astype(np.float32)


def finalize(arrays: dict[str, np.ndarray], hop_s: float, baseline_s: float) -> None:
    """Add audio.loud_rel = rms_db - rolling median (dB over local baseline), then the
    derived audio.voice_react and audio.stinger when the timbre signals are present."""
    rms = arrays["audio.rms_db"].astype(np.float32)
    if rms.size == 0:
        arrays["audio.loud_rel"] = rms.copy()
        return
    base = rolling_median(rms, int(baseline_s / hop_s))
    arrays["audio.loud_rel"] = (rms - base).astype(np.float32)
    n = rms.size
    cen, flat, mod = (arrays.get(k) for k in ("audio.centroid", "audio.flat", "audio.mod"))
    if cen is not None and flat is not None and mod is not None and cen.size == n:
        arrays["audio.voice_react"] = voice_react(arrays["audio.loud_rel"], cen, flat, mod)
        arrays["audio.stinger"] = stinger(rms, flat)


def extract_audio(
    chunks: Iterable[bytes],
    sample_rate: int,
    hop_s: float,
    window_s: float,
    baseline_s: float,
    duration_s: float,
    progress=None,
) -> dict[str, np.ndarray]:
    ex = AudioExtractor(sample_rate, hop_s, window_s)
    fed = 0
    for buf in chunks:
        ex.feed(buf)
        fed += len(buf) // 2
        if progress is not None:
            progress(min(duration_s, fed / sample_rate))
    ex.finish()
    arrays = ex.result(duration_s)
    finalize(arrays, hop_s, baseline_s)
    return arrays
