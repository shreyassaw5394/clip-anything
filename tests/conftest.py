import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from make_test_video import ensure  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


@pytest.fixture(scope="session")
def synth_video() -> Path:
    return ensure(FIXTURES, "base")


@pytest.fixture(scope="session")
def synth_music_video() -> Path:
    return ensure(FIXTURES, "music")


@pytest.fixture(scope="session")
def synth_vfr_video() -> Path:
    return ensure(FIXTURES, "vfr")


@pytest.fixture(scope="session")
def synth_truth(synth_video) -> dict:
    import json

    return json.loads((FIXTURES / "synth.json").read_text())


@pytest.fixture(scope="session")
def synth_quiet_video() -> Path:
    return ensure(FIXTURES, "quiet")


@pytest.fixture(scope="session")
def synth_square_video() -> Path:
    return ensure(FIXTURES, "square")


@pytest.fixture(scope="session")
def synth_square_truth(synth_square_video) -> dict:
    import json

    return json.loads((FIXTURES / "synth_square.json").read_text())


@pytest.fixture(scope="session")
def synth_lobby_video() -> Path:
    return ensure(FIXTURES, "lobby")


@pytest.fixture(scope="session")
def synth_agree_video() -> Path:
    return ensure(FIXTURES, "agree")


@pytest.fixture(scope="session")
def facecam_video(tmp_path_factory) -> Path:
    from synth_extra import build_facecam_video

    return build_facecam_video(tmp_path_factory.mktemp("facecam"))


@pytest.fixture(scope="session")
def speech_video(tmp_path_factory) -> Path:
    from synth_extra import build_speech_video

    p = build_speech_video(tmp_path_factory.mktemp("speech"))
    if p is None:
        pytest.skip("macOS `say` not available for the speech stand-in")
    return p
