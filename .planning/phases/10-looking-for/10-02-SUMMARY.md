# 10-02 Summary — Racing and constant-motion recordings: never "nothing stood out" — 2026-11-14

Branch `racing` (off docs-10-02), PR #31. Commit 9509e46 (scoring + app + tests + docs) + this docs commit. Full pytest green (7 new tests in tests/test_continuous.py), ruff clean, CI 6 jobs. Footage local only: /Users/shreyassawant/clip-anything-footage/{f1-2001-cc-by,gt1-pdm}.mp4 + LICENSE.txt (CC BY 4.0 / CC Public Domain Mark), labels/ (35 + 25 spans from film strips).

Cause confirmed on real footage: F1 2001 (3.85 h) whole-file rms_db MAD 1.4 dB (COD 8.0, BO2 5.1, Persona 3.5), onset p95 0.04 (0.44 / 0.20 / 0.30), motion median 13 with 79 % of windows moving. Audio evidence never passes 0.21, so the bar (needs sharp AND loud) is met only where motion is full: 4 of 10 clips, all replay pans / title. Gran Turismo 1 (2.37 h): 0 clips of 204 candidates = the friend's screen. Raw derivatives fire on loading wipes and menu clicks; only inside moving stretches do they find crashes.

Built: `scoring.continuity()` (profile auto|standard|continuous, `report.scoring`), `continuous_components()` = inside a moving mask (past 12 s median motion ≥ 8, no card, no cut ±2 s): `video.jolt` = relative motion drop (past 5 s vs next 2 s) or jump over the 12 s median, frozen frames (pause) excluded; `audio.impact` = new `audio.hi_db` (3–8 kHz, extractor v3) over its 12 s median. Score = derivatives + agreement at 0.2 (jolts without a sound must rank); evidence = 0.6·max + 0.4·min. Presets racing/sports force it; chip renamed "Racing & sports". Fallback: < min(count, 3) above the bar → top count by file-relative score, never a card, `below_bar_fallback` with the plan's sentence; flag dropped when the relative floor leaves only cleared moments. Reason lines "A sudden jolt" / "An impact sound"; app notes + empty state offers the chip.

| File | before (standard, honest count) | after (auto → continuous) |
|---|---|---|
| F1 2001 PS2 3.85 h | 4 of 10 clips, p@4 0.25, 2 duds, recall 1/14 | 10 clips, p@10 0.70, 2 duds, recall 7/14 (5 finish/results, 1 crash at #8; crashes rank 8/10/26/28 of 33 cleared) |
| Gran Turismo 1 2.37 h | 0 clips ("Nothing stood out") | 10 clips (fallback, 0 cleared), p@10 0.50, 5 duds (tunnel light changes, intro), recall 5/9; crash #1, overtakes, finish |
| COD2 / Persona 3 / BO2 | 0.80·1 dud / 5 returned·0 / 0.40·3 | unchanged (profile standard on all three) |
| synthetic drone + pan, 5 jolts | — | continuous detected, 5/5 in the top 5; plain fixture standard, lobby cards never returned |
Speed: F1 3.85 h alone `--no-cache --dry-run` 68 s wall = 18 s/h (target ≤ 60). Screenshot of the fallback note + "sudden jolt" cards: /Users/shreyassawant/clip-anything-footage/shots/gt1-fallback.png (0 console errors).

Honest: the 3–8 kHz "impact" finds results chimes (10 dB) more than crash sounds in these PS1/PS2 titles (crash hi-band +0.6 to +5 dB), so F1's top five are race-classification screens; replay cameras and tunnel lighting changes are jolts too (no generic signal separates them; brightness guards also kill overtakes/finishes). Big-text flash not used (dropped in 10-01). Labels are film-strip judgements, one unlabelled F1 pick (107:46). Not verified: the friend's own recording, the empty-state chip button on real footage (fallback makes emptiness rare), Windows run.
