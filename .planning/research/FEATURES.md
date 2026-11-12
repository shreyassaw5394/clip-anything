# Feature Research

**Domain:** Local, open-source gameplay/stream highlight clipping (long recording in, vertical clips out)
**Researched:** 2026-11-12
**Confidence:** MEDIUM. Vendor behaviour is mostly from vendor and competitor marketing pages (biased). Open-source behaviour is from READMEs fetched today (higher confidence). No Reddit threads were retrievable by the search tool; "user complaints" come from Trustpilot-derived summaries and review blogs. Gaps are listed in the last section.

Legend: **[V]** verified from a page fetched today, **[S]** search-result snippet only, **[I]** inferred / training knowledge, treat as LOW.

## Competitor Matrix

### Paid / hosted

| Tool | Input | How it finds moments | Output | Price (as reported, conflicting) | Lock-in / limits |
|------|-------|----------------------|--------|----------------------------------|------------------|
| **Eklipse** | Twitch/YouTube/Kick/Facebook stream or VOD link, cloud processed | Own blog: kill feed, eliminations, objectives, round transitions (downweighted alone); separated voice / game audio scoring; frame-level vision context for clip start/end; "action density"; continuity; chat only for strategy genre; voice command "Clip it" [V blog.eklipse.gg/streaming-tips/how-gameplay-intelligence-works-2.html]. Falls back to "general action detection, lower quality" for unsupported titles [V] | Clips in library; convert to 9:16 with captions/templates in Eklipse Studio; schedule to TikTok/Shorts/Reels; examples 6-22 s [V] | $24.99/mo or $179.99/yr on its own blog; older $19.99/$149.99; free AI clipping reportedly ended June 2026; free tier = watermark, 720p, 14-day expiry per other sources [S] | Cloud, account, subscription; clips expire on free tier |
| **Medal.tv** | Live capture on Windows (not VOD upload) | "Automatic Event Detection" per-game triggers, user toggles events and clip length; Windows only; full-session mode makes bookmarks not clips [S medal.tv/auto-clipping, support.medal.tv article 48001167701] | Clips in Medal cloud/editor | Unclear: $3.99, $5, $24.99/mo quoted by three third parties [S] | Needs Medal recorder running; supported-game list only |
| **Opus Clip** | Uploaded file or URL | Audio/speech: pacing, sentiment, hooks; 0-100 virality score [V twoaveragegamers.com OpusClip review]. Reviewer: "waits for speech pauses and cuts late, skipping the action"; misses silent clutch plays [V, secondary] | 9:16, captions, editor | Free 60 credits/mo w/ watermark, 3-day expiry; $15 (150 credits); $29 (300). 1 credit = 1 min of INPUT, so 3 h stream = 180 credits [V secondary] | Credits burn on input length; API Business-only |
| **Klap / Munch / Vizard** | Upload / URL | Transcript, sentiment, face tracking. Klap says best for speaking content; Munch has no gaming-specific logic [S, Eklipse-hosted comparisons, biased]. Vizard's own page claims it detects kills/skilled plays; Eklipse says dialogue only. Contradictory, unresolved [S] | 9:16, captions | Not verified | Subscription, cloud |
| **StreamLadder** | Twitch clip/VOD | Reported as a converter (webcam+gameplay layouts), not a detector: user finds the moment [S, Eklipse blog, biased] | 9:16 stacked facecam layouts | Not verified | Cloud |
| **Allstar.gg** | Supported-game match data / capture | Cloud-rendered clips from game data/demos for a small set of supported games; relationship to Overwolf events unconfirmed [S, Eklipse comparison, biased] | Highlights, full match, session | Not verified | Supported games only; not a universal recorder |
| **NVIDIA ShadowPlay Highlights** | Live capture in-game, NVIDIA GPU | Game-integrated kill/death/streak/win events through in-game settings [V-ish S: nvidia.com tutorial; pcgamer.com PUBG] | Video + screenshot, local files | Free with GeForce Experience | Per-game integration, NVIDIA GPU only; supported list old/unverified (2017-2018 sources) |
| **PS5 / Xbox native** | Console | PS5: trophy-triggered auto clip, 15 or 30 s only; manual "save recent" 15 s to 1 h [S playstation.com support, tomsguide.com]. Xbox: nothing found | Console-native files (16:9) | Free | Trophy moments only, not action; no vertical, no captions. Xbox unverified |
| **Powder.gg** | - | **Could not find reliable information** (search returned nothing relevant) | - | - | Not assessed |
| **Twitch clips/highlights** | Live/VOD | **Could not verify** native auto-detection; viewers/streamers clip manually [gap] | - | - | Not assessed |
| **Athenascope** | Twitch stream or OBS | Computer vision on gameplay for goals/wins/kills; launched 2019-02-05 with Fortnite, PUBG, Rocket League; free; $2.5M seed (First Round) [V finance.yahoo.com/news/xfire-creator-launches-athenascope-free-191900122.html] | Highlight reels | Free | **Why defunct: not found.** [I] Plausible causes: 3-game support list, per-game vision models, free with no revenue. Do not cite as fact |

