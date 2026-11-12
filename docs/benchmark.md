# How the defaults were tuned, and what was measured

Numbers below were measured on 2026-11-12 on an M1 Max laptop with `scripts/eval.py`. Anything not listed here has not been measured.

## The two recordings

The defaults were tuned on two openly licensed recordings (public domain and CC BY) with hand-labelled moments:

- A 40-minute Call of Duty 2 multiplayer match, 720p30, 19 labelled spans. Bursty FPS action.
- A 74-minute Persona 3 opening, 480p60, 33 labelled spans. A turn-based RPG with almost no bursty action, chosen as the hard case.

Two games is a small set. The scorer has no per-game code, so it should transfer, but it has not yet been scored on a third, unseen game.

## Two mechanisms do most of the work

- **Static-card penalty** (`w_card`): a window whose proxy frames are nearly still and full of text strokes (lobby, menu, loading, title card) is multiplied by `1 - 0.8 * card`. Loud menu sounds do not rescue it.
- **Action bar** (`min_evidence`, `--min-score`): every candidate is measured against fixed levels taken from real footage, not against the rest of the file. Audio must be sharp *and* loud (onset plus dB over the rolling baseline) and the picture must show sustained whole-frame motion around the peak. A candidate needs both; one group alone does not clear the bar. Below the bar nothing is returned, which is why `--count` is a maximum. `--min-score 0` turns the bar off and ranks the file against itself.

## Results

| Recording | Asked | Returned | Duds (menu / text / idle) | Precision@10 |
|---|---|---|---|---|
| Call of Duty 2, 40 min | 10 | 10 | 1 (a round-start text card with loud onsets and seven cuts) | 0.80 |
| Persona 3, 74 min | 10 | 5 | 0 (all five are Tartarus battles) | 5 of 5 returned are real |

Before tuning, the same files gave 3 and 8 duds in the top 10.

Recall on the long match is the weak spot: 8 of the 19 labelled moments made the top 10. Raising `--count` or lowering `--min-score` surfaces more.

Known misses: a cutscene explosion with music but no audio onset stays below the bar (by design, it has no audio evidence), and 45-second windows in a turn-based game sometimes include a result screen.

## Speed and memory

- Analysis alone (no render): 26-47 seconds per hour of footage on the two files above. Across 480p-1080p30 input the range is about 25-55 s per hour; it is decode-bound.
- 1080p60: roughly 100 s per hour, above the one-minute goal.
- Render: about 3 s per 17 s 720p clip.
- A 1-hour file: analysis in well under a minute; cached re-runs in a few seconds.
- Memory: a 3-hour file peaked at 363-384 MiB RSS across runs. A 10-hour file has not been run.

## What has not been measured

- A third game, or any game with a different action profile (racing, sports, fighting games).
- Captions and facecam detection on a real streamer VOD with a webcam (verified on fixtures and the two recordings only).
- The `--vision` pass against a real Ollama model.
- A human review of a batch of clips for "postable without edits".
- Windows.

## Reproduce

`scripts/eval.py` takes a recording and a labels file and prints precision, recall and the dud count for a run. `scripts/make_test_video.py` builds the synthetic fixtures the test suite uses (six audio bursts, four motion bursts, a known answer).
