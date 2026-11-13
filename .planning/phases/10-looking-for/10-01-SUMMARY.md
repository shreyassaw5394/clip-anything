# 10-01 Summary — "What are you looking for?" + more things to look for — 2026-11-13

Branch `looking-for` off main, PR #22. Commits: d9ec5fa signals/scoring/presets · 571d376 brief (CLI + app) · 1631a62 tests + docs · + this docs commit. Full pytest green (13 new tests, stub providers + synthetic bursts/fades/streaks), ruff clean, Playwright shots of the chips/brief block in both states, 0 console errors.

Built:
- **Brief**: `--ai-brief` / app text box under "What are you looking for?" (needs AI on). `ai_prompts.clip_prompt(brief=)` asks for `match` 1–10 + one-line `matches`; `Reranker(brief=)` → 5N candidates (cap 40), final 0.6 action + 0.4 AI (mean of excitement and match; match alone for text models); `features.ai.match/matches`, `report.ai = {brief, provider, model, status, asked, answered, reranked}`; sidecar + clip card show "Matches: …". Empty brief = old behaviour (3N, 0.7/0.3). Brief bounded to 300 chars, quotes neutralised.
- **Presets / chips**: `config.PRESETS` (shooter, racing, sports, horror = calm but tense, story, funny) as a config layer file < preset < CLI; `--preset`; app chips Fights · Funny · Big plays · Crashes · Calm but tense (`JobRequest.preset`), `scoring.preset` recorded in the report.
- **Signals**: `audio.centroid/flat/mod` → `audio.voice_react` (voice reaction) and `audio.stinger` (tonal level jump); `video.bright/bmin` → `video.black`, `video.fade`; fade = preferred clip END snap (`snap.end: "fade"`); **streak merge** (bursts ≤ 25 s apart, ≥ 0.6 of the peak, bounded at the midpoint to the neighbouring peak; 3+ bursts that do not fit may run to 60 s; `components.streak`, reason line "N bursts in a row"). Extractor versions audio 2 / video 5 (cache re-analyses once).
- eval.py `--preset --cache-dir --scoring --no-sheet`; BO2 labels (26 spans from the top-30 sheet, midpoint frames only) under the footage folder.

Measured (default preset; before = origin/main on the same cache):
| File | before | after |
|---|---|---|
| COD2 40 min | p@10 0.80 · duds 1 · recall 8/19 | 0.80 · 1 · 8/19 (same set; two adjacent clips of the match end) |
| Persona 3 74 min | 5 of 10 returned · 0 duds · 4/7 | 5 · 0 · 4/7 |
| BO2 6 h campaign | p@10 0.40 · duds 3 (cutscenes) · 4/18 | 0.40 · 3 · 4/18 |
Speed: BO2 6.13 h analysed alone in 100 s = 16 s/h (target ≤ 60). Presets: horror on COD 0.80 / 0 duds, story on COD 0.70 / 1.

Earned / dropped (per-signal ablation, each alone vs all off): no single bonus changed any top-10 set on any file, so **w_voice, w_fade, w_stinger default to 0** (presets use them; report + reason line always show them). `voice_react` fires on cutscene dialogue as hard as on a shout (BO2 cutscenes 0.4 mean, 1.0 max) — it is a voice detector, named so. **Dropped: big text flash** (thin-stroke share of the centre third: gameplay median 0.10–0.13 vs 0.22 on the known round-start card, 0.38 on a cutscene — it measures moving edges, not text). **Dropped: slow-mo** (not detectable from a 5 fps proxy). Streak merge measured neutral on precision/duds; the first version (unbounded chains) made every window 60 s and lost a Persona clip, hence the midpoint bound.

Weak / unverified: real-model behaviour of the brief (stub providers only; no Ollama/keys here); BO2 labels are single midpoint frames; no laughter-labelled footage, so voice_react is validated on synthetic bursts only; the brief is not remembered in Recent (server.py untouched, robust-run owns it).
