"""Library entry point: run(video, options, on_event, cancel) -> Report. No prints, no exits."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import numpy as np

from .audio_signals import EXTRACTOR_VERSION, Signals, extract_audio
from .cache import SignalCache
from .config import Options
from .errors import InputError, StageError
from .events import Event, OnEvent, emit
from .probe import FFmpegCaps, MediaInfo, audio_pipe, preflight, probe
from .report import Clip, Report, Stage, Warning
from .scoring import select_candidates

AUDIO_NAMES = ("audio.rms_db", "audio.flux", "audio.onset", "audio.loud_rel")


def _analysis_fingerprint(opts: Options) -> str:
    return f"{opts.analysis_fingerprint()}-audio{EXTRACTOR_VERSION}"


def analyse_audio(
    info: MediaInfo,
    caps: FFmpegCaps,
    opts: Options,
    cache: SignalCache,
    report: Report,
    on_event: OnEvent | None,
) -> dict[str, np.ndarray]:
    a = opts.analysis
    fp = _analysis_fingerprint(opts)
    t0 = time.time()
    cached = cache.get_npz("signals.npz", fp)
    if cached is not None and all(k in cached for k in AUDIO_NAMES):
        emit(on_event, Event("audio", "cached", info.duration_s, info.duration_s, "s"))
        report.stages.append(Stage("audio", "cached", round(time.time() - t0, 3)))
        return cached
    emit(on_event, Event("audio", "start", 0, info.duration_s, "s"))

    def progress(done: float) -> None:
        emit(on_event, Event("audio", "progress", done, info.duration_s, "s"))

    try:
        arrays = extract_audio(
            audio_pipe(info.path, caps, a.sample_rate, a.chunk_s),
            a.sample_rate,
            a.hop_s,
            a.window_s,
            a.baseline_s,
            info.duration_s,
            progress,
        )
    except InputError as exc:
        raise StageError("audio", str(exc)) from exc
    emit(on_event, Event("audio", "done", info.duration_s, info.duration_s, "s"))
    path = cache.put_npz("signals.npz", fp, arrays)
    report.stages.append(
        Stage("audio", "ok", round(time.time() - t0, 3), f"cache={path}" if path else "")
    )
    return arrays


def run(
    video: str | os.PathLike,
    opts: Options | None = None,
    on_event: OnEvent | None = None,
    cancel: threading.Event | None = None,
    caps: FFmpegCaps | None = None,
) -> Report:
    """Analyse `video`, pick clips and (unless dry_run) render them. Raises InputError,
    FFmpegMissing or StageError; optional-stage problems become report.warnings."""
    opts = opts or Options()
    cancel = cancel or threading.Event()
    t_start = time.time()
    caps = caps or preflight()

    emit(on_event, Event("probe", "start"))
    t0 = time.time()
    info = probe(video, caps)
    report = Report(
        input={
            "path": info.path,
            "id": "",
            "duration_s": info.duration_s,
            "width": info.width,
            "height": info.height,
            "fps": info.fps,
            "has_audio": info.has_audio,
            "has_video": info.has_video,
            "vcodec": info.vcodec,
            "pix_fmt": info.pix_fmt,
        },
        options=opts.to_dict(),
    )
    report.stages.append(Stage("probe", "ok", round(time.time() - t0, 3)))
    emit(
        on_event,
        Event("probe", "done", message=f"{info.duration_s:.0f}s {info.width}x{info.height}"),
    )
    if not info.has_video:
        raise InputError("input has no video stream")
    if info.color_transfer in ("smpte2084", "arib-std-b67"):
        report.warnings.append(
            Warning("probe", "hdr", "HDR source: output may look washed out (no tone-map in v1)")
        )

    cache = SignalCache(info.path, opts.analysis.cache_dir, opts.analysis.cache)
    report.input["id"] = cache.id
    n = int(np.ceil(info.duration_s / opts.analysis.hop_s))
    sig = Signals(hop_s=opts.analysis.hop_s, t0=0.0, n=n, duration_s=info.duration_s)
    sig.meta = {"fingerprint": _analysis_fingerprint(opts), "has_audio": info.has_audio}

    if info.has_audio:
        arrays = analyse_audio(info, caps, opts, cache, report, on_event)
        for k, v in arrays.items():
            v = np.asarray(v, dtype=np.float32)
            if v.size < n:
                v = np.pad(v, (0, n - v.size), constant_values=np.nan)
            sig.arrays[k] = v[:n]
    else:
        report.warnings.append(
            Warning("audio", "no_audio", "no audio stream; audio signals skipped")
        )
        emit(on_event, Event("audio", "skipped", message="no audio stream"))
        report.stages.append(Stage("audio", "skipped", 0.0, "no audio stream"))
    if cancel.is_set():
        raise StageError("audio", "cancelled")
    if not sig.arrays:
        raise StageError("score", "no analysable signals (no audio stream)")

    emit(on_event, Event("score", "start"))
    t0 = time.time()
    top, total, _sm = select_candidates(
        sig, opts.scoring, opts.clips.count, opts.clips.min_s, opts.clips.max_s
    )
    report.candidates_total = total
    report.stages.append(Stage("score", "ok", round(time.time() - t0, 3), f"{total} candidates"))
    report.signals = {
        "cache_path": str(cache.path("signals.npz")) if cache.enabled else "",
        "names": sorted(sig.arrays),
        "hop_s": sig.hop_s,
    }
    for rank, c in enumerate(top, start=1):
        report.clips.append(
            Clip(
                rank=rank,
                candidate_id=c.id,
                start=c.start,
                end=c.end,
                duration_s=round(c.duration_s, 3),
                score=c.score,
                components=c.components,
                peak_t=c.peak_t,
                snap=c.snap,
                status="pending",
            )
        )
    emit(on_event, Event("score", "done", message=f"{len(top)} clips from {total} candidates"))
    if not top:
        report.warnings.append(Warning("score", "no_peaks", "no action peaks found"))

    out_dir = Path(opts.render.out_dir)
    report.out_dir = str(out_dir)
    if opts.render.dry_run:
        for c in report.clips:
            c.status = "skipped"
        emit(on_event, Event("render", "skipped", message="dry run"))
    elif report.clips:
        from .render import render_all

        t0 = time.time()
        render_all(info, caps, opts, report, on_event, cancel)
        report.timings["render_s"] = round(time.time() - t0, 3)

    report.timings["total_s"] = round(time.time() - t_start, 3)
    analyze = sum(s.wall_s for s in report.stages if s.name in ("probe", "audio", "video"))
    fresh = any(s.name in ("audio", "video") and s.status == "ok" for s in report.stages)
    report.timings["analyze_s"] = round(analyze, 3)
    report.timings["media_x_realtime"] = (
        round(info.duration_s / analyze, 1) if analyze > 0 and fresh else 0.0
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    report.write(out_dir / "report.json")
    return report
