import numpy as np

from clip_anything.video_signals import VideoExtractor, extract_video, finalize

W, H, FPS = 64, 36, 5.0


def _frames(seconds=20.0, seed=0):
    """Dark noise; moving bright block 6-8 s; hard cut at 12 s; 1-frame flash at 16 s."""
    rng = np.random.default_rng(seed)
    n = int(seconds * FPS)
    base = rng.integers(20, 40, size=(H, W), dtype=np.uint8)
    frames = np.repeat(base[None], n, axis=0).copy()
    frames[int(12 * FPS) :] = 200 - frames[int(12 * FPS) :]  # scene change (persists)
    for k in range(int(6 * FPS), int(8 * FPS)):
        x = 8 + (k - int(6 * FPS)) * 4
        frames[k, 10:26, x : x + 10] = 250
    frames[int(16 * FPS)] = 255  # single-frame flash
    return frames


def _run(frames, chunk):
    ex = VideoExtractor(FPS, 0.5, W, H)
    for i in range(0, len(frames), chunk):
        ex.feed(frames[i : i + chunk])
    ex.finish()
    out = ex.result(len(frames) / FPS)
    finalize(out)
    return out


def test_chunk_size_invariance():
    frames = _frames()
    a, b, c = _run(frames, 1), _run(frames, 7), _run(frames, len(frames))
    for k in a:
        np.testing.assert_allclose(a[k], b[k], rtol=1e-5, atol=1e-6, equal_nan=True)
        np.testing.assert_allclose(a[k], c[k], rtol=1e-5, atol=1e-6, equal_nan=True)
    assert a["video.motion"].shape[0] == 40


def test_motion_cut_flash_and_centroid():
    out = extract_video([_frames().tobytes()], FPS, 0.5, W, H, 20.0)
    motion = out["video.motion"]
    assert motion[12:16].min() > 3 * motion[0:12].max()  # block moving during 6-8 s
    cut = out["video.cut"]
    assert cut[24] > 0 and (cut > 0).sum() == 1  # exactly one cut, at 12 s
    flash = out["video.flash"]
    assert flash[32] > 0 and flash[24] == 0  # flash at 16 s only; the cut is not a flash
    cx = out["video.cx"]
    assert np.isnan(cx[0:10]).all()  # no reliable centroid when still
    moving = cx[12:16]
    assert np.isfinite(moving).all() and np.all(np.diff(moving) > 0)  # tracks left -> right
    assert out["video.cspread"][12:16].max() < 0.15  # compact object, not diffuse


def test_empty_input():
    out = extract_video([], FPS, 0.5, W, H, 0.0)
    assert out["video.motion"].size == 0 and out["video.cut"].size == 0
