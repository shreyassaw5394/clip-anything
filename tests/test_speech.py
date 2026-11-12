import numpy as np
import pytest

from clip_anything.config import Options
from clip_anything.pipeline import run
from clip_anything.probe import preflight, probe
from clip_anything.speech import (
    Transcript,
    Word,
    clip_audio,
    energy_gate,
    excitement_bonus,
    model_status,
)


def test_energy_gate():
    sr = 16000
    assert not energy_gate(np.zeros(sr, np.float32), sr)
    assert energy_gate((0.1 * np.sin(np.arange(sr) * 0.1)).astype(np.float32), sr)


def test_excitement_bonus_words_and_shouts():
    opts = Options().speech
    tr = Transcript(words=[Word(1.0, 1.3, "No"), Word(1.3, 1.6, "way,"), Word(2.0, 2.4, "bro")])
    tr.speech = True
    bonus, d = excitement_bonus(tr, opts)
    assert d == {"phrases": 2, "shouts": 0} and bonus == 0.5
    rms = np.full(10, -30.0)
    rms[2] = -15.0  # 1.0-1.5 s window: 15 dB above median
    bonus, d = excitement_bonus(tr, opts, rms, 0.5)
    assert d["shouts"] == 1 and bonus == 0.65  # "No" (mid 1.15 s) sits in that hop
    assert excitement_bonus(Transcript(), opts) == (0.0, {"phrases": 0, "shouts": 0})


def test_model_status_without_dep(monkeypatch):
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda n, *a: None if n == "faster_whisper" else real(n, *a)
    )
    assert model_status("base.en") == "missing_dep"


def test_clip_audio_seeks_a_window(synth_video):
    caps = preflight()
    pcm = clip_audio(synth_video, caps, 10.0, 4.0)
    assert abs(pcm.size - 4 * 16000) < 1600 and pcm.dtype == np.float32


@pytest.mark.skipif(model_status("base.en") != "ready", reason="whisper base.en not cached")
def test_whisper_captions_end_to_end(speech_video, tmp_path):
    caps = preflight()
    opts = Options.from_layers(
        {
            "clips": {"count": 1, "min_s": 15.0, "max_s": 20.0},
            "render": {"out_dir": str(tmp_path / "clips")},
            "layout": {"facecam": "off"},
            "analysis": {"cache": False},
        }
    )
    report = run(speech_video, opts, caps=caps)
    assert report.clips, report.warnings
    c = report.clips[0]
    assert c.status == "ok", c.error
    assert c.transcript and "way" in c.transcript.lower()
    assert c.speech["words"] >= 5 and c.speech["phrases"] >= 2 and c.components["speech"] > 0
    assert c.captions_path and c.captions_path.endswith(".ass")
    assert c.captions is caps.captions
    sp = [s for s in report.stages if s.name == "speech"]
    assert sp and sp[0].status == "ok"


@pytest.mark.skipif(model_status("base.en") != "ready", reason="whisper base.en not cached")
def test_no_captions_on_silent_clip(synth_video, tmp_path):
    caps = preflight()
    info = probe(synth_video, caps)
    assert info.has_audio
    opts = Options.from_layers(
        {
            "clips": {"count": 1},
            "render": {"out_dir": str(tmp_path / "clips"), "dry_run": True},
            "layout": {"facecam": "off"},
            "analysis": {"cache": False},
        }
    )
    report = run(synth_video, opts, caps=caps)
    c = report.clips[0]
    assert c.captions is False and c.captions_path is None and c.components["speech"] == 0.0
