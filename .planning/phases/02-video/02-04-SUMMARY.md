# 02-04 Summary — Detector round 2: an absolute bar across games (BENCHMARK #1, #2) — DONE 2026-11-12

Commits: f26db52 repair (plan commit 3bd5a86 was made from the stale main index and dropped 4,277 committed lines; tree restored, no code change) · 2ada4cc absolute bar · b2d409c `--min-score` + TOML · full pytest 83 passed 1 skipped, ruff clean.

Built: `scoring.evidence()` — raw signals against FIXED reference levels (config constants, measured on real footage), not the file's own scale: audio = sharp AND loud (onset ramp 0.25→0.7 × (½+½·loud 4→16 dB); a swell alone ≤ 0.7, a click alone ≤ 0.5), visual = motion/24 × coverage (1−still, ramp 0.3→0.7, half weight) × cspread ramp, averaged over ±3 s (must PERSIST: a page flip or a cut is one big frame), evidence = ½·max + ½·min of the two (one group alone never clears the bar). Bar `min_evidence` 0.5 filters candidates before the relative floor; score ×(½+½·evidence); needs both groups — a no-audio file ranks against itself (02-02 behaviour). CLI `--min-score 0..1` (0 = off), TOML `min_evidence`. 3 unit tests; the music/quiet ranking tests run with the bar off (a 5 % moving square is below the real-footage bar by design).

COD2 (40 min), top 10, 02-02 → now: duds 1 → 1 (12:32 round-start text: loud onsets + full-frame motion — still passes), precision@10 0.70 → 0.80, 10 clips returned.
| # | 02-02 | 02-04 (evidence) |
|---|---|---|
| 1–3 | 35:12 explosive, 39:44 final kill, 12:32 round-start DUD | 39:44 final kill (0.74), 12:32 DUD (0.79), 01:22 kill (0.79) |
| 4–7 | 00:10 smoke+kill, 38:40 ?, 01:22 kill, 19:50 ? | 00:10 smoke+kill (0.59), 03:07 ? (0.80), 35:12 explosive (0.86), 09:20 ADS+kill (1.00) |
| 8–10 | 03:07 ?, 29:21 ?, 24:02 ? | 10:36 killed-by (0.83), 18:56 truck kill (0.81), 08:34 grenade (0.82) |

Persona 3 (74 min RPG), 33 labels now (+ awakening, 3 Tartarus battles, 15 duds): 02-02 7 duds / 10 returned → now 5 returned (asked 10), 0 duds, 5/5 battles by peak label, `below_floor` warned.
| # | 02-02 | 02-04 |
|---|---|---|
| 1–3 | 00:54 quote text DUD, 52:53 cutscene DUD, 35:14 awakening | 62:47 shadow battle (0.69), 61:09 shadow battle (0.56), 59:32 first battle (0.52) |
| 4–5 | 00:06 title DUD, 49:36 dialogue DUD | 60:27 battle animation (0.58), 64:31 battle HP bars (0.58) |
| 6–10 | menu, sky, map, card-select DUDs, 72:03 map walk | — (first dud, the quote scroll, sits at 0.47) |
Sheets: `/Users/shreyassawant/clip-anything-footage/out-cod2-r2/{top8,candidates}.jpg`, `out-persona3-r2/{top5,candidates}.jpg` (+ .txt). Timing alone (M1 Max, `--dry-run --no-cache --no-captions`): COD 40 min 31.6 s (47 s/h); Persona 74 min 32.4 s (26 s/h), load avg 8 from the other executor.

Weak / honest: the awakening explosion (plan target #1) is NOT returned (evidence 0.29): no audio onset at all (music), a 1.5 s visual burst, and `flash` fires just as hard on anime white transitions (train 0.95, sky 0.88, map walk 0.6–0.99) so it cannot be the audio partner. Persona clip windows: 2 of 5 midpoints land on a RESULT screen / dialogue (45 s windows in a turn-based game carry menus — BENCHMARK #5, window shaping). Margins are thin (COD smoke clip 0.59 vs bar 0.5; Persona first dud 0.47). cspread was NOT discriminative on these files (menus 0.17–0.29 ≈ combat) — kept as a mild cursor guard. Motion steadiness (plan fix 3) overlaps combat (CoV 0.24–0.8) — not used. `below_floor` warning text in pipeline.py still says "scored >= 0.20" (pipeline owner; should say "cleared the action bar 0.5; lower --min-score"). Calibrated on 2 games; BENCHMARK #2 (unseen game) unmeasured. Repo: main session commits must use a private index (`git read-tree HEAD`) — the main index is stale.