### Open source

| Project | Signals | Stack / setup | Output | Where it fails |
|---------|---------|---------------|--------|----------------|
| **ClipsAI** (MIT) [V github.com/ClipsAI/clipsai] | Transcript (WhisperX) only; README: "designed for audio-centric, narrative-based videos" | WhisperX from git, pyannote needs HF token, libmagic, ffmpeg | `resize()` to 9:16 following the current speaker (diarization) | Useless on silent gameplay; token + multi-tool setup |
| **FunClip** (MIT, Alibaba) [V github.com/modelscope/FunClip] | ASR (Paraformer) text selection or LLM over transcript; optional TwelveLabs Pegasus for visuals | Python 3.12, PyTorch, funasr, Gradio UI, model downloads, LLM keys | Cuts by text/speaker; burned subtitles; no 9:16 mentioned | Speech-first, heavy deps, manual selection |
| **SupoClip** (AGPL-3.0, ~1.1k stars) [V raw README] | LLM picks 3-7 segments from transcript; hook/engagement scores | Docker Compose, Next.js + FastAPI + ARQ worker; AssemblyAI key + LLM key (local Whisper/Ollama path described but unclear) | Face-centred 9:16, word-synced captions, AI hook title | Network/keys by default, Docker stack, transcript-first, AGPL |
| **Clips Studio / "Clips Kitty"** (AGPL-3.0, Windows) [S] | Not verified; winget package "ClipsKitty" by ColinGPT9 [S, unconfirmed same project] | Windows app | Vertical clips | Not assessed; "Clips Kitty" name not confirmed as a repo |
| **Auto-clipper** (bendawg2010, MIT, 11 stars) [V] | Pixel/CV (muzzle flash, damage vignette, kill-feed colour), YOLOv11n for Arc Raiders only, War Thunder pixel rules, Whisper "clip it" voice triggers, optional paid Grok Vision | Flask UI, OpenCV, ultralytics, faster-whisper, yt-dlp; 1 h VOD in ~3-5 min pixel-only | 9:16 with gameplay 70% / webcam 30% presets; no captions | Per-game hand-built detectors; YOLO weights cover one game; public VODs only |
| **VPCLIPS** (MIT, Windows, Electron) [V] | Audio loudness + HUD OCR for kills/deaths/wins, 40+ per-game profiles, back-to-back kills merged | Electron, auto-downloads ffmpeg/yt-dlp/python; NVENC/AMF/QSV | 16:9, 9:16 or both; music montages; console via Remote Play capture | Windows only; unknown games get audio only; profile submodule upkeep |
| **EZClips** [S] | Kill-feed template matching + edge detection, merges consecutive kills; AI detection listed as future | Python | Clips | Per-game templates |
| **WatchDog** (GPL-2.0, Windows tray) [S] | Game audio for kills/clutch; native CS2, Valorant, OW2, Siege | Windows app | Clips | Four games |
| **clipforge** (LakshmiSravyaVedantham) [V dev.to post, Mar, year not shown] | PySceneDetect scene bounds + librosa mean RMS per scene, top 10; author: "audio alone gets you 80% of the way there" | FastAPI + Next.js, moviepy, Whisper base; upload limit 10 min | 3 formats incl. 9:16 + captions | 10-minute cap, no motion signal, loudness-only, crop logic undocumented |
| **Stream Clipper** (nirvagold) [S] | Audio + chat activity, no kill detection | Tauri/Rust | Clips | Needs chat data (VOD only), not local recordings |
| **pop1-auto-editor** [S] | Kill-sound waveform matching | Python | Timestamps | One game's sound effects |
| **Montage Maker / NiceShot AI** [S] | OCR of kill log; YOLOv8n on CoD BO6 | Python | Timeline / events | One game or kill-log games |
| **auto-editor** [I, not fetched] | Silence/motion thresholds to cut dead air | Python + ffmpeg | Edited same-ratio video | Not a highlight ranker; no 9:16, no captions |

