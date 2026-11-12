"""Content-id cache for analysis signals: <video_dir>/.clipanything/<id>/signals.npz."""

from __future__ import annotations

import hashlib
import io
import os
import tempfile
from pathlib import Path

import numpy as np

from .config import ANALYSIS_SCHEMA

SAMPLE = 1 << 20  # 1 MiB


def content_id(path: str | os.PathLike) -> str:
    """sha256(size || head 1MiB || middle 1MiB || tail 1MiB || schema)[:16]. O(1) on huge files."""
    p = Path(path)
    size = p.stat().st_size
    h = hashlib.sha256()
    h.update(str(size).encode())
    with open(p, "rb") as fh:
        for offset in (0, max(0, size // 2 - SAMPLE // 2), max(0, size - SAMPLE)):
            fh.seek(offset)
            h.update(fh.read(SAMPLE))
    h.update(f"schema{ANALYSIS_SCHEMA}".encode())
    return h.hexdigest()[:16]


class SignalCache:
    """Tiny file cache. `enabled=False` makes every get a miss and every put a no-op."""

    def __init__(self, video_path: str | os.PathLike, cache_dir: str | None, enabled: bool):
        self.enabled = enabled
        self.id = content_id(video_path)
        root = Path(cache_dir) if cache_dir else Path(video_path).resolve().parent / ".clipanything"
        self.dir = root / self.id
        # A cache folder that is really a symlink (planted in a shared download folder, say)
        # would send our writes elsewhere; treat it as no cache rather than follow it.
        if root.is_symlink() or self.dir.is_symlink():
            self.enabled = False

    def path(self, name: str) -> Path:
        return self.dir / name

    def get_npz(self, name: str, fingerprint: str) -> dict[str, np.ndarray] | None:
        if not self.enabled:
            return None
        p = self.path(name)
        if not p.is_file():
            return None
        try:
            with np.load(p, allow_pickle=False) as z:
                if str(z["fingerprint"]) != fingerprint:
                    return None
                return {k: z[k] for k in z.files if k != "fingerprint"}
        except Exception:  # corrupt/foreign file = miss, never error
            return None

    def put_npz(self, name: str, fingerprint: str, arrays: dict[str, np.ndarray]) -> Path | None:
        if not self.enabled:
            return None
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            buf = io.BytesIO()
            np.savez(buf, fingerprint=np.array(fingerprint), **arrays)
            fd, tmp = tempfile.mkstemp(dir=self.dir, suffix=".part")
            with os.fdopen(fd, "wb") as fh:
                fh.write(buf.getvalue())
            os.replace(tmp, self.path(name))
            return self.path(name)
        except OSError:
            return None
