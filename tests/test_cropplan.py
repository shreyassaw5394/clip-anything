import numpy as np

from clip_anything.audio_signals import Signals
from clip_anything.config import LayoutOptions, RenderOptions
from clip_anything.cropplan import deadband_speed_cap, fill_nan, plan_crop, x_expression
from clip_anything.probe import MediaInfo

HOP = 0.5


def _info(w=1920, h=1080):
    return MediaInfo(
        path="x", duration_s=100.0, width=w, height=h, fps=30, has_audio=True,
        has_video=True, rotation=0, size_bytes=1,
    )  # fmt: skip


def _sig(cx, spread=0.05):
    n = cx.size
    arrays = {
        "video.cx": cx.astype(np.float32),
        "video.cspread": np.full(n, spread, np.float32),
    }
    return Signals(HOP, 0.0, n, n * HOP, arrays)


def test_fill_nan():
    x = np.array([np.nan, np.nan, 0.3, np.nan, 0.5, np.nan])
    np.testing.assert_allclose(fill_nan(x), [0.3, 0.3, 0.3, 0.3, 0.5, 0.5])
    assert np.isnan(fill_nan(np.array([np.nan, np.nan]))).all()


def test_speed_cap_and_deadband():
    f = np.r_[np.zeros(4), np.ones(16)]
    out = deadband_speed_cap(f, deadband=0.06, max_step=0.1)
    assert np.all(np.abs(np.diff(out)) <= 0.1 + 1e-9)
    assert out[-1] > 0.99
    wobble = 0.5 + 0.02 * np.sin(np.arange(20))  # inside the deadband: hold still
    assert np.ptp(deadband_speed_cap(wobble, 0.06, 0.1)) == 0


def test_follow_tracks_slow_target_with_capped_speed():
    n = 60
    cx = 0.15 + 0.7 * np.arange(n) / n  # 1.2 % of width per 0.5 s
    plan = plan_crop(_sig(cx), 0.0, n * HOP, _info(), LayoutOptions(), RenderOptions())
    assert plan.mode == "follow" and len(plan.keyframes) == n
    keys = np.array(plan.keyframes)
    assert keys[0, 0] == 0.0 and np.all(np.diff(keys[:, 0]) > 0)
    w, cw = 1920, 1080 * 1920 / 1920 * 9 / 16 * 1920 / 1080
    cw = 1080 * 9 / 16
    travel = w - cw
    centre = (keys[:, 1] * travel + cw / 2) / w
    # after the smoother settles, crop centre within 6 % of the true target
    assert np.abs(centre[20:] - cx[20:]).max() < 0.06
    speed = np.abs(np.diff(keys[:, 1])) * travel / w / HOP  # fraction of width per second
    assert speed.max() <= LayoutOptions().pan_speed + 1e-6


def test_fallbacks():
    n = 40
    lay, ren, inf = LayoutOptions(), RenderOptions(), _info()
    sparse = np.full(n, np.nan)
    sparse[:5] = 0.5
    assert plan_crop(_sig(sparse), 0, 20, inf, lay, ren).mode == "center"
    diffuse = plan_crop(_sig(np.full(n, 0.5), spread=0.28), 0, 20, inf, lay, ren)
    assert diffuse.mode == "center" and "diffuse" in diffuse.reason
    assert plan_crop(_sig(np.full(n, 0.5)), 0, 20, _info(1080, 1920), lay, ren).mode == "center"
    static = plan_crop(_sig(np.full(n, 0.3)), 0, 20, inf, lay, ren)
    assert static.mode == "follow" and len(static.keyframes) == 1
    lay.crop = "center"
    assert plan_crop(_sig(np.full(n, 0.3)), 0, 20, inf, lay, ren).mode == "center"


def test_x_expression_shape():
    assert x_expression([]) == "0.5"
    assert x_expression([[0.0, 0.25]]) == "0.2500"
    e = x_expression([[0.0, 0.0], [1.0, 1.0], [2.0, 0.5]])
    assert e.startswith("if(lt(t,1.000),") and e.endswith("0.5000))") and "," in e
    assert e.count("if(") == 2