**Pattern across open source [inferred from the table]:** every repo either (a) depends on speech, or (b) hard-codes per-game HUD/OCR/YOLO detectors. Only clipforge is a generic audio-energy approach, and it is a 10-minute web demo with no motion signal. Nothing found combines audio onset + loudness-vs-baseline + motion + scene cuts as a generic, game-agnostic, local CLI. Search was not exhaustive; absence is "not found", not "does not exist".

## Feature Landscape

### Table Stakes (postable without editing)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| 9:16 output, 1080x1920, H.264/AAC | TikTok/Shorts/Reels spec; every competitor outputs it | LOW | ffmpeg; veryfast CRF 20 per PROJECT.md |
| Clip length 15-45 s, tunable | Eklipse examples 6-22 s [V]; short-form norm | LOW | `--min/--max` |
| Clip starts before the moment, ends after | Eklipse users: "captures final kill but misses the buildup" [S Trustpilot summary] | MED | 60/40 build-up split; snap to quiet points/cuts |
| No watermark, no expiry, no quota | Free tiers of Eklipse/Opus watermark and expire clips [V/S] | LOW | Free by construction |
| Burned-in captions when speech exists | Opus/Eklipse/SupoClip all ship captions | MED | faster-whisper lazy; ASS word-sync |
| Webcam handling | StreamLadder/Auto-clipper/Eklipse layouts | MED | Facecam stack above gameplay |
| Non-overlapping, de-duplicated clips | Compilations of near-identical clips read as spam | LOW | Peak picking + NMS |
| Progress + ETA, clear errors | VPCLIPS shows ETA; Opus stalls "silently" are a top complaint [S] | LOW | rich progress; ffmpeg check with install help |
| JSON report with timestamps and scores | Lets users verify and tune | LOW | report.json |
| Accepts console captures / OBS files (mp4, mkv, mov) | Core input | LOW | PS5/Xbox files are plain mp4 |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Speech-independent action scoring (audio onsets, loudness vs rolling baseline, motion, cuts) | Opus/Klap/Munch/ClipsAI/FunClip/SupoClip are transcript-first [V/S]; silent clutch plays missed | MED | Core wedge. Weak spot: loud non-highlights (menus, music); mitigate with baseline + motion gate |
| Game-agnostic (no per-game profile) | Auto-clipper/VPCLIPS/WatchDog/EZClips need per-game detectors; Eklipse falls back to worse output off-list [V] | MED | Matters for GTA 6 on day one: no profile exists yet |
| Fully local, no account, no network | Eklipse/Opus/SupoClip default are cloud/keyed | LOW | Privacy story is also a legal simplifier |
| One command, `uvx clip-anything video.mp4` | ClipsAI, FunClip, SupoClip, Auto-clipper need multi-step setup [V] | LOW | No torch at import |
| Hours-long VOD in minutes on CPU | clipforge caps at 10 min [V]; Auto-clipper ~28x realtime pixel-only is the benchmark [V] | MED | Analyse 16 kHz mono + 320px/5 fps proxy; need to beat or match ~3-5 min/hour |
| Action-following crop (smoothed centre of motion) | ClipsAI follows speaker; SupoClip centres face [V]. Nothing found follows action | HIGH | Jitter is the failure mode; smooth + dead-zone |
| Facecam auto-detect (static corner + face) | Auto-clipper requires manual layout presets [V] | MED | Opt-in to avoid false stacks |
| Tunable weights via config file | No competitor found that exposes scoring | LOW | Needed for GTA 6 tuning |
| Optional local vision re-rank + title via Ollama | Eklipse vision is cloud; Auto-clipper's vision is paid Grok [V] | MED | Must degrade silently |
| Library-first `pipeline.run()` | Enables later hosted wrapper | LOW | |
| Console-friendly: runs on captures from PS5/Xbox with no console API | Native console auto-capture is trophy-only [S] | LOW | Works on user-supplied files |

