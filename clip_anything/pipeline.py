"""Library entry point: run(video, options, on_event, cancel) -> Report. No prints, no exits."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import numpy as np

from .audio_signals import EXTRACTOR_VERSION, Signals
from .cache import SignalCache
from .config import Options
from .cropplan import plan_crop
from .errors import InputError, StageError
from .events import Event, OnEvent, emit
from .inputs import (
    Session,
    audio_roles,
    build_session,
    choose_track,
    clamp_to_source,
    concat_arrays,
    discover,
    probe_all,
)
from .probe import FFmpegCaps, MediaInfo, audio_pipe, preflight, probe, video_pipe
from .report import Clip, Report, Stage, Warning
from .scoring import Candidate, action_score, make_window, select_candidates, smooth
from .video_signals import EXTRACTOR_VERSION as VIDEO_EXTRACTOR_VERSION
from .video_signals import extract_video
from .video_signals import finalize as video_finalize

SEGMENT_S = 900.0  # analysis checkpoint every 15 min of media (resume after a kill)

AUDIO_NAMES = ("audio.rms_db", "audio.flux", "audio.onset", "audio.loud_rel")
VIDEO_NAMES = (
    "video.motion",
    "video.hist_delta",
    "video.cut",
    "video.flash",
    "video.cx",
    "video.cspread",
    "video.still",
    "video.stroke",
)


def _analysis_fingerprint(opts: Options) -> str:
    return f"{opts.analysis_fingerprint()}-audio{EXTRACTOR_VERSION}-video{VIDEO_EXTRACTOR_VERSION}"


def _segments(start_s: float, duration_s: float, seg_s: float | None = None):
    """(start, length) pieces from start_s to the end; lengths are whole seconds so the 5 fps
    proxy and the 0.5 s hop grid line up at every boundary."""
    seg_s = SEGMENT_S if seg_s is None else seg_s
    t = start_s
    while t < duration_s - 1e-6:
        length = min(seg_s, duration_s - t)
        yield t, length
        t += length


def _run_audio(
    info: MediaInfo,
    caps: FFmpegCaps,
    opts: Options,
    on_event,
    track: int | str = 0,
    prefix: dict[str, np.ndarray] | None = None,
    checkpoint=None,
) -> dict:
    """Whole file through one chunk-invariant extractor; the pipe is restarted per segment
    (`-ss`/`-t` before `-i`) only to leave a checkpoint behind. `prefix` = arrays from an
    earlier, interrupted run: the pipe starts where they end."""
    from .audio_signals import AudioExtractor, finalize

    a = opts.analysis
    done_s = 0.0
    pre = {
        k: np.asarray(v, np.float32) for k, v in (prefix or {}).items() if k.startswith("audio.")
    }
    if pre:
        done_s = len(pre["audio.rms_db"]) * a.hop_s
    ex = AudioExtractor(a.sample_rate, a.hop_s, a.window_s)
    n_tracks = len(info.audio_streams)
    for seg_start, seg_len in _segments(done_s, info.duration_s):
        fed = 0
        for buf in audio_pipe(
            info.path, caps, a.sample_rate, a.chunk_s, seg_start, seg_len, track, n_tracks
        ):
            ex.feed(buf)
            fed += len(buf) // 2
            emit(
                on_event,
                Event(
                    "audio",
                    "progress",
                    min(info.duration_s, seg_start + fed / a.sample_rate),
                    info.duration_s,
                    "s",
                ),
            )
        if checkpoint is not None and seg_start + seg_len < info.duration_s - 1e-6:
            part = ex.result(seg_start + seg_len)
            part = {k: np.concatenate([pre[k], v]) if pre else v for k, v in part.items()}
            checkpoint(part)
    ex.finish()
    arrays = ex.result(info.duration_s - done_s)
    if pre:
        arrays = {k: np.concatenate([pre[k], arrays[k]]) for k in arrays}
    finalize(arrays, a.hop_s, a.baseline_s)
    return arrays


def _run_video(
    info: MediaInfo,
    caps: FFmpegCaps,
    opts: Options,
    on_event,
    prefix: dict[str, np.ndarray] | None = None,
    checkpoint=None,
) -> dict:
    a = opts.analysis
    pw, ph = info.proxy_size(a.proxy_width)
    if a.hwaccel == "auto":
        # hw decode only pays off on big HEVC/AV1 sources (4K HEVC: 2x faster); on 720p/1080p
        # H.264 videotoolbox was 10x slower than software in measurement
        big = info.width * info.height >= 3000 * 1500 and info.vcodec in ("hevc", "av1")
        hw = caps.hwaccel if big else ""
    else:
        hw = "" if a.hwaccel == "none" else a.hwaccel
    pre = {
        k: np.asarray(v, np.float32)
        for k, v in (prefix or {}).items()
        if k.startswith("video.") and k != "video.cut"
    }
    parts: list[dict[str, np.ndarray]] = [pre] if pre else []
    done_s = len(pre["video.motion"]) * a.hop_s if pre else 0.0

    for seg_start, seg_len in _segments(done_s, info.duration_s):

        def progress(done: float, _s=seg_start) -> None:
            emit(
                on_event,
                Event("video", "progress", min(info.duration_s, _s + done), info.duration_s, "s"),
            )

        arrays = extract_video(
            video_pipe(
                info,
                caps,
                a.proxy_fps,
                a.proxy_width,
                hwaccel=hw,
                start_s=seg_start,
                duration_s=seg_len,
            ),
            a.proxy_fps,
            a.hop_s,
            pw,
            ph,
            seg_len,
            progress,
        )
        n_seg = (
            int(round(seg_len / a.hop_s)) if seg_start + seg_len < info.duration_s - 1e-6 else None
        )
        arrays.pop("video.cut", None)
        if n_seg is not None:
            arrays = {k: v[:n_seg] for k, v in arrays.items()}
        parts.append(arrays)
        if checkpoint is not None and n_seg is not None:
            checkpoint(_concat_parts(parts))
    out = _concat_parts(parts)
    video_finalize(out)
    return out


def _concat_parts(parts: list[dict[str, np.ndarray]]) -> dict[str, np.ndarray]:
    keys = [k for k in parts[0]] if parts else []
    return {
        k: np.concatenate([np.asarray(p[k], np.float32) for p in parts if k in p]) for k in keys
    }


def analyse_signals(
    info: MediaInfo,
    caps: FFmpegCaps,
    opts: Options,
    cache: SignalCache,
    report: Report,
    on_event: OnEvent | None,
    audio_track: int | str = 0,
    resume: bool = True,
) -> dict[str, np.ndarray]:
    """Audio and video extraction in two parallel ffmpeg pipes; both stored in signals.npz.
    A cache written by an older run (audio only) triggers only the missing pass. Every
    SEGMENT_S of media each pass leaves <stage>.partial.npz behind; a run killed mid-way
    resumes from it (same fingerprint), the partials are removed on completion."""
    fp = _analysis_fingerprint(opts) + f"-atrack{audio_track}"
    cached = cache.get_npz("signals.npz", fp) or {}
    arrays: dict[str, np.ndarray] = dict(cached)
    stages = {"audio": info.has_audio, "video": info.has_video}
    names = {"audio": AUDIO_NAMES, "video": VIDEO_NAMES}
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
    resumed: dict[str, float] = {}

    def work(stage: str) -> None:
        emit(on_event, Event(stage, "start", 0, info.duration_s, "s"))
        ts = time.time()
        part_name = f"{stage}.partial.npz"
        prefix = (cache.get_npz(part_name, fp) or {}) if resume else {}
        prefix = {k: v for k, v in prefix.items() if k.startswith(stage + ".")}
        if prefix:
            first = next(iter(prefix.values()))
            resumed[stage] = len(first) * opts.analysis.hop_s

        def checkpoint(arrs: dict[str, np.ndarray]) -> None:
            cache.put_npz(part_name, fp, arrs)

        try:
            if stage == "audio":
                results[stage] = _run_audio(
                    info, caps, opts, on_event, audio_track, prefix, checkpoint
                )
            else:
                results[stage] = _run_video(info, caps, opts, on_event, prefix, checkpoint)
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
    for stage in todo:
        try:
            cache.path(f"{stage}.partial.npz").unlink(missing_ok=True)
        except OSError:
            pass
    detail = f"cache={path}" if path else ""
    for stage in todo:
        extra = f" resumed at {resumed[stage]:.0f}s" if stage in resumed else ""
        report.stages.append(Stage(stage, "ok", round(walls[stage], 3), detail + extra))
    if "video" in walls and walls["video"] > info.duration_s and info.duration_s > 60:
        report.warnings.append(
            Warning(
                "video",
                "slow_decode",
                f"video decode slower than real time ({info.duration_s / walls['video']:.2f}x; "
                f"{info.vcodec} {info.width}x{info.height}): a software decoder is the bottleneck",
            )
        )
    report.timings["signals_wall_s"] = round(time.time() - t0, 3)
    return arrays


def _speech_stage(
    info: MediaInfo,
    caps: FFmpegCaps,
    opts: Options,
    sig: Signals,
    cands: list,
    report: Report,
    on_event: OnEvent | None,
    cancel: threading.Event,
) -> dict[int, object]:
    """Transcribe the candidate windows only (never the whole file); excitement bonus into the
    score; returns {candidate id: Transcript}. Any problem -> one warning, speech skipped."""
    from .speech import clip_audio, excitement_bonus, load_model, transcribe

    sp = opts.speech
    out: dict[int, object] = {}
    if not cands or not info.has_audio:
        return out
    t0 = time.time()
    emit(on_event, Event("speech", "start", 0, len(cands), "clips"))
    model, reason = load_model(sp.model, allow_download=sp.yes)
    if model is None:
        report.warnings.append(Warning("speech", "captions_off", f"captions skipped: {reason}"))
        report.stages.append(Stage("speech", "skipped", round(time.time() - t0, 3), reason))
        emit(on_event, Event("speech", "skipped", message=reason))
        return out
    rms = sig.arrays.get("audio.rms_db")
    model_s = 0.0
    for i, c in enumerate(cands, start=1):
        if cancel.is_set():
            break
        try:
            pcm = clip_audio(info.path, caps, c.start, c.end - c.start, opts.analysis.sample_rate)
            tr = transcribe(model, pcm, sp, opts.analysis.sample_rate)
        except Exception as exc:  # noqa: BLE001 - optional stage: never fail the run
            reason = f"{type(exc).__name__}: {str(exc)[:160]}"
            for done in cands:
                done.components.pop("speech", None)
            report.warnings.append(Warning("speech", "captions_off", f"captions skipped: {reason}"))
            report.stages.append(Stage("speech", "failed", round(time.time() - t0, 3), reason))
            emit(on_event, Event("speech", "skipped", message=reason))
            return {}
        model_s += tr.model_s
        window = None
        if rms is not None:
            window = rms[sig.index_of(c.start) : sig.index_of(c.end) + 1]
        bonus, detail = excitement_bonus(tr, sp, window, sig.hop_s)
        c.components["speech"] = bonus
        c.score = round(c.score + opts.scoring.w_speech * bonus, 4)
        c.features["speech"] = {
            "words": len(tr.words),
            "bonus": bonus,
            **detail,
            "model_s": tr.model_s,
            "reason": tr.reason,
        }
        out[c.id] = tr
        emit(on_event, Event("speech", "progress", i, len(cands), "clips"))
    spoken = sum(1 for tr in out.values() if getattr(tr, "speech", False))
    detail = f"{spoken}/{len(out)} with speech, model {model_s:.1f}s ({sp.model})"
    report.stages.append(Stage("speech", "ok", round(time.time() - t0, 3), detail))
    report.timings["speech_model_s"] = round(model_s, 3)
    emit(on_event, Event("speech", "done", len(cands), len(cands), "clips", message=detail))
    return out


def _facecam_stage(
    info: MediaInfo, caps: FFmpegCaps, opts: Options, report: Report, on_event: OnEvent | None
):
    from .facecam import detect_facecam

    t0 = time.time()
    emit(on_event, Event("facecam", "start"))
    try:
        fc = detect_facecam(info, caps)
    except Exception as exc:  # optional layer: never blocks a clip
        report.warnings.append(Warning("facecam", "facecam_error", f"facecam detect: {exc}"))
        fc = None
    detail = f"{fc.corner} conf {fc.confidence:.2f}" if fc else "none"
    report.stages.append(Stage("facecam", "ok", round(time.time() - t0, 3), detail))
    emit(on_event, Event("facecam", "done", message=detail))
    return fc


def _write_captions(report: Report, transcripts: dict, opts: Options, caps: FFmpegCaps, stem: str):
    from .captions import build_ass, write_ass
    from .render import clip_filename

    out_dir = Path(opts.render.out_dir)
    n = 0
    for c in report.clips:
        tr = transcripts.get(c.candidate_id)
        if tr is None or not tr.speech:
            continue
        name = clip_filename(stem, c.rank, c.start)
        text = build_ass(
            tr.words, opts.speech, opts.render.width, opts.render.height, c.end - c.start
        )
        c.captions_path = str(write_ass(out_dir / (name[:-4] + ".ass"), text))
        c.captions = True
        c.transcript = tr.text
        n += 1
    if n and not caps.captions:
        report.warnings.append(
            Warning(
                "render",
                "no_libass",
                f"ffmpeg has no libass: {n} caption file(s) written next to the clips, "
                "not burned in (macOS: brew install ffmpeg-full)",
            )
        )


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
    paths = discover([video] if isinstance(video, (str, os.PathLike)) else list(video))
    if len(paths) > 1:
        return _run_many(paths, opts, on_event, cancel, caps, t_start)
    video = paths[0]

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
            "container": info.container,
            "audio_streams": len(info.audio_streams),
        },
        options=opts.to_dict(),
    )
    track = _pick_audio_track(info, caps, opts, report)
    report.stages.append(Stage("probe", "ok", round(time.time() - t0, 3)))
    emit(
        on_event,
        Event("probe", "done", message=f"{info.duration_s:.0f}s {info.width}x{info.height}"),
    )
    if not info.has_video:
        raise InputError("input has no video stream")
    _source_warnings(info, caps, report)

    cache = SignalCache(info.path, opts.analysis.cache_dir, opts.analysis.cache)
    report.input["id"] = cache.id
    n = int(np.ceil(info.duration_s / opts.analysis.hop_s))
    sig = Signals(hop_s=opts.analysis.hop_s, t0=0.0, n=n, duration_s=info.duration_s)
    sig.meta = {"fingerprint": _analysis_fingerprint(opts), "has_audio": info.has_audio}

    arrays = analyse_signals(info, caps, opts, cache, report, on_event, track, opts.analysis.resume)
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
    speech_on = (opts.speech.captions or opts.speech.rank) and info.has_audio
    n_select = opts.clips.count * 3 if (speech_on and opts.speech.rank) else opts.clips.count
    top, total, _sm = select_candidates(
        sig, opts.scoring, n_select, opts.clips.min_s, opts.clips.max_s
    )
    report.candidates_total = total
    report.stages.append(Stage("score", "ok", round(time.time() - t0, 3), f"{total} candidates"))
    transcripts: dict = {}
    if speech_on and top:
        transcripts = _speech_stage(info, caps, opts, sig, top, report, on_event, cancel)
        if transcripts:
            top = sorted(top, key=lambda c: c.score, reverse=True)[: opts.clips.count]
    facecam = None
    if opts.layout.facecam == "auto" and top and not opts.render.dry_run:
        facecam = _facecam_stage(info, caps, opts, report, on_event)
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
                source=info.path,
                session_start=c.start,
                session_end=c.end,
                layout="facecam" if facecam else "gameplay",
                facecam=facecam.to_dict() if facecam else None,
                speech=c.features.get("speech", {})
                if isinstance(c.features.get("speech"), dict)
                else {},
            )
        )
    emit(on_event, Event("score", "done", message=f"{len(top)} clips from {total} candidates"))
    if not top:
        report.warnings.append(Warning("score", "no_peaks", "no action peaks found"))
    elif len(top) < opts.clips.count:
        report.warnings.append(
            Warning(
                "score",
                "below_floor",
                f"{len(top)} of {opts.clips.count} requested: only {len(top)} moments cleared "
                f"the action bar {opts.scoring.min_evidence:.2f} (--count is a maximum, no "
                f"filler clips; lower --min-score to get more)",
            )
        )

    out_dir = Path(opts.render.out_dir)
    report.out_dir = str(out_dir)
    if transcripts and opts.speech.captions and not opts.render.dry_run:
        _write_captions(report, transcripts, opts, caps, Path(info.path).stem)
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


def _source_warnings(info: MediaInfo, caps: FFmpegCaps, report: Report) -> None:
    name = Path(info.path).name
    if info.is_hdr:
        if caps.tonemap:
            kind = (
                "assumed PQ: 10-bit bt2020 without a transfer tag"
                if info.hdr_assumed
                else info.color_transfer
            )
            report.warnings.append(
                Warning("probe", "hdr", f"HDR source ({kind}): tone-mapped to SDR [{name}]")
            )
        else:
            report.warnings.append(
                Warning(
                    "probe",
                    "hdr",
                    "HDR source: output may look washed out (ffmpeg >= 8 needed to tone-map) "
                    f"[{name}]",
                )
            )
    if info.duration_measured:
        report.warnings.append(
            Warning(
                "probe",
                "no_index",
                f"container has no duration/index (interrupted recording?): measured "
                f"{info.duration_s:.1f}s with a copy pass [{name}]",
            )
        )
    if info.vcodec == "av1" and not caps.hwaccel:
        report.warnings.append(
            Warning("probe", "av1", f"AV1 source: software decode may be slow [{name}]")
        )
    if not info.has_audio:
        report.warnings.append(
            Warning("probe", "no_audio", f"no audio stream: scoring on video motion only [{name}]")
        )


def _pick_audio_track(info: MediaInfo, caps: FFmpegCaps, opts: Options, report: Report):
    """Resolve opts.analysis.audio_track for this file; roles go into the report."""
    choice = str(opts.analysis.audio_track)
    if not info.has_audio:
        return 0
    if len(info.audio_streams) <= 1 and choice in ("auto", "all", "mix", "game", "0"):
        return 0
    roles = audio_roles(info, caps)
    track, desc = choose_track(choice, roles)
    entry = {
        "path": info.path,
        "choice": choice,
        "used": desc,
        "tracks": [
            {
                "index": r.index,
                "role": r.role,
                "title": r.title,
                "rms_db": round(r.rms_db, 1),
                "active": round(r.active, 3),
                "dynamic_db": round(r.dynamic_db, 1),
                "high_ratio": round(r.high_ratio, 3),
            }
            for r in roles
        ],
    }
    report.input.setdefault("audio_tracks", []).append(entry)
    summary = ", ".join(f"{r.index}={r.role}" + (f" ({r.title})" if r.title else "") for r in roles)
    report.warnings.append(
        Warning(
            "probe",
            "audio_tracks",
            f"{len(roles)} audio tracks ({summary}): analysing {desc} [{Path(info.path).name}]",
        )
    )
    return track


def _offset_events(on_event: OnEvent | None, offset_s: float, total_s: float) -> OnEvent | None:
    """Progress of one file -> progress on the session timeline."""
    if on_event is None:
        return None

    def wrapped(ev: Event) -> None:
        if ev.unit == "s" and ev.kind in ("start", "progress", "done", "cached"):
            done = offset_s + (ev.done if ev.kind != "start" else 0.0)
            on_event(
                Event(
                    ev.stage,
                    "progress" if ev.kind != "start" else ev.kind,
                    done,
                    total_s,
                    "s",
                    ev.message,
                    ev.extra,
                )
            )
        else:
            on_event(ev)

    return wrapped


def _offset_clip_events(on_event: OnEvent | None, done_before: int, total: int) -> OnEvent | None:
    if on_event is None:
        return None

    def wrapped(ev: Event) -> None:
        if ev.stage == "render" and ev.unit == "clips":
            kind = ev.kind if ev.kind != "done" or done_before + ev.done >= total else "progress"
            on_event(
                Event("render", kind, done_before + ev.done, total, "clips", ev.message, ev.extra)
            )
        else:
            on_event(ev)

    return wrapped


def _whole_file_candidates(
    session: Session, sig: Signals, opts: Options, count: int
) -> list[Candidate]:
    """Console clip collections: each short file is one candidate (the player already chose
    it); ranked by its action peak; whole file unless longer than --max. The intro/outro edge
    rule is per recording, not per session: off here."""
    from dataclasses import replace

    score, comps = action_score(sig, replace(opts.scoring, edge_s=0.0))
    sm = smooth(score, sig.hop_s, opts.scoring.smooth_sigma_s)
    cands: list[Candidate] = []
    for src in session.sources:
        i0, i1 = sig.index_of(src.offset_s), sig.index_of(src.offset_s) + src.n
        seg = sm[i0:i1]
        if seg.size == 0:
            continue
        p = int(np.nanargmax(seg)) if np.isfinite(seg).any() else 0
        raw = float(np.nan_to_num(score[i0 + max(0, p - 2) : i0 + p + 3]).max())
        c_score = 0.5 * float(np.nan_to_num(seg[p])) + 0.5 * raw  # as select_candidates
        peak_local = (p + 0.5) * sig.hop_s
        dur = src.info.duration_s
        if dur <= opts.clips.max_s:
            start, end, note = 0.0, dur, "whole file"
        else:
            start, end = make_window(
                peak_local, (peak_local, peak_local), opts.clips.min_s, opts.clips.max_s, dur,
                opts.scoring.lead_frac,
            )  # fmt: skip
            note = "trimmed to the peak"
        components = {
            k.split(".", 1)[-1]: round(float(np.nan_to_num(v[i0 + p])), 4) for k, v in comps.items()
        }
        cands.append(
            Candidate(
                id=src.index,
                peak_t=round(src.offset_s + peak_local, 3),
                score=round(c_score, 4),
                prominence=0.0,
                components=components,
                start=round(src.offset_s + start, 3),
                end=round(src.offset_s + end, 3),
                snap={"mode": note},
                features={
                    k: round(float(np.nan_to_num(v[i0 + p])), 4)
                    for k, v in sig.arrays.items()
                    if v.size == sig.n
                },
            )
        )
    cands.sort(key=lambda c: c.score, reverse=True)
    return cands[:count]


def _run_many(
    paths: list[Path],
    opts: Options,
    on_event: OnEvent | None,
    cancel: threading.Event,
    caps: FFmpegCaps,
    t_start: float,
) -> Report:
    """Several files = one session: per-file analysis (cached per file), one ranking over the
    whole timeline, clips never cross a file boundary, speech/facecam/render per file."""
    emit(on_event, Event("probe", "start"))
    t0 = time.time()
    infos = probe_all(paths, caps)
    hop = opts.analysis.hop_s
    session = build_session(infos, hop)
    parent = os.path.commonpath([i.path for i in infos]) if len(infos) > 1 else infos[0].path
    report = Report(
        input={
            "path": parent,
            "id": "",
            "session": True,
            "files": len(infos),
            "duration_s": round(sum(i.duration_s for i in infos), 3),
            "short_clips": session.short_mode,
            "width": infos[0].width,
            "height": infos[0].height,
            "fps": infos[0].fps,
            "has_audio": any(i.has_audio for i in infos),
            "has_video": True,
            "vcodec": infos[0].vcodec,
            "pix_fmt": infos[0].pix_fmt,
            "container": infos[0].container,
            "audio_streams": len(infos[0].audio_streams),
            "sources": session.to_dicts(),
        },
        options=opts.to_dict(),
    )
    tracks = {i.path: _pick_audio_track(i, caps, opts, report) for i in infos}
    report.stages.append(Stage("probe", "ok", round(time.time() - t0, 3), f"{len(infos)} files"))
    emit(on_event, Event("probe", "done", message=f"{len(infos)} files, {session.total_s:.0f}s"))
    for info in infos:
        _source_warnings(info, caps, report)
    if session.short_mode:
        report.warnings.append(
            Warning(
                "score",
                "short_clips",
                f"all {len(infos)} files are <= 90 s: each file is one candidate, ranked by its "
                "action peak (whole file; trimmed to the peak when longer than --max)",
            )
        )

    caches: dict[int, SignalCache] = {}
    sigs: dict[int, Signals] = {}
    for src in session.sources:
        info = src.info
        cache = SignalCache(info.path, opts.analysis.cache_dir, opts.analysis.cache)
        caches[src.index] = cache
        ev = _offset_events(on_event, src.offset_s, session.total_s)
        arrays = analyse_signals(
            info, caps, opts, cache, report, ev, tracks[info.path], opts.analysis.resume
        )
        fixed: dict[str, np.ndarray] = {}
        for k, v in arrays.items():
            v = np.asarray(v, dtype=np.float32)
            if v.size < src.n:
                v = np.pad(v, (0, src.n - v.size), constant_values=np.nan)
            fixed[k] = v[: src.n]
        session.per_file[src.index] = fixed
        s_i = Signals(hop_s=hop, t0=0.0, n=src.n, duration_s=info.duration_s, arrays=fixed)
        s_i.meta = {"fingerprint": _analysis_fingerprint(opts), "has_audio": info.has_audio}
        sigs[src.index] = s_i
        if cancel.is_set():
            raise StageError("audio", "cancelled")
    names = sorted({k for arrs in session.per_file.values() for k in arrs})
    sig = Signals(hop_s=hop, t0=0.0, n=session.n, duration_s=session.total_s)
    sig.arrays = concat_arrays(session, names, session.per_file)
    sig.meta = {"fingerprint": _analysis_fingerprint(opts), "has_audio": report.input["has_audio"]}
    if not sig.arrays:
        raise StageError("score", "no analysable signals")

    emit(on_event, Event("score", "start"))
    t0 = time.time()
    speech_on = (opts.speech.captions or opts.speech.rank) and report.input["has_audio"]
    n_select = opts.clips.count * 3 if (speech_on and opts.speech.rank) else opts.clips.count
    if session.short_mode:
        top = _whole_file_candidates(session, sig, opts, n_select)
        total = len(session.sources)
    else:
        from dataclasses import replace

        # the intro/outro edge rule assumes one recording; a session's first/last 30 s are
        # ordinary gameplay of the first/last file (per-file edges: scoring's work)
        top, total, _sm = select_candidates(
            sig, replace(opts.scoring, edge_s=0.0), n_select, opts.clips.min_s, opts.clips.max_s
        )
    report.candidates_total = total
    # never cross a file boundary; candidate times become local to their file
    where: dict[int, tuple] = {}
    for c in top:
        src, a, b = clamp_to_source(
            session, c.start, c.end, c.peak_t, opts.clips.min_s, opts.clips.max_s
        )
        where[c.id] = (src, c.start, c.end)
        c.start, c.end = a, b
        c.peak_t = round(c.peak_t - src.offset_s, 3)
    report.stages.append(
        Stage("score", "ok", round(time.time() - t0, 3), f"{total} candidates, {len(infos)} files")
    )

    by_src: dict[int, list] = {}
    for c in top:
        by_src.setdefault(where[c.id][0].index, []).append(c)
    transcripts: dict[int, dict] = {}
    if speech_on and top:
        for idx, cands in by_src.items():
            info = session.sources[idx].info
            if info.has_audio:
                transcripts[idx] = _speech_stage(
                    info, caps, opts, sigs[idx], cands, report, on_event, cancel
                )
        if any(transcripts.values()):
            top = sorted(top, key=lambda c: c.score, reverse=True)[: opts.clips.count]
            by_src = {}
            for c in top:
                by_src.setdefault(where[c.id][0].index, []).append(c)
    facecams: dict[int, object] = {}
    if opts.layout.facecam == "auto" and top and not opts.render.dry_run:
        for idx in by_src:
            facecams[idx] = _facecam_stage(session.sources[idx].info, caps, opts, report, on_event)
    report.signals = {
        "cache_path": "",
        "names": names,
        "hop_s": hop,
        "per_file": {
            str(i): str(c.path("signals.npz")) if c.enabled else "" for i, c in caches.items()
        },
    }
    for rank, c in enumerate(top, start=1):
        src = where[c.id][0]
        fc = facecams.get(src.index)
        crop = plan_crop(sigs[src.index], c.start, c.end, src.info, opts.layout, opts.render)
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
                source=src.info.path,
                source_index=src.index,
                session_start=round(src.offset_s + c.start, 3),
                session_end=round(src.offset_s + c.end, 3),
                layout="facecam" if fc else "gameplay",
                facecam=fc.to_dict() if fc else None,
                speech=c.features.get("speech", {})
                if isinstance(c.features.get("speech"), dict)
                else {},
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
        done_before = 0
        for idx in by_src:
            src = session.sources[idx]
            sub = Report(
                input=report.input,
                options=report.options,
                stages=report.stages,
                warnings=report.warnings,
                clips=[c for c in report.clips if c.source_index == idx],
            )
            if transcripts.get(idx) and opts.speech.captions:
                _write_captions(sub, transcripts[idx], opts, caps, Path(src.info.path).stem)
            render_all(
                src.info,
                caps,
                opts,
                sub,
                _offset_clip_events(on_event, done_before, len(report.clips)),
                cancel,
            )
            done_before += len(sub.clips)
        report.timings["render_s"] = round(time.time() - t0, 3)

    report.timings["total_s"] = round(time.time() - t_start, 3)
    probe_s = sum(s.wall_s for s in report.stages if s.name == "probe")
    analyze = probe_s + sum(s.wall_s for s in report.stages if s.name in ("audio", "video"))
    report.timings["analyze_s"] = round(analyze, 3)
    report.timings["media_x_realtime"] = round(session.total_s / analyze, 1) if analyze > 0 else 0.0
    out_dir.mkdir(parents=True, exist_ok=True)
    report.write(out_dir / "report.json")
    return report
