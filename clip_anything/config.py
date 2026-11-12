"""Layered options: defaults < config file (TOML) < CLI. No global state."""

from __future__ import annotations

import copy
import os
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .errors import InputError

ANALYSIS_SCHEMA = 1  # bump when extractor output changes (invalidates signal cache)


@dataclass
class AnalysisOptions:
    hop_s: float = 0.5
    window_s: float = 1.0
    sample_rate: int = 16000
    chunk_s: float = 30.0
    baseline_s: float = 60.0
    proxy_fps: float = 5.0
    proxy_width: int = 320
    hwaccel: str = "auto"  # auto | none | <ffmpeg hwaccel name>; analysis proxy decode only
    cache: bool = True
    cache_dir: str | None = None
    audio_track: str = "auto"  # auto (mix of non-silent tracks) | all | game | mic | <N>
    resume: bool = True  # pick up <stage>.partial.npz checkpoints left by an interrupted run


@dataclass
class ScoringOptions:
    # weights of the base mix
    w_loud: float = 1.0
    w_onset: float = 0.8
    w_rms: float = 0.3
    w_motion: float = 0.8
    w_cut: float = 0.15
    w_speech: float = 0.3
    # score = w_mean * weighted mean + w_max * max + w_agree * sqrt(audio * motion)
    w_mean: float = 0.2
    w_max: float = 0.4
    w_agree: float = 0.4
    z_soft: float = 4.0  # rolling z-score -> tanh(z / z_soft): no hard saturation at 1.0
    scale_frac: float = 0.25  # sigma floor = scale_frac * global (p90 - p50): flat regions
    local_window_s: float = 300.0
    smooth_sigma_s: float = 0.5  # a 1 s burst must survive smoothing as a peak
    prominence: float = 0.1
    height_pct: float = 50.0
    min_height: float = 0.1
    span_frac: float = 0.35
    # informativeness floors (raw units: dB for audio, abs diff for motion)
    floor_loud_db: float = 6.0
    floor_onset: float = 0.3
    floor_rms_db: float = 6.0
    floor_motion: float = 4.0
    lead_frac: float = 0.6
    min_gap_s: float = 30.0
    overlap_frac: float = 0.2
    # static cards (lobby, menu, loading): score *= 1 - w_card * card
    w_card: float = 0.8
    still_lo: float = 0.92  # video.still below this is never a card (testsrc2 sits at 0.91)
    card_s: float = 10.0  # rolling-median span for the card test (page flips are not motion)
    # intro/outro: first/last edge_s are scaled by edge_factor unless agreement is strong
    edge_s: float = 30.0
    edge_factor: float = 0.8
    edge_agree: float = 0.7
    # --count is a maximum: windows below max(min_score, min_score_rel * best) are never
    # returned (absolute floor for filler, relative floor so a file's own scale counts)
    min_score: float = 0.2
    min_score_rel: float = 0.35
    # absolute bar (02-04): raw signals against FIXED reference levels measured on real
    # footage, so a score means the same thing on every file. A candidate needs evidence
    # >= min_evidence to be returned at all; score *= (1 - w_evidence) + w_evidence * evidence.
    # Reference levels: proxy mean |frame diff| of real combat (COD action 16-45, menus < 12),
    # spectral-flux onset of gunfire/impacts (0.5-1.4; menu clicks 0.2-0.7), dB above the
    # rolling baseline (combat 8-50; music swells 2-14). Needs both audio and video: a file
    # without one is ranked against itself only. min_evidence = 0 turns the bar off.
    min_evidence: float = 0.5
    w_evidence: float = 0.5
    ref_motion: float = 24.0  # proxy mean |diff| that counts as full motion evidence
    ref_onset: tuple[float, float] = (0.25, 0.7)  # onset ramp lo -> hi
    ref_loud: tuple[float, float] = (4.0, 16.0)  # loud_rel ramp (dB above baseline)
    cov_ramp: tuple[float, float] = (0.3, 0.7)  # fraction of the frame changing: lo -> hi
    cov_weight: float = 0.5  # how much confined motion (menus, dialogue boxes) is discounted
    spread_ramp: tuple[float, float] = (0.03, 0.08)  # cspread below lo = a cursor, not action
    loud_alone: float = 0.7  # a loud swell with no onset is at most this much audio evidence
    lone_cap: float = 0.5  # one group alone (audio or video) is at most this much evidence
    evidence_s: float = 1.0  # audio/flash evidence at a peak = max over +- this many seconds
    visual_s: float = 3.0  # motion evidence = mean over +- this many seconds (must persist)
    zero_start_ratio: float = 2.0  # a clip starting at 0:00 needs 2x the median top score
    zero_start_peak_s: float = 10.0  # ...when its peak is inside the first 10 s (an intro)


@dataclass
class ClipOptions:
    count: int = 10
    min_s: float = 15.0
    max_s: float = 45.0


