import os

import numpy as np

from clip_anything.cache import SignalCache


def _video(tmp_path):
    v = tmp_path / "v.mp4"
    v.write_bytes(os.urandom(4096))
    return v


def test_cache_round_trip(tmp_path):
    v = _video(tmp_path)
    c = SignalCache(v, None, enabled=True)
    assert c.put_npz("signals.npz", "fp", {"a": np.arange(3)}) is not None
    got = SignalCache(v, None, enabled=True).get_npz("signals.npz", "fp")
    assert got is not None and got["a"].tolist() == [0, 1, 2]
    assert SignalCache(v, None, enabled=True).get_npz("signals.npz", "other") is None


def test_cache_refuses_symlinked_root(tmp_path):
    v = _video(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / ".clipanything").symlink_to(elsewhere, target_is_directory=True)
    c = SignalCache(v, None, enabled=True)
    assert c.enabled is False
    assert c.put_npz("signals.npz", "fp", {"a": np.arange(3)}) is None
    assert list(elsewhere.iterdir()) == []
