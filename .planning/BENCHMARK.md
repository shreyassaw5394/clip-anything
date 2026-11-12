# BENCHMARK — "best in the world" (owner 2026-11-12), measured, not claimed

Every dimension has a number, a rival to beat, and a status. Any dimension we lose becomes the next work. Re-run before launch and after every tuning pass.

| # | Dimension | Best rival today (research) | Our target | How we measure | Status |
|---|---|---|---|---|---|
| 1 | Finds action with NO speech | Eklipse (cloud, per-game); open-source: none game-agnostic | ≥ 90 % of human-marked action moments in top-10 on a 1-h GTA session; ≤ 1 dud (menu/loading/idle) per 10 | Labelled real footage: a human marks every "clip-worthy" moment; precision@10 / recall | ○ needs footage |
| 2 | Works on a game nobody has a profile for (GTA 6 day one) | VPCLIPS/auto-clipper: fail with no profile | Same scores on an unseen game as on GTA 5 | Run on 2 games never tuned on | ○ |
| 3 | Speed | auto-clipper ≈ 3–5 min per hour of video | ≤ 1 min analysis per hour of input on an M1/laptop; cached re-run < 5 s | timed runs, written in GRAPH numbers | ◆ audio 4 s/h; video pass pending |
| 4 | Zero setup | SupoClip: Docker + API keys; FunClip: torch; ClipsAI: HF token | `uvx clip-anything video.mp4` on a clean machine with only ffmpeg; first clip in < 2 min for a 1-h file | clean-VM / fresh-user test, timed | ○ phase 5 |
| 5 | Postable without editing | Opus "cuts late, skips the action"; speech-first tools cut mid-sentence | Build-up before every peak, ends at a quiet point, no two clips of one moment, no mid-kill cut, HUD-safe captions | Human review of 30 clips: % needing zero edits (target ≥ 80 %) | ○ |
| 6 | Crop that follows the action | Nobody (rivals follow faces) | Action stays in frame ≥ 95 % of frames; zero visible jitter; pan ≤ cap | synthetic moving-target test + human review on real footage | ◆ phase 2 |
| 7 | Hours-long VODs | Opus: credits per minute; clipforge: 10-min cap | 10-h file completes in bounded RAM (< 2 GB) | generated 10-h file, peak RSS | ○ |
| 8 | Robust inputs | Most tools choke on VFR/HEVC/HDR | OBS VFR, PS5/Xbox HEVC, HDR all produce correct, colour-right clips | fixtures + the owner's HDR clips | ◆ |
| 9 | Never fails silently | Hosted tools: opaque | Every degradation is one clear line + in report.json; one bad clip never kills a run | fault-injection tests | ◆ |
| 10 | Privacy | Hosted = upload your footage | Zero network (Whisper download opt-in only) | network sniff during a run | ◆ |
| 11 | Polish of the CLI | — | Progress with time estimates, a final table, colours, helpful errors; feels like a product | screenshot review + 3 fresh-user runs | ◆ |
| 12 | Facecam + captions | Eklipse/Opus do it (cloud) | Auto facecam stack; word-synced captions only when speech; both off cleanly when absent | fixtures + real streamer VOD | ○ phase 3 |

Launch rule: 1, 3, 4, 5, 9, 10, 11 must be green on Sunday. 2, 6, 7, 8, 12 green or honestly listed in the README as "coming".
