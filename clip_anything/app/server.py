"""Local HTTP server for the app UI. Stdlib only, loopback only.

Every request: the Host header must be a loopback name (DNS rebinding), a browser Origin must be
this server itself, writes reject cross-site `Sec-Fetch-Site`, and everything but the static
files needs the per-launch token (`?t=` on the page URL and media/SSE, `Authorization: Bearer`
on the JSON API). Clip files are served only from the job's own output folder, by basename.
Responses carry a strict CSP (`default-src 'self'`): the UI has no inline code or styles.
"""

from __future__ import annotations

import hmac
import json
import mimetypes
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .. import __version__
from .data import Recent
from .jobs import MAX_COUNT, Job, JobRequest

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
STATIC_DIR = Path(__file__).resolve().parent / "static"
CLIP_SUFFIXES = {".mp4", ".ass", ".txt", ".json"}
MAX_BODY = 256 * 1024
MAX_JOBS = 50
SSE_HEARTBEAT_S = 15.0
CSP = (
    "default-src 'self'; script-src 'self'{eval}; style-src 'self'; img-src 'self' data:; "
    "media-src 'self'; font-src 'self'; connect-src 'self'; object-src 'none'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
# the native window's bridge (pywebview) evaluates its own scripts with eval; the browser
# mode keeps the strict policy. Neither allows inline code or styles.
CSP_BY_WINDOW = {"browser": CSP.format(eval=""), "webview": CSP.format(eval=" 'unsafe-eval'")}
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".webmanifest": "application/manifest+json",
}


def bare_host(host: str) -> str:
    h = (host or "").strip().lower()
    if h.startswith("["):
        return h[1 : h.find("]")] if "]" in h else h
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


def is_loopback_host(host: str | None) -> bool:
    return bool(host) and bare_host(host) in LOOPBACK