### Anti-Features

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Per-game HUD/OCR/YOLO detectors | Higher precision per game (Auto-clipper, VPCLIPS) | Maintenance treadmill; none exist for GTA 6; Athenascope's 3-game list is a cautionary tale [I] | Generic signals; optional later plug-in hook |
| Transcript-first selection | Easy with Whisper + LLM | The exact failure of Opus et al. | Speech as bonus weight only |
| Cloud LLM / API keys | Better titles | Breaks local/free/one-command promise; SupoClip needs AssemblyAI [V] | Optional Ollama |
| Posting/scheduling to TikTok/Shorts | Eklipse/Opus do it | OAuth, API terms, accounts; out of scope | User posts the files |
| GUI/web UI in v1 | Auto-clipper, FunClip, VPCLIPS have one | Weekend timeline; setup pain moves to the UI | CLI + report.json |
| Live-stream/live-capture mode | Medal/ShadowPlay/VPCLIPS | Needs per-OS capture; different product | Post-hoc files only |
| Virality score / "trend" claims | Opus 0-100 | Unfalsifiable; marketing | Show raw signal scores in report |
| Credits / quotas / accounts | - | Top complaint pattern | None |
| Music montages, stock B-roll, emoji overlays | VPCLIPS/SupoClip | Licensing risk (music), scope | Skip |
| Chat-spike signal | Stream Clipper, Eklipse (strategy genre) | Needs chat logs; not present in local files | Defer; optional JSON import in v2 |
| Reprocessing "by game title" selector | Eklipse supported-games model | Implies support list | Auto only |

## What Users Hate (with sources)

| Complaint | Tool | Source | Strength |
|-----------|------|--------|----------|
| Clips "unusable"; streams not processed; "waited days"; hours of processing | Eklipse | Trustpilot pages via search summary (trustpilot.com/review/eklipse.gg) | [S] summary, Trustpilot flagged Eklipse for review solicitation |
| Captures final kill, misses buildup | Eklipse | same | [S] |
| Poor on Just Chatting/strategy; PvP better than PvE | Eklipse | same; own blog admits fallback quality for unsupported titles [V] | [V]+[S] |
| Inconsistent captions, esp. non-English | Eklipse | Trustpilot summary | [S] |
| Free tier: 720p, watermark, 14-day expiry, queue | Eklipse | review sites; Eklipse help page confirms watermark on free [S] | [S] |
| Cluttered / clunky UI | Eklipse | twoaveragegamers.com, Trustpilot summary | [S] |
| Cuts late, skips the action; picks talky segment over multi-kill | Opus Clip | twoaveragegamers.com/opusclip-review-2026-great-tool-wrong-hype-for-gamers/ | [V], single reviewer |
| Credits charged on input minutes; 3 h stream = 180 credits; renewal/cancellation charges | Opus Clip | same; ssemble.com, dailyaifixs.com pricing posts | [V]+[S] |
| Videos stall or fail silently; poor support | Opus Clip | eesel.ai, G2/Trustpilot/Reddit per a summary | [S] (Reddit not directly seen) |
| Needs HF token, WhisperX, pyannote | ClipsAI | github.com/ClipsAI/clipsai | [V] |
| Docker stack plus AssemblyAI + LLM keys | SupoClip | raw README | [V] |
| Windows-only, per-game | Medal, VPCLIPS, WatchDog | medal.tv support, repo READMEs | [V]/[S] |
| Manual layout drawing; public VODs only | Auto-clipper | README | [V] |

**Not found:** direct r/Twitch, r/streaming, r/VideoEditing, Steam or Discord threads, app store reviews. Search tool did not return them. Before finalising positioning copy, a manual pass of those is recommended.

## Gap Table (what Clip Anything should own)

| Gap | Who comes closest | Their shortfall | Clip Anything position |
|-----|-------------------|-----------------|------------------------|
| Action with no speech, any game | Eklipse (cloud, game-aware), clipforge (audio only) | Eklipse: cloud, paywall, off-list quality drops; clipforge: demo, 10 min cap | Core |
| Fully local + one command | Auto-clipper (local, Flask UI + weights) | Multi-dep install, per-game | Core |
| Hours-long VOD | Auto-clipper (~28x realtime pixel-only) | Needs per-game pixel rules | Core; benchmark ~3-5 min/h on CPU |
| Facecam stacking, automatic | StreamLadder/Auto-clipper presets | Manual layout | Auto-detect, opt-in |
| Action-following 9:16 crop | None found | ClipsAI/SupoClip follow faces/speakers | Differentiator, highest risk |
| Tunable scoring | None found | Closed scoring | Config file |
| Day-one coverage for a brand-new game (GTA 6) | None | Profile/model-based tools need training or templates | Generic signals |
| Honest report of why each clip scored | None found | Virality score opacity | report.json per-signal |

## Feature Dependencies

