"""The native window is optional: Windows opens the browser, and any window failure falls back."""
import sys
import types

import clip_anything.app.launch as launch_mod


def test_auto_prefers_browser_on_windows(monkeypatch):
    monkeypatch.setattr(launch_mod, "webview_available", lambda: True)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("CLIP_ANYTHING_WEBVIEW", raising=False)
    assert launch_mod._native_window_wanted("auto") is False
    monkeypatch.setenv("CLIP_ANYTHING_WEBVIEW", "1")
    assert launch_mod._native_window_wanted("auto") is True
    assert launch_mod._native_window_wanted("browser") is False


def test_auto_uses_window_elsewhere(monkeypatch):
    monkeypatch.setattr(launch_mod, "webview_available", lambda: True)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert launch_mod._native_window_wanted("auto") is True
    monkeypatch.setattr(launch_mod, "webview_available", lambda: False)
    assert launch_mod._native_window_wanted("auto") is False


def test_window_failure_falls_back_to_browser(monkeypatch, capsys):
    """A pywebview that blows up on start (the pythonnet failure seen on Windows) must not crash."""
    monkeypatch.setattr(launch_mod, "webview_available", lambda: True)
    monkeypatch.setattr(sys, "platform", "darwin")
    calls = []

    def fake_webview_launch(prefs, port):
        raise RuntimeError("Failed to resolve Python.Runtime.Loader.Initialize")

    def fake_browser_launch(prefs, port, open_ui, stop):
        calls.append(("browser", port, open_ui))
        return 0

    monkeypatch.setattr(launch_mod, "_launch_webview", fake_webview_launch)
    monkeypatch.setattr(launch_mod, "_launch_browser", fake_browser_launch)
    assert launch_mod.launch(window="auto", port=0, open_ui=False) == 0
    assert calls == [("browser", 0, False)]
    assert "browser instead" in capsys.readouterr().out


def test_explicit_window_failure_raises(monkeypatch):
    monkeypatch.setattr(launch_mod, "webview_available", lambda: True)

    def boom(prefs, port):
        raise RuntimeError("no .NET")

    monkeypatch.setattr(launch_mod, "_launch_webview", boom)
    monkeypatch.setattr(launch_mod, "_launch_browser", lambda *a: 0)
    try:
        launch_mod.launch(window="webview")
    except RuntimeError:
        pass
    else:
        raise AssertionError("explicit --window webview should surface the error")


def test_fake_module_import_not_required():
    assert isinstance(types, types.ModuleType)
