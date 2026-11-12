import subprocess
import threading

from clip_anything.config import Options
from clip_anything.pipeline import run
from clip_anything.probe import preflight, probe
from clip_anything.render import clip_filename, render_all
from clip_anything.report import Clip, Report


def _probe(path):
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v",
            "-show_entries",
            "stream=width,height,pix_fmt,color_transfer:format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    w, h, pix, trc = out[0].split(",")
    return int(w), int(h), pix, trc, float(out[1])


def _opts(tmp_path, count=2, **extra):
    layer = {
        "clips": {"count": count},
        "render": {"out_dir": str(tmp_path / "clips")},
        "analysis": {"cache": False},
    }
    layer.update(extra)
    return Options.from_layers(layer)


def test_render_two_clips(synth_video, tmp_path):
    report = run(synth_video, _opts(tmp_path))
    assert [c.status for c in report.clips] == ["ok", "ok"]
    for c in report.clips:
        w, h, pix, trc, dur = _probe(c.path)
        assert (w, h, pix, trc) == (1080, 1920, "yuv420p", "bt709")
        assert abs(dur - c.duration_s) <= 0.1
        assert c.path.endswith(clip_filename("synth", c.rank, c.start))
    assert (tmp_path / "clips" / "report.json").is_file()
    # second run without --force skips existing files
    report2 = run(synth_video, _opts(tmp_path))
    assert [c.status for c in report2.clips] == ["skipped", "skipped"]


def test_failed_clip_does_not_kill_run(synth_video, tmp_path):
    caps = preflight()
    info = probe(synth_video, caps)
    opts = _opts(tmp_path)
    good = Clip(rank=1, candidate_id=0, start=40.0, end=55.0, duration_s=15.0, score=0.9)
    bad = Clip(rank=2, candidate_id=1, start=500.0, end=515.0, duration_s=15.0, score=0.8)
    report = Report(input={}, options=opts.to_dict(), clips=[good, bad])
    render_all(info, caps, opts, report, None, threading.Event())
    assert good.status == "ok" and bad.status == "failed" and bad.path is None
    assert any(w.code == "clip_failed" for w in report.warnings)
    assert not list((tmp_path / "clips").glob("*.part*"))


def test_vfr_source(synth_vfr_video, synth_truth, tmp_path):
    report = run(
        synth_vfr_video,
        _opts(tmp_path, count=6, render={"dry_run": True, "out_dir": str(tmp_path)}),
    )
    for b in synth_truth["audio_bursts"]:
        hits = [c for c in report.clips if c.start <= b["t"] <= c.end]
        assert hits, f"VFR: burst at {b['t']}s not inside any clip"
    report = run(synth_vfr_video, _opts(tmp_path, count=1))
    c = report.clips[0]
    assert c.status == "ok"
    _, _, _, _, dur = _probe(c.path)
    assert abs(dur - c.duration_s) <= 0.15


def _white_centre_frac(path, t):
    """x-centre (fraction of width) of the bright pixels in the frame at t seconds."""
    import numpy as np

    raw = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{t:.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            "scale=108:192,format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    g = np.frombuffer(raw, np.uint8).reshape(192, 108)
    cols = (g > 200).sum(axis=0).astype(float)
    assert cols.sum() > 0, "no white square visible in the rendered frame"
    return float((cols * (np.arange(108) + 0.5)).sum() / cols.sum() / 108)


def test_follow_crop_tracks_moving_square(synth_square_video, synth_square_truth, tmp_path):
    report = run(synth_square_video, _opts(tmp_path, count=1))
    assert len(report.clips) == 1
    c = report.clips[0]
    assert c.status == "ok" and c.crop["mode"] == "follow", c.crop
    keys = c.crop["keyframes"]
    assert len(keys) >= 20
    # keyframes: crop centre within 8 % of the true square centre once the smoother settled
    x0, x1 = synth_square_truth["square_x0"], synth_square_truth["square_x1"]
    d = synth_square_truth["duration_s"]
    w, cw = 1280, 720 * 9 / 16
    travel = w - cw
    errs = []
    for t_rel, left in keys[6:]:
        truth = x0 + (x1 - x0) * (c.start + t_rel) / d
        centre = (left * travel + cw / 2) / w
        errs.append(abs(centre - truth))
    assert max(errs) < 0.08, max(errs)
    # no pan faster than the cap
    import numpy as np

    k = np.array(keys)
    speed = np.abs(np.diff(k[:, 1])) * travel / w / np.diff(k[:, 0])
    assert speed.max() <= 0.25 + 1e-6
    # rendered output: the square stays near the middle of the vertical frame
    for t in (2.0, c.duration_s / 2, c.duration_s - 2.0):
        frac = _white_centre_frac(c.path, t)
        assert abs(frac - 0.5) < 0.2, (t, frac)