@dataclass
class RenderOptions:
    out_dir: str = "./clips"
    width: int = 1080
    height: int = 1920
    fade_s: float = 0.3
    crf: int = 20
    preset: str = "veryfast"
    audio_bitrate: str = "160k"
    workers: int | None = None  # default max(1, cpu//4)
    force: bool = False
    dry_run: bool = False


DEFAULT_EXCITEMENT_WORDS = [
    "no way",
    "let's go",
    "lets go",
    "oh my god",
    "what",
    "bro",
    "dude",
    "insane",
    "clutch",
    "holy",
    "wow",
    "yes",
    "come on",
    "are you kidding",
    "oh no",
    "nice",
    "sick",
]


@dataclass
class SpeechOptions:
    captions: bool = True
    model: str = "base.en"
    yes: bool = False  # allow the one-time Whisper model download
    rank: bool = False  # transcribe the top 3N candidates and re-rank by excitement (slow)
    excitement_words: list[str] = field(default_factory=lambda: list(DEFAULT_EXCITEMENT_WORDS))
    shout_db: float = 8.0  # a word is a shout when clip RMS sits this far above its median
    min_words: int = 3  # fewer confident words than this -> no captions for the clip
    min_word_prob: float = 0.5
    min_logprob: float = -1.0
    max_no_speech: float = 0.6
    max_words_per_line: int = 4
    highlight: str = "&H0000FFFF"  # ASS BGR: current word in yellow
    font: str = "Arial"
    font_size: int = 80  # at 1080x1920
    margin_v: int = 600  # px from the bottom at 1920 high -> text sits at ~68 % height


@dataclass
class VisionOptions:
    enabled: bool = False
    model: str | None = None


@dataclass
class LayoutOptions:
    facecam: str = "auto"  # auto | off
    crop: str = "follow"  # follow | center
    pan_speed: float = 0.25  # max pan, fraction of source width per second
    deadband: float = 0.06  # ignore target moves smaller than this fraction of crop travel
    min_cutoff: float = 0.4  # One-Euro min cutoff (Hz)
    beta: float = 0.02  # One-Euro speed coefficient
    diffuse_spread: float = 0.24  # median cspread above this = global motion -> centre crop


@dataclass
class Options:
    analysis: AnalysisOptions = field(default_factory=AnalysisOptions)
    scoring: ScoringOptions = field(default_factory=ScoringOptions)
    clips: ClipOptions = field(default_factory=ClipOptions)
    render: RenderOptions = field(default_factory=RenderOptions)
    speech: SpeechOptions = field(default_factory=SpeechOptions)
    vision: VisionOptions = field(default_factory=VisionOptions)
    layout: LayoutOptions = field(default_factory=LayoutOptions)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Options:
        return cls.from_layers(data)

    @classmethod
    def from_layers(cls, *layers: dict[str, Any] | None) -> Options:
        """Deep-merge dict layers (later wins) over defaults; None values are skipped."""
        base = cls().to_dict()
        for layer in layers:
            if not layer:
                continue
            _merge(base, layer, path="")
        return cls(
            analysis=AnalysisOptions(**base["analysis"]),
            scoring=ScoringOptions(**base["scoring"]),
            clips=ClipOptions(**base["clips"]),
            render=RenderOptions(**base["render"]),
            speech=SpeechOptions(**base["speech"]),
            vision=VisionOptions(**base["vision"]),
            layout=LayoutOptions(**base["layout"]),
        )

    def analysis_fingerprint(self) -> str:
        a = self.analysis
        return (
            f"v{ANALYSIS_SCHEMA}-hop{a.hop_s}-win{a.window_s}-sr{a.sample_rate}"
            f"-pfps{a.proxy_fps}-pw{a.proxy_width}"
        )


def _merge(base: dict, layer: dict, path: str) -> None:
    for key, value in layer.items():
        full = f"{path}.{key}" if path else key
        if key not in base:
            raise InputError(f"unknown config key: {full}")
        if isinstance(base[key], dict):
            if not isinstance(value, dict):
                raise InputError(f"config section expected for: {full}")
            _merge(base[key], value, full)
        elif value is not None:
            base[key] = copy.deepcopy(value)


def load_config_file(path: str | os.PathLike | None) -> dict[str, Any]:
    """Resolve config: --config > ./clip-anything.toml > ~/.config/clip-anything/config.toml."""
    candidates: list[Path] = []
    if path is not None:
        p = Path(path)
        if not p.is_file():
            raise InputError(f"config file not found: {p}")
        candidates.append(p)
    else:
        candidates.append(Path("clip-anything.toml"))
        candidates.append(Path.home() / ".config" / "clip-anything" / "config.toml")
    for p in candidates:
        if p.is_file():
            try:
                with open(p, "rb") as fh:
                    return tomllib.load(fh)
            except tomllib.TOMLDecodeError as exc:
                raise InputError(f"bad TOML in {p}: {exc}") from exc
    return {}
