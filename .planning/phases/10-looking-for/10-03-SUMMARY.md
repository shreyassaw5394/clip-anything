# 10-03 Summary — Genre pass: does it work on a game nobody tuned on? — 2026-11-14

Branch `genres` off main (after #31). Full pytest green, ruff clean, 3 new tests. Footage + labels local only: ~/clip-anything-footage/genres/<slug>/ (12 archive.org CC/PD recordings, LICENSE.txt each), labels/*.json (~400 spans from 3-frame strips at peak −6/0/+6 s), labels/BASELINE-main-2026-11-14.md (pre-#31 table).

Phase A (main 8b62ee5): GTA IV chase 0.80/0 duds; GTA 5 free roam 0.10/2 (pause map, respawn cam first; crashes at ranks 16–24); GTA 5 story 0.20/1 (title intro #1); Cyberpunk 0.10/6 (dialogue scenes); MK XL 2 returned, NBA 6, Madden 3, Outlast 3, Fortnite 2, SMB3 0, Hearthstone 0 (bar needs gunfire-shaped audio); Dead Space 2 0.50/4.

Built (game-agnostic):
- `scoring.cinematic()`: hard cuts per minute over ±15 s × a voice reaction → `w_cine` 0.5 demotion applied per candidate in `select_candidates` (curve untouched, so no peak disappears — the first version halved the curve and lost a Persona battle and the cut bonus). Evidence: labelled duds carry 3–7 cuts/min, play 0–2, in 13 of 15 files; voice gate keeps Persona's cut-ins and a scripted heist.
- `scoring.luminance_step()` in the continuous profile: |brightness 4 s after − 4 s before| (2 s gap) relative, ramp 0.2–0.4, discounts jolt and impact. Tunnels 0.25–0.45, results overlays 0.35–0.75, F1 crashes ≤ 0.13; the 2-s version killed the Fortnite light show, the 4-s windows let flicker average out.
- `scripts/eval-matrix.py`: every labelled recording in one table (returned, p@N, duds, recall, profile, fallback), 9 s from cache. BENCHMARK #2 row rewritten with per-genre numbers.

Measured (main e944151 → genres): totals action 65 → 68, duds 43 → 33. COD 0.80/2 → 0.90/1, Persona 5/0 → 5/0, BO2 0.50/4 → 0.70/2, GT1 0.50/5 → 0.70/1, F1 0.20/8 → 0.30/7, Dead Space 0.50/4 → 0.50/2, Cyberpunk 0.10/6 → 0.20/5; GTA IV 0.80/0 unchanged. Costs: Fortnite event 8 → 6 returned (0.60 → 0.30, 0 duds), GTA 5 free roam 0.30 → 0.20 (1 dud both), Madden 6 → 7 duds, GTA 5 story 1 → 2 duds (the intro fell to #10, "mission passed" is not a static card).

Relabelled (coordinator): F1 "race classification appears" ×7 and GT1 "New Record results" → dud; 11 new F1/GT1 spans from the new picks.

Still failing and why: sports and fighting (no audio onsets → fallback ranking, plays ungradeable from stills, presentation cards fill the list); results overlays with no brightness change and "awaiting race completion" replay cameras (no generic signal); GTA free-roam cruising vs crash (impact band unreliable on 640x360 AAC); SMB3/Hearthstone return 2/10 honestly.
