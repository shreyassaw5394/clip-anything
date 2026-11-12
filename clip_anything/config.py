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
    cache: bool = True
    cache_dir: str | None = None


@dataclass
class ScoringOptions:
    # weights of the base mix
    w_loud: float = 1.0
    w_onset: float = 0.8
    w_rms: float = 0.3
    w_motion: float = 0.8
    w_cut: float = 0.15
    w_speech: float = 0.3
    alpha: float = 0.5  # mean/max blend
    z_cap: float = 6.0
    local_window_s: float = 300.0
    smooth_sigma_s: float = 1.0
    prominence: float = 0.1
    height_pct: float = 90.0
    span_frac: float = 0.35
    # informativeness floors (raw units: dB for audio, abs diff for motion)
    floor_loud_db: float = 6.0
    floor_onset: float = 0.5
    floor_rms_db: float = 6.0
    floor_motion: float = 4.0
    lead_frac: float = 0.6
    min_gap_s: float = 30.0
    overlap_frac: float = 0.2


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


@dataclass
class SpeechOptions:
    captions: bool = True
    model: str = "base.en"
    yes: bool = False


@dataclass
class VisionOptions:
    enabled: bool = False
    model: str | None = None


@dataclass
class LayoutOptions:
    facecam: str = "auto"  # auto | off


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
        return f"v{ANALYSIS_SCHEMA}-hop{a.hop_s}-win{a.window_s}-sr{a.sample_rate}"


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
