import subprocess
import threading
from dataclasses import replace
from pathlib import Path

import numpy as np

from clip_anything.captions import build_ass, group_lines, write_ass
from clip_anything.config import Options
from clip_anything.probe import preflight, probe
from clip_anything.render import build_graph, render_clip
from clip_anything.report import Clip
from clip_anything.speech import Word

WORDS = [
    Word(0.5, 0.8, "No"), Word(0.8, 1.2, "way."), Word(1.6, 1.9, "Let's"), Word(1.9, 2.3, "go!"),
    Word(2.6, 2.8, "Oh"), Word(2.8, 3.0, "my"), Word(3.0, 3.4, "god,"), Word(3.4, 3.6, "that"),
    Word(3.6, 3.8, "was"), Word(3.8, 4.4, "insane,"), Word(4.5, 4.9, "bro."),
]  # fmt: skip


def test_group_lines_two_to_four_words():
    lines = group_lines(WORDS, 4)
    sizes = [len(ln.words) for ln in lines]
    assert all(2 <= n <= 5 for n in sizes), sizes
    assert sum(sizes) == len(WORDS)
    assert [w.text for w in lines[0].words] == ["No", "way."]
    # long pause splits
    gap = [Word(0, 0.3, "a"), Word(0.3, 0.6, "b"), Word(2.0, 2.3, "c"), Word(2.3, 2.6, "d")]
    assert [len(ln.words) for ln in group_lines(gap, 4)] == [2, 2]


def test_build_ass_structure():
    opts = Options().speech
    text = build_ass(WORDS, opts, 1080, 1920, duration=20.0)
    assert "PlayResX: 1080" in text and "PlayResY: 1920" in text
    assert "Style: Cap,Arial,80,&H00FFFFFF" in text and ",2,60,60,600,1" in text  # align 2, MarginV
    events = [ln for ln in text.splitlines() if ln.startswith("Dialogue:")]
    assert len(events) == len(WORDS)  # one event per spoken word
    assert all(opts.highlight in e for e in events)
    assert events[0].startswith("Dialogue: 0,0:00:00.50,0:00:00.80,Cap")
    assert "{\\c&H0000FFFF&}No{\\c&HFFFFFF&} way." in events[0]
    # times never exceed the clip
    assert all(float(e.split(",")[2].split(":")[-1]) <= 20.0 for e in events)
    assert build_ass([], opts).endswith("Text\n")


def _frame_gray(path, t, ffmpeg="ffmpeg"):
    raw = subprocess.run(
        [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i",
         str(path), "-frames:v", "1", "-vf", "scale=540:960,format=gray", "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    return np.frombuffer(raw, np.uint8).reshape(960, 540)


BAND = slice(595, 692)  # 62-72 % of the height: where captions sit


def _clip(tmp_path, **kw):
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    ass = write_ass(out_dir / "c.ass", build_ass(WORDS, Options().speech, duration=15.0))
    c = Clip(rank=1, candidate_id=0, start=1.0, end=16.0, duration_s=15.0, score=0.9,
             captions=True, captions_path=str(ass), **kw)  # fmt: skip
    return c, out_dir


def test_graph_has_ass_after_final_size(synth_video, tmp_path):
    caps = preflight()
    info = probe(synth_video, caps)
    c, _ = _clip(tmp_path)
    g = build_graph(c, info, Options(), True, caps, captions=True)
    assert "pad=1080:1920" in g and ",ass=captions.ass,setparams" in g
    g2 = build_graph(c, info, Options(), True, caps, captions=False)
    assert "ass=" not in g2


def test_captions_burned_when_libass_present(synth_video, tmp_path):
    caps = preflight()
    if not caps.captions:
        import pytest

        pytest.skip("ffmpeg without libass (brew install ffmpeg-full)")
    info = probe(synth_video, caps)
    c, out_dir = _clip(tmp_path)
    opts = Options.from_layers({"render": {"out_dir": str(out_dir)}})
    render_clip(caps, info, c, opts, out_dir / "cap.mp4", 4, threading.Event())
    assert c.status == "ok" and c.captions is True and c.error is None
    # the caption band (62-72 % of height) is brighter while a word is on screen than after
    on = _frame_gray(c.path, 1.0, caps.ffmpeg)[BAND]
    off = _frame_gray(c.path, 9.0, caps.ffmpeg)[BAND]
    assert (on > 250).sum() > 150 and (off > 250).sum() < 20


def test_captions_sidecar_when_libass_missing(synth_video, tmp_path):
    caps = replace(preflight(), captions=False)
    info = probe(synth_video, caps)
    c, out_dir = _clip(tmp_path)
    opts = Options.from_layers({"render": {"out_dir": str(out_dir)}})
    render_clip(caps, info, c, opts, out_dir / "cap.mp4", 4, threading.Event())
    assert c.status == "ok" and c.captions is False and c.error is None
    assert Path(c.captions_path).is_file()
    # frame has no caption text in the band
    band = _frame_gray(c.path, 1.0, caps.ffmpeg)[BAND]
    assert (band > 250).sum() < 20


def test_facecam_layout_render(facecam_video, tmp_path):
    from clip_anything.facecam import detect_facecam, face_boxes

    caps = preflight()
    info = probe(facecam_video, caps)
    fc = detect_facecam(info, caps)
    assert fc is not None
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    c = Clip(rank=1, candidate_id=0, start=2.0, end=17.0, duration_s=15.0, score=0.9,
             layout="facecam", facecam=fc.to_dict())  # fmt: skip
    opts = Options.from_layers({"render": {"out_dir": str(out_dir)}})
    render_clip(caps, info, c, opts, out_dir / "fc.mp4", 4, threading.Event())
    assert c.status == "ok" and c.layout == "facecam", c.error
    frame = _frame_gray(c.path, 5.0, caps.ffmpeg)
    assert frame.shape == (960, 540)
    # the facecam band (top 30 %) holds the face; the gameplay below does not
    top, bottom = np.ascontiguousarray(frame[:288]), np.ascontiguousarray(frame[288:])
    assert face_boxes(top, 40), "no face in the top band"
    assert not face_boxes(bottom, 40)


def test_facecam_fallback_to_gameplay(synth_video, tmp_path, monkeypatch):
    import dataclasses

    import clip_anything.render as render_mod

    # the ladder's first rung needs a captions-capable ffmpeg; force the capability so the test
    # is the same on a machine without libass (stock Homebrew, GitHub's macOS runners): the
    # mocked encode fails that rung anyway
    caps = dataclasses.replace(preflight(), captions=True)
    info = probe(synth_video, caps)
    fc = {"x": 0.02, "y": 0.02, "w": 0.25, "h": 0.33, "corner": "top-left", "confidence": 1.0}
    c, out_dir = _clip(tmp_path, layout="facecam", facecam=fc)
    real = render_mod._encode
    attempts = []

    def flaky(caps, info, clip, opts, part, threads, cancel, captions, facecam):
        attempts.append((captions, facecam))
        if captions or facecam:
            return 1, b"simulated filter failure"
        return real(caps, info, clip, opts, part, threads, cancel, captions, facecam)

    monkeypatch.setattr(render_mod, "_encode", flaky)
    opts = Options.from_layers({"render": {"out_dir": str(out_dir)}})
    render_clip(caps, info, c, opts, out_dir / "fb.mp4", 4, threading.Event())
    assert attempts == [(True, True), (False, True), (False, False)]
    assert c.status == "ok" and c.layout == "gameplay" and c.captions is False
    assert "degraded" in (c.error or "")
