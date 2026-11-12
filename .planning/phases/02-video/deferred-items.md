
## From 02-03 (inputs) — 2026-11-12
- With 02-02's uncommitted scoring (min_score floor 0.35, edge rule) three existing tests fail independent of 02-03: test_e2e::test_music_bed_still_finds_bursts (172 s burst below floor), test_e2e::test_lobby_cards_are_never_picked, test_render::test_follow_crop_tracks_moving_square (40 s fixture is all "edge": 0 clips). Verified: signals from the segmented analysis are bit-identical to HEAD; the failures move with scoring.py. Owner: 02-02.
- Sessions (many files) disable the intro/outro edge rule (edge_s=0) because it assumes one recording; the right fix is a per-file edge (first/last 30 s of each source) inside scoring.action_score. Owner: 02-02 / phase 4.
- Short-clip ranking among saturated loud bursts is decided by motion/smoothing noise (tanh z-score saturates): clip_4 (0.25 amp) ranks above clip_2 (0.5 amp). A raw-dB tie-break for whole-file candidates would fix it.
- Multi-track mix uses amix default normalisation (sum / n): a lone track's burst is 6 dB quieter in the mix; loud_rel is relative so the ranking survives, but `normalize=0` with a limiter would be truer.
