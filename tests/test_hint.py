"""10-04: the Smarter-picks hint. The detector says when it is weak (fallback, continuous
profile, almost no onsets) and the report carries one reason code; never when the AI ran."""

from __future__ import annotations

from clip_anything.config import Options, ScoringOptions
from clip_anything.pipeline import HINT_TEXT, run, scoring_hint

OPTS = ScoringOptions()


def _sel(profile="standard", fallback=False, onset_p95=0.4, cleared=3):
    return {
        "profile": profile,
        "fallback": fallback,
        "cleared_bar": cleared,
        "continuity": {"onset_p95": onset_p95},
    }


ASKED = 10


def test_fallback_hint():
    h = scoring_hint(_sel(fallback=True), OPTS, ASKED)
    assert h == {"reason": "below_bar_fallback", "text": HINT_TEXT}
    # the fallback is the most specific reason, it wins over the profile
    assert (
        scoring_hint(_sel("continuous", fallback=True), OPTS, ASKED)["reason"]
        == "below_bar_fallback"
    )


def test_continuous_profile_hint():
    assert scoring_hint(_sel("continuous"), OPTS, ASKED)["reason"] == "continuous_profile"


def test_few_onsets_hint():
    assert scoring_hint(_sel(onset_p95=0.05), OPTS, ASKED)["reason"] == "few_onsets"
    assert scoring_hint(_sel(onset_p95=OPTS.hint_onset_p95), OPTS, ASKED) is None  # at the cut-off
    assert scoring_hint(_sel(onset_p95=None), OPTS, ASKED) is None  # no audio: nothing to judge
    # quiet file whose few bursts fill the list: the detector was not short, no hint
    assert scoring_hint(_sel(onset_p95=0.05, cleared=ASKED), OPTS, ASKED) is None


def test_no_hint_for_an_ordinary_recording_or_when_the_ai_ran():
    assert scoring_hint(_sel(), OPTS, ASKED) is None
    assert scoring_hint(_sel(fallback=True), OPTS, ASKED, ai_on=True) is None
    assert scoring_hint({}, OPTS, 0) is None


def _opts(tmp_path, count):
    return Options.from_layers(
        {
            "clips": {"count": count},
            "render": {"out_dir": str(tmp_path), "dry_run": True},
            "speech": {"captions": False},
            "analysis": {"cache": False},
        }
    )


def test_report_carries_the_hint_end_to_end(synth_continuous_video, synth_video, tmp_path):
    report = run(synth_continuous_video, _opts(tmp_path / "a", 5))
    assert report.scoring["hint"]["reason"] == "continuous_profile"
    # the same file with the AI pass on: no hint (the user already has it)
    report = run(synth_continuous_video, _opts(tmp_path / "b", 5), rerank=lambda c, *_: c)
    assert report.scoring["hint"] is None
    # the plain bursty fixture is ordinary: scored standard, onsets present, nothing to suggest
    report = run(synth_video, _opts(tmp_path / "c", 6))
    assert report.scoring["profile"] == "standard" and report.scoring["hint"] is None


def test_fallback_run_hints(synth_lobby_video, tmp_path):
    report = run(synth_lobby_video, _opts(tmp_path, 5))
    hint = report.scoring["hint"]
    if report.scoring["fallback"]:
        assert hint["reason"] == "below_bar_fallback"
    else:
        assert hint is None or hint["reason"] == "few_onsets"
