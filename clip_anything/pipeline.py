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
from .cropplan import plan_crop
from .errors import InputError, StageError
from .events import Event, OnEvent, emit
from .probe import FFmpegCaps, MediaInfo, audio_pipe, preflight, probe, video_pipe
from .report import Clip, Report, Stage, Warning
from .scoring import select_candidates
from .video_signals import EXTRACTOR_VERSION as VIDEO_EXTRACTOR_VERSION
from .video_signals import extract_video

AUDIO_NAMES = ("audio.rms_db", "audio.flux", "audio.onset", "audio.loud_rel")
VIDEO_NAMES = (
    "video.motion",
    "video.hist_delta",
    "video.cut",
    "video.flash",
    "video.cx",
    "video.cspread",
)


def _analysis_fingerprint(opts: Options) -> str:
    return f"{opts.analysis_fingerprint()}-audio{EXTRACTOR_VERSION}-video{VIDEO_EXTRACTOR_VERSION}"


def _run_audio(info: MediaInfo, caps: FFmpegCaps, opts: Options, on_event) -> dict:
    a = opts.analysis

    def progress(done: float) -> None:
        emit(on_event, Event("audio", "progress", done, info.duration_s, "s"))

    return extract_audio(
        audio_pipe(info.path, caps, a.sample_rate, a.chunk_s),
        a.sample_rate,
        a.hop_s,
        a.window_s,
        a.baseline_s,
        info.duration_s,
        progress,
    )


def _run_video(info: MediaInfo, caps: FFmpegCaps, opts: Options, on_event) -> dict:
    a = opts.analysis
    pw, ph = info.proxy_size(a.proxy_width)
    if a.hwaccel == "auto":
        # hw decode only pays off on big HEVC/AV1 sources (4K HEVC: 2x faster); on 720p/1080p
        # H.264 videotoolbox was 10x slower than software in measurement
        big = info.width * info.height >= 3000 * 1500 and info.vcodec in ("hevc", "av1")
        hw = caps.hwaccel if big else ""
    else:
        hw = "" if a.hwaccel == "none" else a.hwaccel

    def progress(done: float) -> None:
        emit(on_event, Event("video", "progress", done, info.duration_s, "s"))

    return extract_video(
        video_pipe(info, caps, a.proxy_fps, a.proxy_width, hwaccel=hw),
        a.proxy_fps,
        a.hop_s,
        pw,
        ph,
        info.duration_s,
        progress,
    )


def analyse_signals(
    info: MediaInfo,
    caps: FFmpegCaps,
    opts: Options,
    cache: SignalCache,
    report: Report,
    on_event: OnEvent | None,
) -> dict[str, np.ndarray]:
    """Audio and video extraction in two parallel ffmpeg pipes; both stored in signals.npz.
    A cache written by an older run (audio only) triggers only the missing pass."""
    fp = _analysis_fingerprint(opts)
    cached = cache.get_npz("signals.npz", fp) or {}
    arrays: dict[str, np.ndarray] = dict(cached)
    stages = {"audio": info.has_audio, "video": info.has_video}
    names = {"audio": AUDIO_NAMES, "video": VIDEO_NAMES}
    runners = {"audio": _run_audio, "video": _run_video}
    todo: list[str] = []
    for stage, present in stages.items():
        if not present:
            report.warnings.append(
                Warning(stage, f"no_{stage}", f"no {stage} stream; {stage} signals skipped")
            )
            emit(on_event, Event(stage, "skipped", message=f"no {stage} stream"))
            report.stages.append(Stage(stage, "skipped", 0.0, f"no {stage} stream"))
        elif all(k in cached for k in names[stage]):
            emit(on_event, Event(stage, "cached", info.duration_s, info.duration_s, "s"))
            report.stages.append(Stage(stage, "cached", 0.0))
        else:
            todo.append(stage)
    if not todo:
        return arrays
    results: dict[str, dict | BaseException] = {}
    t0 = time.time()
    walls: dict[str, float] = {}

    def work(stage: str) -> None:
        emit(on_event, Event(stage, "start", 0, info.duration_s, "s"))
        ts = time.time()
        try:
            results[stage] = runners[stage](info, caps, opts, on_event)
        except BaseException as exc:  # surfaced below on the calling thread
            results[stage] = exc
        walls[stage] = time.time() - ts

    threads = [threading.Thread(target=work, args=(st,), daemon=True) for st in todo]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    for stage in todo:
        res = results[stage]
        if isinstance(res, InputError):
            raise StageError(stage, str(res)) from res
        if isinstance(res, BaseException):
            raise res
        arrays.update(res)
        emit(on_event, Event(stage, "done", info.duration_s, info.duration_s, "s"))
    path = cache.put_npz("signals.npz", fp, arrays)
    detail = f"cache={path}" if path else ""
    for stage in todo:
        report.stages.append(Stage(stage, "ok", round(walls[stage], 3), detail))
    report.timings["signals_wall_s"] = round(time.time() - t0, 3)
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
    if info.is_hdr:
        if caps.tonemap:
            report.warnings.append(
                Warning("probe", "hdr", f"HDR source ({info.color_transfer}): tone-mapped to SDR")
            )
        else:
            report.warnings.append(
                Warning(
                    "probe",
                    "hdr",
                    "HDR source: output may look washed out (ffmpeg >= 8 needed to tone-map)",
                )
            )

    cache = SignalCache(info.path, opts.analysis.cache_dir, opts.analysis.cache)
    report.input["id"] = cache.id
    n = int(np.ceil(info.duration_s / opts.analysis.hop_s))
    sig = Signals(hop_s=opts.analysis.hop_s, t0=0.0, n=n, duration_s=info.duration_s)
    sig.meta = {"fingerprint": _analysis_fingerprint(opts), "has_audio": info.has_audio}

    arrays = analyse_signals(info, caps, opts, cache, report, on_event)
    for k, v in arrays.items():
        v = np.asarray(v, dtype=np.float32)
        if v.size < n:
            v = np.pad(v, (0, n - v.size), constant_values=np.nan)
        sig.arrays[k] = v[:n]
    if cancel.is_set():
        raise StageError("audio", "cancelled")
    if not sig.arrays:
        raise StageError("score", "no analysable signals")

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
        crop = plan_crop(sig, c.start, c.end, info, opts.layout, opts.render)
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
                crop=crop.to_dict(),
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
    probe_s = sum(s.wall_s for s in report.stages if s.name == "probe")
    analyze = probe_s + report.timings.get("signals_wall_s", 0.0)
    fresh = any(s.name in ("audio", "video") and s.status == "ok" for s in report.stages)
    report.timings["analyze_s"] = round(analyze, 3)
    report.timings["media_x_realtime"] = (
        round(info.duration_s / analyze, 1) if analyze > 0 and fresh else 0.0
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    report.write(out_dir / "report.json")
    return report