def origin_is_self(origin: str | None, port: int) -> bool:
    """No Origin (a non-browser client) or exactly this server over http."""
    if not origin:
        return True
    try:
        u = urlsplit(origin)
    except ValueError:
        return False
    if u.scheme != "http" or u.hostname is None:
        return False
    return u.hostname.lower().strip("[]") in LOOPBACK and (u.port or 80) == port


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class AppServer:
    """Owns the state (jobs, token, picker) and the listening socket; one thread serves."""

    def __init__(
        self,
        *,
        port: int = 0,
        token: str | None = None,
        static_dir: Path | None = None,
        runner: Callable | None = None,
        picker: Callable[[str], list[str]] | None = None,
        recent: Recent | None = None,
        window: str = "browser",
        on_quit: Callable[[], None] | None = None,
    ) -> None:
        self.token = token or secrets.token_urlsafe(32)
        self.static_dir = (static_dir or STATIC_DIR).resolve()
        self.runner = runner
        self.picker = picker
        self.recent = recent or Recent()
        self.window = window
        self.on_quit = on_quit
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self._caps_cache: tuple[float, dict] | None = None
        self._install_lock = threading.Lock()
        self.httpd = _Server(("127.0.0.1", port), _Handler, self)
        self.port = self.httpd.server_address[1]
        self.thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?t={self.token}"

    def start(self) -> AppServer:
        self.thread = threading.Thread(
            target=self.httpd.serve_forever, name="app-http", daemon=True
        )
        self.thread.start()
        return self

    def stop(self) -> None:
        for job in list(self.jobs.values()):
            if job.running:
                job.cancel()
        self.httpd.shutdown()
        self.httpd.server_close()

    def token_ok(self, candidate: str | None) -> bool:
        return bool(candidate) and hmac.compare_digest(candidate, self.token)

    # -- API ------------------------------------------------------------------------------
    def caps(self) -> dict:
        now = time.time()
        if self._caps_cache and now - self._caps_cache[0] < 10:
            return self._caps_cache[1]
        from ..errors import FFmpegMissing
        from ..gui import captions_available
        from ..probe import preflight

        ffmpeg: dict = {"ok": False, "detail": ""}
        try:
            c = preflight()
            ffmpeg = {"ok": True, "version": f"{c.version[0]}.{c.version[1]}", "libass": c.captions}
        except FFmpegMissing as exc:
            ffmpeg = {"ok": False, "detail": str(exc)}
        whisper = "missing_dep"
        if captions_available():
            from ..speech import model_status

            whisper = model_status("base.en")
        data = {
            "version": __version__,
            "platform": sys.platform,
            "window": self.window,
            "ffmpeg": ffmpeg,
            "captions": captions_available(),
            "whisper": whisper,
            "ai": self._ai_status(),
            "home": str(Path.home()),
            "max_count": MAX_COUNT,
            "recent": self.recent.load(),
        }
        self._caps_cache = (now, data)
        return data

    def _ai_status(self) -> dict:
        from ..ai import AISettings, resolve_provider

        provider, why = resolve_provider(AISettings())
        if provider is None:
            return {"ok": False, "reason": why, "cloud": False, "model": ""}
        host = getattr(provider, "host", "")
        return {
            "ok": True,
            "cloud": bool(host),
            "host": host,
            "model": getattr(provider, "model", "") or getattr(provider, "text_model", ""),
            "reason": "",
        }

    def create_job(self, data: dict) -> Job:
        try:
            req = JobRequest.from_json(data)
        except ValueError as exc:
            raise ApiError(400, str(exc)) from None
        if not req.out_dir:
            req.out_dir = req.default_out_dir()
        problem = req.problem()
        if problem:
            raise ApiError(400, problem)
        with self.lock:
            if any(j.running for j in self.jobs.values()):
                raise ApiError(409, "A run is already in progress.")
            req.force = self._needs_rerender(req)
            job = Job(req, self.runner)
            problem = job.prepare_ai()
            if problem:
                raise ApiError(400, problem)
            self.jobs[job.id] = job
            while len(self.jobs) > MAX_JOBS:
                oldest = min(self.jobs.values(), key=lambda j: j.created)
                if oldest.running:
                    break
                del self.jobs[oldest.id]
        self._caps_cache = None
        job.start()
        threading.Thread(target=self._remember, args=(job,), daemon=True).start()
        return job

    def _needs_rerender(self, req: JobRequest) -> bool:
        """Clips are named by rank and time, so a re-run with the same look (captions, facecam,
        crop, length) can keep identical files and finish in seconds; a changed look renders
        them again. Unknown previous settings (first run on this folder): overwrite."""
        out = str(Path(req.out_dir).resolve()) if req.out_dir else ""
        previous = None
        for j in sorted(self.jobs.values(), key=lambda j: j.created, reverse=True):
            if j.state == "done" and str(j.out_dir() or "") == out:
                previous = j.request
                break
        if previous is None:
            for item in self.recent.load():
                if str(Path(str(item.get("out_dir", ""))).resolve()) == out:
                    previous = JobRequest.from_json(item)
                    break
        if previous is None:
            return True
        same = (previous.captions, previous.facecam, previous.crop, previous.length, previous.ai)
        return same != (req.captions, req.facecam, req.crop, req.length, req.ai)

    def _remember(self, job: Job) -> None:
        job.thread.join() if job.thread else None
        if job.state == "done" and job.report is not None:
            req = job.request
            self.recent.add(
                {
                    "inputs": req.inputs,
                    "out_dir": str(job.out_dir() or req.out_dir),
                    "count": req.count,
                    "length": req.length,
                    "captions": req.captions,
                    "facecam": req.facecam,
                    "crop": req.crop,
                    "ai": req.ai,
                    "clips": job.result()["ok"],
                    "name": job.result()["input"]["name"],
                }
            )
            self._caps_cache = None

    def job(self, job_id: str) -> Job:
        job = self.jobs.get(job_id or "")
        if job is None:
            raise ApiError(404, "No such run.")
        return job

    def clip_path(self, job: Job, name: str) -> Path:
        """A file inside the job's output folder, by basename only."""
        out = job.out_dir()
        if not out or not name or name != os.path.basename(name) or name.startswith("."):
            raise ApiError(404, "Not found.")
        if "/" in name or "\\" in name or "\x00" in name or Path(name).suffix not in CLIP_SUFFIXES:
            raise ApiError(404, "Not found.")
        p = (out / name).resolve()
        if p.parent != out or not p.is_file() or p.is_symlink():
            raise ApiError(404, "Not found.")
        return p

    def open_path(self, job: Job, what: str, name: str = "") -> None:
        out = job.out_dir()
        if not out or not out.is_dir():
            raise ApiError(404, "The output folder does not exist.")
        if what == "folder":
            _open([str(out)], reveal=False)
        elif what == "file":
            _open([str(self.clip_path(job, name))], reveal=False)
        elif what == "reveal":
            _open([str(self.clip_path(job, name))], reveal=True)
        else:
            raise ApiError(400, "Unknown action.")

    def delete_clip(self, job: Job, name: str) -> list[str]:
        p = self.clip_path(job, name)
        if p.suffix != ".mp4":
            raise ApiError(400, "Only clips can be deleted here.")
        removed = []
        for s in (p, p.with_suffix(".ass"), p.with_suffix(".txt")):
            if s.is_file() and not s.is_symlink():
                s.unlink()
                removed.append(s.name)
        if job.report is not None:
            for c in job.report.clips:
                if c.path and os.path.basename(c.path) == name:
                    c.status, c.error, c.path = "deleted", None, None
        return removed

    def setup_steps(self) -> list[dict]:
        from .. import setup_cmd as sc

        t = sc.Tools()
        steps = [
            sc.check_ffmpeg(t, captions=True),
            sc.check_python(t),
            sc.check_captions_dep(t),
            sc.check_whisper_model(t, sc.DEFAULT_WHISPER),
            sc.check_ollama(t),
            sc.check_vision_model(t, sc.DEFAULT_VISION_MODEL),
        ]
        return [
            {
                "key": s.key,
                "label": SETUP_LABELS.get(s.key, (s.label, ""))[0],
                "why": SETUP_LABELS.get(s.key, ("", ""))[1],
                "ok": s.ok,
                "detail": _sentence(s.detail),
                "fix": " ".join(s.fix) if s.fix else "",
                "download": bool(s.action and not s.fix),
                "note": _sentence(s.note),
                "required": s.required or s.key in ("ffmpeg", "python"),
            }
            for s in steps
        ]

    def setup_install(self, key: str) -> dict:
        """Run the fix for one step, after the user pressed its button. Returns the re-check."""
        from .. import setup_cmd as sc

        if not self._install_lock.acquire(blocking=False):
            raise ApiError(409, "An install is already running.")
        try:
            t = sc.Tools()
            checks = {
                "ffmpeg": lambda: sc.check_ffmpeg(t, captions=True),
                "captions": lambda: sc.check_captions_dep(t),
                "whisper": lambda: sc.check_whisper_model(t, sc.DEFAULT_WHISPER),
                "ollama": lambda: sc.check_ollama(t),
                "vision": lambda: sc.check_vision_model(t, sc.DEFAULT_VISION_MODEL),
            }
            if key not in checks:
                raise ApiError(400, "Unknown step.")
            step = checks[key]()
            if step.ok:
                return {"ok": True, "detail": step.detail, "output": ""}
            output = ""
            if step.fix:
                rc, output = _run_capture(step.fix)
                err = "" if rc == 0 else f"exit {rc}"
            elif step.action:
                err = step.action()
            else:
                raise ApiError(400, step.note or "This step has to be done by hand.")
            again = checks[key]()
            return {
                "ok": again.ok,
                "detail": _sentence(again.detail) + (f" ({err})" if err and not again.ok else ""),
                "output": output[-4000:],
            }
        finally:
            self._install_lock.release()


