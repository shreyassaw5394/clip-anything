"""Render clips: one ffmpeg process per clip, one filter graph, one encode."""

from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import Options
from .events import Event, OnEvent, emit
from .probe import FFmpegCaps, MediaInfo, _popen_kwargs
from .report import Clip, Report, Warning


def clip_filename(stem: str, rank: int, start: float) -> str:
    m, s = divmod(int(start), 60)
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in stem)[:60]
    return f"{safe}_{rank:02d}_{m:02d}-{s:02d}.mp4"


def build_graph(clip: Clip, info: MediaInfo, opts: Options, has_audio: bool) -> str:
    """Centre 9:16 crop (phase 2 swaps in the follow-crop keyframes), scale, fades."""
    r = opts.render
    dur = clip.end - clip.start
    fade = min(r.fade_s, dur / 4)
    out_st = max(0.0, dur - fade)
    v = (
        "[0:v]crop=w='min(iw,ih*9/16)':h=ih:x='(iw-ow)/2':y=0,"
        f"scale={r.width}:{r.height}:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad={r.width}:{r.height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p,"
        "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709,"
        f"fade=t=in:st=0:d={fade:.3f},fade=t=out:st={out_st:.3f}:d={fade:.3f}[v]"
    )
    if not has_audio:
        return v
    a = f"[0:a]afade=t=in:st=0:d={fade:.3f},afade=t=out:st={out_st:.3f}:d={fade:.3f}[a]"
    return v + ";\n" + a


def ffmpeg_args(
    caps: FFmpegCaps,
    info: MediaInfo,
    clip: Clip,
    opts: Options,
    graph_file: str,
    out_part: str,
    threads: int,
) -> list[str]:
    r = opts.render
    dur = clip.end - clip.start
    args = [
        caps.ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{clip.start:.3f}",
        "-t",
        f"{dur:.3f}",
        "-i",
        os.fspath(info.path),
    ]
    if caps.filter_file_flag == "-/filter_complex":
        args += ["-/filter_complex", graph_file]
    else:
        args += ["-filter_complex_script", graph_file]
    args += ["-map", "[v]"]
    if info.has_audio:
        args += ["-map", "[a]", "-c:a", "aac", "-b:a", r.audio_bitrate]
    else:
        args += ["-an"]
    args += [
        "-c:v",
        "libx264",
        "-preset",
        r.preset,
        "-crf",
        str(r.crf),
        "-pix_fmt",
        "yuv420p",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-colorspace",
        "bt709",
        "-threads",
        str(threads),
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        out_part,
    ]
    return args


def _probe_duration(caps: FFmpegCaps, path: str) -> float:
    res = subprocess.run(
        [
            caps.ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            path,
        ],
        capture_output=True,
        text=True,
        check=False,
        **_popen_kwargs(),
    )
    try:
        return float(res.stdout.strip())
    except ValueError:
        return 0.0


def render_clip(
    caps: FFmpegCaps,
    info: MediaInfo,
    clip: Clip,
    opts: Options,
    out_path: Path,
    threads: int,
    cancel: threading.Event,
) -> Clip:
    t0 = time.time()
    if out_path.exists() and not opts.render.force:
        clip.status, clip.error, clip.path = "skipped", "exists (use --force)", str(out_path)
        return clip
    if cancel.is_set():
        clip.status, clip.error = "skipped", "cancelled"
        return clip
    graph = build_graph(clip, info, opts, info.has_audio)
    part = out_path.with_suffix(".part.mp4")
    with tempfile.TemporaryDirectory(prefix="clipany-") as tmp:
        graph_file = "graph.txt"
        Path(tmp, graph_file).write_text(graph, encoding="utf-8")
        args = ffmpeg_args(caps, info, clip, opts, graph_file, os.fspath(part), threads)
        proc = subprocess.Popen(
            args, cwd=tmp, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **_popen_kwargs()
        )
        err_bytes = b""
        try:
            while True:
                try:
                    _, err_bytes = proc.communicate(timeout=0.5)
                    break
                except subprocess.TimeoutExpired:
                    if cancel.is_set():
                        proc.terminate()
                        _, err_bytes = proc.communicate()
                        break
        finally:
            if proc.poll() is None:
                proc.kill()
    clip.render_s = round(time.time() - t0, 3)
    if cancel.is_set():
        part.unlink(missing_ok=True)
        clip.status, clip.error = "skipped", "cancelled"
        return clip
    if proc.returncode != 0 or not part.exists() or _probe_duration(caps, str(part)) < 0.5:
        part.unlink(missing_ok=True)
        clip.status = "failed"
        clip.error = (err_bytes.decode(errors="replace").strip().splitlines() or ["ffmpeg failed"])[
            -1
        ][:200]
        return clip
    os.replace(part, out_path)
    clip.status, clip.path, clip.error = "ok", str(out_path), None
    return clip


def render_all(
    info: MediaInfo,
    caps: FFmpegCaps,
    opts: Options,
    report: Report,
    on_event: OnEvent | None,
    cancel: threading.Event,
) -> None:
    out_dir = Path(opts.render.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    cpu = os.cpu_count() or 4
    workers = opts.render.workers or max(1, cpu // 4)
    workers = max(1, min(workers, len(report.clips)))
    threads = max(1, cpu // workers)
    stem = Path(info.path).stem
    total = len(report.clips)
    emit(on_event, Event("render", "start", 0, total, "clips"))
    done = 0
    lock = threading.Lock()

    def job(clip: Clip) -> Clip:
        nonlocal done
        out_path = out_dir / clip_filename(stem, clip.rank, clip.start)
        result = render_clip(caps, info, clip, opts, out_path, threads, cancel)
        with lock:
            done += 1
            emit(on_event, Event("render", "progress", done, total, "clips"))
        return result

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(job, report.clips))
    for c in report.clips:
        if c.status == "failed":
            report.warnings.append(Warning("render", "clip_failed", f"clip {c.rank}: {c.error}"))
    ok = len(report.ok_clips)
    emit(on_event, Event("render", "done", total, total, "clips", message=f"{ok}/{total} ok"))
    report.stages.append(
        Stage_render(ok, total, sum(c.render_s or 0 for c in report.clips), workers)
    )


def Stage_render(ok: int, total: int, cpu_s: float, workers: int):
    from .report import Stage

    return Stage("render", "ok" if ok else "failed", round(cpu_s, 3), f"{ok}/{total} w={workers}")
