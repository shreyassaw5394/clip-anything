#!/usr/bin/env python3
"""Detector eval on labelled footage (BENCHMARK #1). Footage and labels stay outside the repo.

  python scripts/eval.py <video> <labels.json> [--count N] [--out dir] [--sheet 30]

labels.json = [{"start": s, "end": e, "label": "action" | "dud", "note": "..."}, ...]
Prints precision@N, duds@N and recall of labelled action spans for the clips the tool would
really produce, then writes <out>/candidates.jpg: the top --sheet candidates (floor off),
6 per row, frame at each clip midpoint, with <out>/candidates.txt as the rank/time sidecar
(ffmpeg here has no drawtext). Reads the signal cache, so re-runs cost seconds.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clip_anything.config import Options  # noqa: E402
from clip_anything.pipeline import run  # noqa: E402

COLS = 6


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def classify(clip: dict, labels: list[dict]) -> tuple[str, str]:
    """A clip is what its peak falls in; else what it overlaps for >= 3 s; else '?'."""
    best = ("?", "")
    for lab in labels:
        if lab["start"] <= clip["peak_t"] <= lab["end"]:
            return lab["label"], lab.get("note", "")
    for lab in labels:
        if _overlap(clip["start"], clip["end"], lab["start"], lab["end"]) >= 3.0:
            best = (lab["label"], lab.get("note", ""))
    return best


def _run(video: Path, count: int, out: Path, floor: float | None) -> dict:
    scoring = {} if floor is None else {"min_score": floor}
    opts = Options.from_layers(
        {
            "clips": {"count": count},
            "render": {"out_dir": str(out), "dry_run": True},
            "scoring": scoring,
        }
    )
    return run(video, opts).to_dict()


def _hms(t: float) -> str:
    t = int(round(t))
    return f"{t // 60:02d}:{t % 60:02d}"


def contact_sheet(video: Path, clips: list[dict], out_jpg: Path, labels: list[dict]) -> None:
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    rows = max(1, -(-len(clips) // COLS))
    lines = []
    with tempfile.TemporaryDirectory() as td:
        for i, c in enumerate(clips):
            mid = (c["start"] + c["end"]) / 2
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{mid:.2f}",
                    "-i",
                    str(video),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=320:180",
                    f"{td}/f{i:03d}.png",
                ],
                check=True,
            )
            kind, note = classify(c, labels)
            comp = " ".join(f"{k}={v:.2f}" for k, v in c["components"].items())
            lines.append(
                f"{i + 1:2d}  r{i // COLS + 1}c{i % COLS + 1}  {_hms(c['start'])}-{_hms(c['end'])}"
                f"  score={c['score']:.3f}  {comp}  [{kind}] {note}"
            )
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-nostdin",
                "-loglevel",
                "error",
                "-framerate",
                "1",
                "-i",
                f"{td}/f%03d.png",
                "-vf",
                f"tile={COLS}x{rows}:padding=4:margin=4:color=black",
                "-frames:v",
                "1",
                "-q:v",
                "3",
                str(out_jpg),
            ],
            check=True,
        )
    out_jpg.with_suffix(".txt").write_text("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video")
    ap.add_argument("labels")
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--out", default=None)
    ap.add_argument("--sheet", type=int, default=30)
    args = ap.parse_args(argv)
    video = Path(args.video)
    labels = json.loads(Path(args.labels).read_text()) if Path(args.labels).is_file() else []
    out = Path(args.out or (video.parent / f"out-{video.stem}"))
    out.mkdir(parents=True, exist_ok=True)

    real = _run(video, args.count, out, None)
    clips = real["clips"]
    t = real["timings"]
    print(f"{video.name}: {len(clips)} clips (count={args.count}), {real['candidates_total']} "
          f"candidates, analyse {t.get('analyze_s', 0):.1f}s")
    actions = [lab for lab in labels if lab["label"] == "action"]
    hit = duds = 0
    print(f"{'#':>2} {'time':>13} {'score':>6}  components  [label]")
    for c in clips:
        kind, note = classify(c, labels)
        hit += kind == "action"
        duds += kind == "dud"
        comp = " ".join(f"{k}={v:.2f}" for k, v in c["components"].items())
        print(f"{c['rank']:>2} {_hms(c['start'])}-{_hms(c['end'])} {c['score']:6.3f}  {comp}"
              f"  [{kind}] {note}")
    covered = sum(
        any(_overlap(c["start"], c["end"], a["start"], a["end"]) > 0 for c in clips)
        for a in actions
    )
    n = max(1, len(clips))
    print(f"precision@{len(clips)}={hit / n:.2f}  duds@{len(clips)}={duds}  "
          f"recall={covered}/{len(actions)}  unlabelled={len(clips) - hit - duds}")
    for w in real["warnings"]:
        print(f"warning[{w['stage']}/{w['code']}]: {w['message']}")

    sheet = _run(video, args.sheet, out, 0.0)
    contact_sheet(video, sheet["clips"], out / "candidates.jpg", labels)
    top = min(8, len(clips))
    contact_sheet(video, clips[:top], out / f"top{top}.jpg", labels)
    print(f"sheets: {out / 'candidates.jpg'} (+.txt), {out / f'top{top}.jpg'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
