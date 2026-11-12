from clip_anything.config import Options
from clip_anything.errors import InputError
from clip_anything.probe import preflight, probe


def test_preflight_and_probe(synth_video):
    caps = preflight()
    assert caps.version >= (5, 0)
    info = probe(synth_video, caps)
    assert abs(info.duration_s - 180.0) < 0.5
    assert (info.width, info.height) == (1280, 720)
    assert info.has_audio and info.has_video
    assert abs(info.fps - 30.0) < 0.01


def test_probe_missing_file(tmp_path):
    caps = preflight()
    import pytest

    with pytest.raises(InputError):
        probe(tmp_path / "nope.mp4", caps)


def test_options_layering():
    o = Options.from_layers({"clips": {"count": 3}}, {"clips": {"count": None, "min_s": 20}})
    assert o.clips.count == 3 and o.clips.min_s == 20
    assert o.render.crf == 20
    import pytest

    with pytest.raises(InputError):
        Options.from_layers({"clipz": {}})