```
ffmpeg check ──> proxy extraction (16 kHz audio, 320px/5 fps)
                     └──> per-0.5 s signal windows ──> normalise+weight ──> peak picking
                                                                              └──> window build-up/snap/dedupe/clamp ──> render
render ──requires──> crop path (motion centre, smoothed)
facecam detect ──enhances──> render (stack layout)  [conflicts with action crop if facecam overlaps; crop gameplay region only]
captions ──requires──> speech detection ──requires──> faster-whisper (optional)
Ollama re-rank ──enhances──> peak list (optional, silent fallback)
library pipeline.run() ──requires──> no global state (applies to every box above)
```

## MVP Definition

### Launch With (v1, Saturday night)
- [ ] One-command CLI to `./clips/` + report.json (core promise)
- [ ] Audio + motion + cut scoring, peak picking, build-up windows (the wedge)
- [ ] 9:16 render with fades, centre-of-motion crop with smoothing (even a simple version beats centre crop)
- [ ] Config-file weights (needed to tune on GTA 5 now, GTA 6 later)
- [ ] Synthetic video test: injected bursts are picked
- [ ] README: how it differs from transcript clippers, with measured speed

### Add After Validation (v1.x)
- [ ] Word-synced captions when speech exists (MED, uses lazy faster-whisper)
- [ ] Facecam auto-detect and stack
- [ ] Ollama vision re-rank and titles
- [ ] Optional game plug-in hook for HUD cues

### Future (v2+)
- [ ] Chat-log JSON import as extra signal
- [ ] Hosted wrapper around `pipeline.run()`
- [ ] Learned weights from user keep/discard feedback

## Feature Prioritization Matrix

| Feature | User Value | Cost | Priority |
|---------|------------|------|----------|
| Action scoring + peaks | HIGH | MED | P1 |
| One-command CLI, local | HIGH | LOW | P1 |
| 9:16 render + fades | HIGH | LOW | P1 |
| Action-following crop | HIGH | HIGH | P1 (simple first, smooth) |
| Config weights | MED | LOW | P1 |
| Build-up windows, dedupe | HIGH | MED | P1 |
| Captions | MED | MED | P2 |
| Facecam stack | MED | MED | P2 |
| Ollama re-rank | MED | MED | P2 |
| GUI, posting, live mode | LOW | HIGH | Skip |

## Sources

Fetched and read (higher confidence):
- https://blog.eklipse.gg/streaming-tips/how-gameplay-intelligence-works-2.html (vendor)
- https://www.twoaveragegamers.com/opusclip-review-2026-great-tool-wrong-hype-for-gamers/ (review blog)
- https://finance.yahoo.com/news/xfire-creator-launches-athenascope-free-191900122.html (2019-02-05)
- https://github.com/ClipsAI/clipsai, https://github.com/modelscope/FunClip, https://raw.githubusercontent.com/FujiwaraChoki/supoclip/main/README.md
- https://github.com/bendawg2010/Auto-clipper, https://github.com/verticalhost/VPCLIPS
- https://dev.to/lakshmisravyavedantham/i-built-an-ai-that-turns-raw-gameplay-into-tiktok-youtube-and-trailer-clips-automatically-373

Search snippets only (verify before quoting):
- https://medal.tv/auto-clipping, https://support.medal.tv/support/solutions/articles/48001167701
- https://www.nvidia.com/en-us/geforce/news/shadowplay-highlights-tutorial, https://www.pcgamer.com/pubg-kills-can-now-be-instantly-recorded-with-nvidia-shadowplay/
- https://www.playstation.com/en-ae/support/games/capture-ps5-gameplay-screenshots, https://www.tomsguide.com/news/how-to-disable-ps5-trophy-videos
- https://www.trustpilot.com/review/eklipse.gg, https://eklipse.gg/compare/ (vendor-authored comparisons, biased)
- https://github.com/corp14x3/EZClips, https://github.com/nirvagold/stream-clipper, https://thrtn70.github.io/WatchDog/
- https://www.ssemble.com/blog/opus-clip-pricing-2026

## Gaps to Close Later
- Powder.gg, Allstar internals, Twitch native clipping, Xbox capture, Vizard/StreamLadder detection: not verified.
- Athenascope shutdown reason: not found. Treat as unknown.
- Official pricing for Eklipse, Medal, Opus: three-way conflicting; check live pages.
- Reddit/Steam/Discord/app-store voices: not retrieved.
- auto-editor and ClipsAI recent commit dates: not checked.

---
*Feature research for: local gameplay highlight clipping*
*Researched: 2026-11-12*
