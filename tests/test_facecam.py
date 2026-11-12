import numpy as np

from clip_anything.facecam import detect_facecam, sample_frames, static_regions
from clip_anything.probe import preflight, probe


def _frames(path, n=5):
    caps = preflight()
    info = probe(path, caps)
    return info, caps, sample_frames(info, caps, n)


def test_static_region_in_corner(facecam_video):
    _info, _caps, frames = _frames(facecam_video)
    assert len(frames) == 5 and frames[0].shape == (360, 640)
    regions = static_regions(frames)
    assert regions, "static webcam box not found"
    r = max(regions, key=lambda r: r["w"] * r["h"])
    assert r["corner"] == "top-left"
    # box drawn at (20,20) 320x240 on 1280x720 -> (10,10) 160x120 at 640 wide
    assert abs(r["x"] - 10) <= 8 and abs(r["y"] - 10) <= 8
    assert abs(r["w"] - 160) <= 16 and abs(r["h"] - 120) <= 16


def test_detect_facecam_with_face(facecam_video):
    info, caps, _ = _frames(facecam_video)
    fc = detect_facecam(info, caps)
    assert fc is not None, "facecam not detected"
    assert fc.corner == "top-left" and fc.face_hits >= 2 and fc.confidence >= 0.4
    assert abs(fc.x - 20 / 1280) < 0.02 and abs(fc.w - 320 / 1280) < 0.03


def test_no_facecam_on_plain_gameplay(synth_video):
    info, caps, _ = _frames(synth_video)
    assert detect_facecam(info, caps) is None


def test_static_regions_need_motion_elsewhere():
    # a fully static frame set has no distinguished corner: nothing bigger than the cap
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 255, (180, 320), dtype=np.uint8)
    assert static_regions([frame.copy() for _ in range(5)]) == []
