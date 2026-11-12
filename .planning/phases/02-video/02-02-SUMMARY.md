# 02-02 Summary — Detector quality on real footage (BENCHMARK #1, #5) — DONE 2026-11-12

Commits: cbe9f49 agreement score / soft z / static-card penalty / floor / eval harness · ef5ecb6 below_floor warning, lobby+agree e2e tests · c2166e7 relative floor, cuts are not motion, onset-exempt card. Full pytest 80 passed 1 skipped (all executors' tests), ruff clean.

Built: `scoring.py` — rolling z → `tanh(z/4)` with sigma floor `max(1.4826·MAD, eps, 0.25·(p90−p50))` (a flat stretch can no longer make the next small change 1.00); score = 0.2·weighted mean + 0.4·max + 0.4·agree, agree = gate-weighted geometric mean of the audio and motion groups (group = ½ weighted mean + ½ max; an uninformative group fades out instead of zeroing it); cuts are not motion (a cut window takes its neighbours' median motion in `finalize`) and the 0.15 cut bonus is gated off next to a card; static-card penalty `score·(1−0.8·card)`, card = ramp(rolling-median₁₀ₛ still 0.92→0.98)·ramp(stroke 0.3→0.8)·(1−onset); first/last 30 s ×0.8 unless agree ≥ 0.7; a clip starting at 0:00 with its peak in the first 10 s needs 2× the median top score; candidate score = ½ smoothed(σ 0.5 s) + ½ raw at the peak; floor = max(0.2, 0.35·best) — `--count` is a maximum, pipeline warns `below_floor`. `video_signals.py` v2 adds `video.still` (fraction |diff| ≤ 2) and `video.stroke` (fraction of changed pixels that vanish under a 3x3 opening on a 2x2 subsample = text strokes). `scripts/eval.py <video> <labels.json>`: precision@N, duds@N, recall, `candidates.jpg` (top-30, 6/row, sidecar .txt with rank/time/components/label; ffmpeg here has no drawtext) + `top8.jpg`. Labels at `/Users/shreyassawant/clip-anything-footage/labels/<file>.json` (19 COD spans, 15 Persona), never in the repo.

COD2 match (40 min, 720p30), top 10 — before → after (duds 3 → 1, precision@10 0.30 → 0.70, all 3 labelled duds gone):
| # | before | after |
|---|---|---|
| 1 | 39:44 end (loud 1.00 motion 1.00) — frames show the final kill at 40:00, relabelled action | 39:44 final kill (agree 0.83) |
| 2 | 00:00 lobby DUD (loud 0.05 motion 1.00) | 35:12 explosive planted + fire (agree 0.66, speech +0.6 from 03-01) |
| 3 | 12:31 round-start text DUD | 12:32 round-start text DUD (onset 0.97, 7 cuts — the one left) |
| 4 | 01:22 kill | 00:10 smoke + scope + kill (agree 0.77) |
| 5–7 | 25:28 kill, 27:00 ADS, 09:20 ADS+kill | 01:22 kill, 19:50 ?, 03:07 ? |
| 8–10 | 04:26 ready-up DUD, 20:32 ?, 17:10 | 31:54 kill, 24:26 kill, 10:36 killed-by |
Sheets: `out-cod-before/{top8,candidates}.jpg` → `out-cod-after/{top8,candidates}.jpg` (+ `check-end.jpg`, the frames behind the #1 relabel).

Persona 3 (74 min, RPG opening, 854x480@60), top 10 — before 8/8 duds (every pick motion 1.00) → after 7 duds + 3 unlabelled, still 10 returned (the two labelled battles at 37:02 and 64:29 are outside the top 10). Honest result: this file has no bursty action; cutscenes with music and animated menus/maps carry real audio+motion agreement (0.70–0.93, above the relative floor 0.33), and P3P menus/dialogue animate (still median 0.97 but card fires only at 05:37, 0.04). Sheets: `out-p3-before/` → `out-p3-after/{top8,candidates}.jpg` (+ `check.jpg`).

Synthetic: base/music/vfr/quiet/square unchanged; new `lobby` (silent card + card under loud music: never picked, 2/2 events found, below_floor warned) and `agree` (loud+motion 0.93 ranks first > loud-only 0.74 > motion-only 0.48).

Timing: extractor 0.16 → 0.26 ms/frame (+ ≈ 5 s CPU per hour inside the decode-bound video thread); the only fresh COD run measured 54 s but at load average 19 with three executors running — re-measure alone. Snap to cuts: 1 of 10 COD clips snapped its end to a cut (01:22–01:44), the rest to quiet points; not verified beyond that.

Weak: Persona stays 7/10 duds — scores are file-relative by construction; an absolute "what is action" floor needs calibration across games (phase 4). COD 12:31 round-start text survives (loud onsets + cuts look like a firefight). Card penalty needs still ≥ 0.92 so it misses animated menus. The speech bonus (03-01) is added after my floor and reorders the COD top-3 (+0.6 on 35:12). Floor is now relative (0.35·best): a file of nothing but duds still returns duds — only an absolute, cross-game calibrated floor fixes Persona. Main git index is stale (private-index commits) — `git reset -q` when nobody is mid-commit.
