#!/usr/bin/env python3
"""Detector eval across every labelled recording (BENCHMARK #2: works on a game nobody tuned on).

  python scripts/eval-matrix.py [--footage ~/clip-anything-footage] [--count 10] [--preset P]
                                [--scoring '{"w_cut": 0}'] [--json out.json] [--only slug,slug]

Footage and labels stay outside the repo: <footage>/labels/<slug>.json (eval.py format) with the
video at <footage>/genres/<slug>/<slug>.mp4 or <footage>/<slug>.mp4. Reads the signal cache next
to each video, so a full matrix costs seconds after the first run. Prints one table: clips
returned of --count, precision@count (action / count asked), duds@count, recall of labelled
action spans, and the top-N label string (A action, D dud, n neutral, ? unlabelled).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from eval import _overlap, classify  # noqa: E402

from clip_anything.config import Options, preset_layer  # noqa: E402
from clip_anything.pipeline import run  # noqa: E402

MARK = {"action": "A", "dud": "D", "neutral": "n", "?": "?"}


def find_video(footage: Path, slug: str) -> Path | None:
    for p in (footage / "genres" / slug / f"{slug}.mp4", footage / f"{slug}.mp4"):
        if p.is_file():
            return p
    folder = footage / "genres" / slug
    hits = sorted(folder.glob("*.m*")) if folder.is_dir() else []
    return hits[0] if hits else None


def score_file(
    video: Path, labels: list[dict], count: int, preset: str | None, scoring: dict
) -> dict:
    opts = Options.from_layers(
        preset_layer(preset),
        {
            "clips": {"count": count},
            "render": {"out_dir": str(video.parent / "out-eval-matrix"), "dry_run": True},
            "scoring": scoring,
        },
    )
    rep = run(video, opts).to_dict()
    clips = rep["clips"]
    kinds = [classify(c, labels)[0] for c in clips]
    actions = [lab for lab in labels if lab["label"] == "action"]
    covered = sum(
        any(_overlap(c["start"], c["end"], a["start"], a["end"]) > 0 for c in clips)
        for a in actions
    )
    return {
        "video": str(video),
        "duration_s": rep["input"]["duration_s"],
        "returned": len(clips),
        "count": count,
        "action": kinds.count("action"),
        "duds": kinds.count("dud"),
        "recall": [covered, len(actions)],
        "labels": "".join(MARK.get(k, "?") for k in kinds),
        "profile": (rep.get("scoring") or {}).get("profile", ""),
        "fallback": bool((rep.get("scoring") or {}).get("fallback")),
        "warnings": [w["code"] for w in rep["warnings"] if w["code"] != "captions_off"],
        "analyze_s": rep["timings"].get("analyze_s", 0.0),
        "clips": [
            {
                "rank": c["rank"],
                "start": c["start"],
                "end": c["end"],
                "score": c["score"],
                "label": k,
            }
            for c, k in zip(clips, kinds, strict=True)
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--footage", default=str(Path.home() / "clip-anything-footage"))
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--preset", default=None)
    ap.add_argument("--scoring", default=None, help="JSON of ScoringOptions overrides")
    ap.add_argument("--json", default=None, help="write the full per-file results here")
    ap.add_argument("--only", default=None, help="comma-separated slugs")
    args = ap.parse_args(argv)
    footage = Path(args.footage).expanduser()
    scoring = json.loads(args.scoring) if args.scoring else {}
    only = set(args.only.split(",")) if args.only else None
    label_files = sorted((footage / "labels").glob("*.json"))
    if not label_files:
        print(f"no labels under {footage / 'labels'}", file=sys.stderr)
        return 2
    rows: dict[str, dict] = {}
    print(
        f"{'file':22} {'dur':>6} {'ret':>5} {'p@N':>5} {'duds':>4} {'recall':>7}  "
        f"top-N       profile    warnings"
    )
    tot_a = tot_d = 0
    for lf in label_files:
        slug = lf.stem
        if only and slug not in only:
            continue
        video = find_video(footage, slug)
        if video is None:
            print(f"{slug:22} (no video)")
            continue
        labels = json.loads(lf.read_text())
        if not isinstance(labels, list) or not labels:
            print(f"{slug:22} (no labels)")
            continue
        r = score_file(video, labels, args.count, args.preset, scoring)
        rows[slug] = r
        tot_a += r["action"]
        tot_d += r["duds"]
        rc = f"{r['recall'][0]}/{r['recall'][1]}"
        print(
            f"{slug:22} {r['duration_s'] / 60:5.0f}m {r['returned']:>2}/{args.count:<2} "
            f"{r['action'] / args.count:5.2f} {r['duds']:>4} {rc:>7}  {r['labels']:<10}  "
            f"{(r['profile'] or '-') + ('*' if r['fallback'] else ''):<10} "
            f"{','.join(r['warnings'])}"
        )
    print(f"total: action {tot_a}, duds {tot_d} over {len(rows)} files")
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
