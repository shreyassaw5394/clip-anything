import numpy as np

from clip_anything.audio_signals import AudioExtractor, extract_audio

SR = 16000


def _pcm(seconds=20.0, bursts=((5.0, 0.5), (12.0, 0.8)), base_amp=0.03, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(int(SR * seconds)) / SR
    x = base_amp * np.sin(2 * np.pi * 220 * t) + 0.005 * (rng.random(t.size) - 0.5)
    for s, d in bursts:
        i0, i1 = int(s * SR), int((s + d) * SR)
        x[i0:i1] += 0.9 * (rng.random(i1 - i0) - 0.5)
    return (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()


def _run(pcm, chunk):
    ex = AudioExtractor(SR, 0.5, 1.0)
    for i in range(0, len(pcm), chunk):
        ex.feed(pcm[i : i + chunk])
    ex.finish()
    return ex.result(20.0)


def test_chunk_size_invariance():
    pcm = _pcm()
    a = _run(pcm, 2)  # one sample at a time (2 bytes)
    b = _run(pcm, 777 * 2)
    c = _run(pcm, len(pcm))
    for k in a:
        np.testing.assert_allclose(a[k], b[k], rtol=1e-5, atol=1e-6)
        np.testing.assert_allclose(a[k], c[k], rtol=1e-5, atol=1e-6)
    assert a["audio.rms_db"].shape[0] == 40


def test_bursts_are_loud_and_sharp():
    pcm = _pcm()
    arrays = extract_audio([pcm], SR, 0.5, 1.0, 60.0, 20.0)
    loud = arrays["audio.loud_rel"]
    onset = arrays["audio.onset"]
    # peak window index for burst at 5 s ~ index 10, at 12 s ~ index 24
    assert loud[9:12].max() > 15 and loud[23:26].max() > 15
    quiet = np.r_[loud[0:8], loud[14:22], loud[28:40]]
    assert quiet.max() < 3
    assert onset.argmax() in (10, 24)
    assert onset[10] > 5 * onset[0:9].max()