SETUP_LABELS = {
    "ffmpeg": ("Video tools (ffmpeg)", "Reads your recording and renders the clips. Required."),
    "python": ("Python", "Runs the tool. Required."),
    "captions": ("Captions (speech recognition)", "Adds burned-in captions when someone speaks."),
    "whisper": ("Speech model (base.en)", "The model captions use; downloaded once, about 150 MB."),
    "ollama": ("Ollama (local AI)", "Runs a small AI model on this computer for titles and picks."),
    "vision": ("Local AI model (qwen3-vl:4b)", "The model Ollama uses to look at frames; ~3 GB."),
}


def _sentence(text: str) -> str:
    text = (text or "").strip()
    return text[:1].upper() + text[1:] if text else ""


def _run_capture(argv: list[str]) -> tuple[int, str]:
    try:
        res = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=1800)
    except OSError as exc:
        return 127, f"could not run {argv[0]}: {exc}"
    except subprocess.TimeoutExpired:
        return 124, "timed out after 30 minutes"
    return res.returncode, (res.stdout or "") + (res.stderr or "")


def _open(paths: list[str], reveal: bool) -> None:
    """Open a file/folder with the desktop, or reveal a file in its folder. argv only."""
    if sys.platform == "darwin":
        argv = ["open", "-R", *paths] if reveal else ["open", *paths]
    elif sys.platform == "win32":
        if reveal:
            argv = ["explorer", f"/select,{paths[0]}"]
        else:
            os.startfile(paths[0])  # type: ignore[attr-defined]  # noqa: S606
            return
    else:
        argv = ["xdg-open", str(Path(paths[0]).parent) if reveal else paths[0]]
    subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False
    address_family = socket.AF_INET

    def __init__(self, addr, handler, app: AppServer) -> None:
        self.app = app
        super().__init__(addr, handler)

    def handle_error(self, request, client_address) -> None:
        """A <video> element aborts range requests all the time: not worth a traceback."""
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "clip-anything"
    sys_version = ""

    def log_message(self, fmt, *args):  # quiet; the CLI owns stdout
        pass

    @property
    def app(self) -> AppServer:
        return self.server.app  # type: ignore[attr-defined]

    # -- plumbing --
    def _headers(self, status: int, ctype: str, length: int | None = None, extra=None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        if length is not None:
            self.send_header("Content-Length", str(length))
        csp = CSP_BY_WINDOW.get(self.app.window, CSP_BY_WINDOW["browser"])
        self.send_header("Content-Security-Policy", csp)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def _json(self, data, status: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body))
        if self.command != "HEAD":
            self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        self._json({"ok": False, "error": message}, status)

    def _guard(self, write: bool) -> bool:
        if not is_loopback_host(self.headers.get("Host")):
            self._error(403, "Forbidden.")
            return False
        if not origin_is_self(self.headers.get("Origin"), self.app.port):
            self._error(403, "Forbidden.")
            return False
        if write:
            site = (self.headers.get("Sec-Fetch-Site") or "").lower()
            if site and site not in ("same-origin", "none"):
                self._error(403, "Forbidden.")
                return False
        return True

    def _authed(self, query: dict) -> bool:
        auth = self.headers.get("Authorization") or ""
        token = auth[7:] if auth.startswith("Bearer ") else (query.get("t") or [""])[0]
        if self.app.token_ok(token):
            return True
        self._error(401, "Unauthorized.")
        return False

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length < 0 or length > MAX_BODY:
            raise ApiError(413, "Body too large.")
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if length and ctype != "application/json":
            raise ApiError(415, "Send JSON.")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            raise ApiError(400, "Invalid JSON.") from None
        if not isinstance(data, dict):
            raise ApiError(400, "Body must be an object.")
        return data

    # -- routing --
    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802
        if not self._guard(write=False):
            return
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        parts = [p for p in url.path.split("/") if p]
        try:
            if not parts:
                if not self._authed(query):
                    return
                return self._static("index.html")
            if parts[0] == "static" and 2 <= len(parts) <= 3:
                return self._static(parts[1:])
            if parts[0] == "api":
                if not self._authed(query):
                    return
                return self._api_get(parts[1:], query)
            if parts[0] == "clips" and len(parts) == 3:
                if not self._authed(query):
                    return
                return self._file(self.app.clip_path(self.app.job(parts[1]), parts[2]))
            raise ApiError(404, "Not found.")
        except ApiError as exc:
            self._error(exc.status, exc.message)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self) -> None:  # noqa: N802
        if not self._guard(write=True):
            return
        url = urlsplit(self.path)
        parts = [p for p in url.path.split("/") if p]
        try:
            if not self._authed(parse_qs(url.query)):
                return
            if not parts or parts[0] != "api":
                raise ApiError(404, "Not found.")
            data = self._body()
            return self._api_post(parts[1:], data)
        except ApiError as exc:
            self._error(exc.status, exc.message)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _api_get(self, parts: list[str], query: dict) -> None:
        app = self.app
        if parts == ["caps"]:
            return self._json(app.caps())
        if parts == ["setup"]:
            return self._json({"steps": app.setup_steps()})
        if parts and parts[0] == "jobs":
            if len(parts) == 2:
                return self._json(app.job(parts[1]).status())
            if len(parts) == 3 and parts[2] == "events":
                since = int((query.get("since") or ["0"])[0] or 0)
                last_id = self.headers.get("Last-Event-ID")
                if last_id and last_id.isdigit():
                    since = int(last_id) + 1
                return self._sse(app.job(parts[1]), max(0, since))
        raise ApiError(404, "Not found.")

    def _api_post(self, parts: list[str], data: dict) -> None:
        app = self.app
        if parts == ["jobs"]:
            job = app.create_job(data)
            return self._json({"ok": True, "id": job.id, "disclosure": job.disclosure}, 201)
        if len(parts) == 3 and parts[0] == "jobs":
            job = app.job(parts[1])
            if parts[2] == "cancel":
                job.cancel()
                return self._json({"ok": True})
            if parts[2] == "open":
                app.open_path(job, str(data.get("what", "")), str(data.get("file", "")))
                return self._json({"ok": True})
            if parts[2] == "delete":
                removed = app.delete_clip(job, str(data.get("file", "")))
                return self._json({"ok": True, "removed": removed})
        if parts == ["setup", "install"]:
            return self._json({"ok": True, **app.setup_install(str(data.get("key", "")))})
        if parts == ["pick"]:
            kind = str(data.get("kind", "files"))
            if kind not in ("files", "folder", "out"):
                raise ApiError(400, "Unknown picker.")
            if app.picker is None:
                return self._json({"ok": True, "paths": [], "unsupported": True})
            return self._json({"ok": True, "paths": app.picker(kind)})
        if parts == ["recent", "clear"]:
            app.recent.clear()
            app._caps_cache = None
            return self._json({"ok": True})
        if parts == ["quit"]:
            self._json({"ok": True})
            if app.on_quit:
                threading.Thread(target=app.on_quit, daemon=True).start()
            return None
        raise ApiError(404, "Not found.")

    # -- responses --
    def _static(self, parts: str | list[str]) -> None:
        parts = [parts] if isinstance(parts, str) else parts
        if any(x != os.path.basename(x) or x.startswith(".") or not x for x in parts):
            raise ApiError(404, "Not found.")
        root = self.app.static_dir
        p = root.joinpath(*parts).resolve()
        if root not in p.parents or not p.is_file() or p.is_symlink():
            raise ApiError(404, "Not found.")
        ctype = (
            STATIC_TYPES.get(p.suffix)
            or mimetypes.guess_type(p.name)[0]
            or "application/octet-stream"
        )
        data = p.read_bytes()
        cache = (
            {"Cache-Control": "no-cache"}
            if p.suffix == ".html"
            else {"Cache-Control": "max-age=3600"}
        )
        self._headers(200, ctype, len(data), cache)
        if self.command != "HEAD":
            self.wfile.write(data)

    def _file(self, p: Path) -> None:
        """Whole file or a single byte range (so <video> can scrub)."""
        size = p.stat().st_size
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if p.suffix == ".ass":
            ctype = "text/plain; charset=utf-8"
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        status = 200
        if rng and rng.startswith("bytes=") and size > 0:
            spec = rng[6:].split(",")[0].strip()
            a, _, b = spec.partition("-")
            try:
                if a:
                    start = int(a)
                    end = int(b) if b else size - 1
                elif b:
                    start = max(0, size - int(b))
                else:
                    raise ValueError
            except ValueError:
                raise ApiError(400, "Bad range.") from None
            if start >= size or start < 0:
                self._headers(416, "text/plain", 0, {"Content-Range": f"bytes */{size}"})
                return
            end = min(end, size - 1)
            status = 206
        length = end - start + 1 if size else 0
        extra = {"Accept-Ranges": "bytes"}
        if status == 206:
            extra["Content-Range"] = f"bytes {start}-{end}/{size}"
        self._headers(status, ctype, length, extra)
        if self.command == "HEAD":
            return
        with p.open("rb") as fh:
            fh.seek(start)
            left = length
            while left > 0:
                chunk = fh.read(min(1 << 16, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    def _sse(self, job: Job, since: int) -> None:
        self.close_connection = True
        self._headers(
            200,
            "text/event-stream; charset=utf-8",
            None,
            {"X-Accel-Buffering": "no", "Connection": "close"},
        )
        self.wfile.write(b"retry: 1000\n\n")
        self.wfile.flush()
        last_beat = time.time()
        while True:
            events = job.wait_events(since, timeout=1.0)
            for ev in events:
                payload = json.dumps(ev, separators=(",", ":"))
                self.wfile.write(
                    f"id: {ev['seq']}\nevent: {ev['kind']}\ndata: {payload}\n\n".encode()
                )
                since = ev["seq"] + 1
                if ev["kind"] == "finished":
                    self.wfile.flush()
                    return
            if events:
                self.wfile.flush()
            if time.time() - last_beat > SSE_HEARTBEAT_S:
                self.wfile.write(b": ping\n\n")
                self.wfile.flush()
                last_beat = time.time()
            if not job.running and not events and since >= len(job.events):
                return
