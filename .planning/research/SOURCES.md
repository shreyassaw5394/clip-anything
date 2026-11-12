# SOURCES — how people end up with a gameplay recording (researched 2026-11-12)

Legend: **V** = stated by at least one cited source; **V?** = single/third-party or conflicting source; **I** = inferred (my judgement, no source). Nothing downloaded; no file was probed with ffprobe, so every codec/fps cell is from articles, not from real files. Verify with the owner's real clips (`ffprobe -show_streams`) before trusting any **V?/I**.

Headline for the design: the owner's premise ("1-10 h file") is only true for PC/OBS, capture cards and stream VODs. Consoles built-in capture produce **many short clips** (30 s default). Clip Anything must be a **session tool (folder in, ranked clips out)**, not only a single-file tool.

## 1. Per-source table

| Source | Container / codec | Typical length | fps mode | HDR | Audio tracks | Reaches a PC via | Share of target users (I) |
|---|---|---|---|---|---|---|---|
| PS5 Create button | **WebM default**, MP4 optional (V, androidcentral/gamesradar/Wikipedia). Creator report: 4K60 HDR = WebM with **VP9 + Opus** (V?, letsplayindex). HEVC not found in any source | Last 15 s to 1 h selectable, **default 30 s** (V, gamesradar/thesixthaxis); 1 h is the 4K-to-storage cap per tweaktown headline (V?) | Unknown, assume VFR-ish (I) | 4K HDR possible; WebM+VP9 HDR needs metadata kept (V?, Google VP9 HDR doc: ffmpeg cannot write SMPTE2086 into WebM/MKV) | Single mixed stream; party chat/mic inclusion is a console setting (I) | Copy to USB (exFAT/FAT32 only; >4 GB fails on FAT32) (V, thesixthaxis/slashgear); PS App/cloud upload (V? not detailed) | PC+console players are ~44% of players but console recording is mostly clips: ~25% of target users (I) |
| Xbox Series X\|S | **MP4**, H.264 or HEVC (V, Xbox devdocs XAppCaptureVideoEncoding enum; windowscentral) | Retroactive last **30 s** default; longer needs 1080p SDR / USB / card (V?, windowscentral/insights.gg; "10 min" figure unconfirmed) | Unknown (I) | HDR only if console output is 4K with HDR on (V, windowscentral); 4K clips eat space | Single mix (I) | Xbox app / Xbox Network upload then download as .mp4 (V? old guide); OneDrive path not confirmed; USB export (I) | in the ~25% console figure |
| Nintendo Switch / Switch 2 | MP4 (I) | **30 s only**, Switch 2 unchanged (V, Nintendo Today via notebookcheck/nintendowire May 2025); GameChat keeps last 3 min for safety, not exportable (V, nintendosoup) | I: CFR 30/60 | No | Mixed | microSD/USB, Smart-Device transfer, or capture card for anything longer (V?) | <5% (I); 30 s clips are too short to rank |
| Capture card (Elgato 4K60, HD60 X, AVerMedia) | Elgato Studio: **HEVC auto-selected when HDR is on, H.264 not offered; AV1 optional; 10-bit BT.2020** (V, elgato.com). Container not stated; mp4 typical (I) | Hours, one long file | CFR from the card (I), can be VFR in OBS | Yes; tone mapping only affects preview, **file stays HDR** (V, elgato.com) | Usually 1 stream; OBS can split game/mic (I) | Direct on the PC (it is the PC) | ~15% (I): the console-and-long-session route, important for GTA 6 |
| PC: OBS | **MKV by default for years; Hybrid MP4 newer** (V?, third-party obs-versions.com says Hybrid MP4 default from OBS 32); remux File > Remux (V, OBS forum) | Hours | Constant by default but **VFR files do occur** (V? the user complaints; no OBS source for the VFR mechanics) | SDR mostly; HDR via HEVC/AV1 in 10-bit (I) | **Advanced mode: up to 6 tracks, mic on its own track** (V, obs forum); Simple mode = 1 mixed track (I) | Local disk | ~30% of long-session users (I; "~60% of streamers use OBS" is a low-quality blog estimate, V?) |
| PC: NVIDIA ShadowPlay / NVIDIA App | MP4; H.264 baseline, HEVC, AV1 on RTX 40/50 (V?, nvidia.com AV1 news; recmaster) | Instant Replay up to **20 min** (V?, digitaltrends/recmaster; other sources say 15/30), full recording hours | I: CFR | 4K HDR 60 (nvidia UK page) vs 120 (G2) conflict (V?) | Game audio plus optional mic mixed into one (I) | Local disk | ~25% (I) |
| PC: AMD ReLive / Xbox Game Bar | Game Bar: **MP4** to `%UserProfile%\Videos\Captures` (V, elevenforum); max length **30 min/1 h/2 h default/4 h** (V). ReLive: MP4 (I) | Up to 2 h by default | VFR possible (Game Bar, I) | Game Bar HDR capture is a separate setting (I) | Mixed (I) | Local disk | ~10% (I) |
| PC: Steam Game Recording (2024+) | Background recordings are stored in **Steam's own raw timeline format, not MP4**; MP4 only after "create clip / export" (V, gamedeveloper/shacknews/primagames). Folder set in Settings > Game Recording (V); default path unverified | Background buffer overwritten when disk limit hit (V); clips of any length | I | I | I | Export dialog | ~5-10% (I), growing; Steam Deck included |
| Medal / Outplayed / Overwolf | MP4 local clips (I; not researched) | 15-120 s clips | I | I | I | Local folder | ~10% (I), mostly **many short clips** |
| Twitch VOD | HLS chunks (.ts) served, download tools remux to mp4 (I; not covered by sources found). Retention: **60 d Partner/Turbo/Prime, 14 d Affiliate, 7 d others**; Highlights/uploads share a 100 h store and persist (V, streamscheme/PC Gamer, 2022-2025) | 4-12 h | Source stream CFR (I) | No | One mixed track (I) | Creator dashboard Export, or downloader tools | ~15% (I): streamers; VOD is a re-encode of their own live output |
| YouTube / Kick VOD | mp4/webm via downloaders (I; not researched) | hours | I | I | I | downloader | in the Twitch figure |
| Phone: iPhone screen record | Control Center recorder saves **.mp4**, not .mov (V? single source, videoproc/fitune conflict); 60 fps is an average (**VFR**) (V, Adobe community) | minutes | **VFR** (V) | iPhone HDR for camera; screen recording HDR unverified | App audio + optional mic mixed (I) | AirDrop/iCloud/cable | ~10% for mobile games (I) |
| Phone: Android / Steam Deck | Steam Deck uses Steam Game Recording (see above) (V, steamdeckhq); Android recorders mp4 (I) | minutes | I | no | I | cable/cloud | in the above |
| GoPro / drone / dashcam | GoPro: MP4 HEVC, HERO11+ HDR10 (PQ) (V, partial); **chapters**: files split at 4 GB (older) or 12 GB (newer), named GOPR0001 / GP010001 / GP020001 (V, GoPro Labs, havecamerawilltravel); lossless join with ffmpeg concat, may lose telemetry (V, jeffgeerling) | Hours across chapters | CFR typically (I) | HLG/PQ 10-bit (V partial) | 1 stereo mix, wind-noise (I) | SD card reader | Out of scope for launch; cheap to support if folder+HDR work (I) |
| Podcast / call recordings | Zoom/Meet mp4, speech-first | Hours | VFR (screen-share) (I) | no | multi or single | cloud download | Not our case: no action energy; we would pick loud-laughter, not action. Note limit in README (I) |

Player-base context (V, Newzoo 2025 via pocketgamer.biz/gamedevreports): 3.578 B players; mobile 2.985 B, PC 936 M, console 645 M (overlapping). Not a measure of who records long sessions.

## 2. Verified findings that change the design
1. **PS5 defaults to 30 s clips; WebM unless the user switches to MP4** (V). Most PS5 users will hand us dozens or hundreds of 30 s files, probably WebM/VP9 or MP4 depending on setting. A 4K HDR PS5 clip may be VP9 Profile 2 (10-bit) in WebM (V?).
2. **Xbox is the same story**: 30 s retroactive, MP4 H.264 or HEVC, HDR when the TV is HDR (V).
3. **Switch is capped at 30 s** (V, May 2025). Per-clip ranking is meaningless; support the folder but expect "take them all".
4. **Elgato HDR file stays HDR 10-bit HEVC BT.2020; only the preview is tone-mapped** (V). Without our own tone map the burned-in 9:16 clip will look grey/flat.
5. **OBS multi-track is real**: Advanced output records up to 6 tracks; MKV is the crash-safe default recommended on the forum; remux to MP4 is lossless (V). Some editors then show tracks wrongly (V?).
6. **Steam background recordings are not playable files** (V). Users must export a clip first; we cannot read the raw format. State this in README; no work needed.
7. **Twitch retention is 7/14/60 days** (V); users with an old VOD usually already downloaded it with a third-party tool, so we get mp4/ts from tools, not from Twitch itself (I).
8. **GoPro splits long takes into chapters at 4/12 GB** (V): same "many files = one session" problem in a different sport.

## 3. What breaks naive tools (and the fix)
| Symptom | Where it happens | Cause | Fix in Clip Anything |
|---|---|---|---|
| A/V drift or wrong cut times | iPhone (V), OBS/Game Bar (I), PS5 (I) | VFR: nominal 60 is an average | Never trust container fps. Analyse on audio timeline plus `-vsync cfr` proxy at 5 fps; cut with `-ss` after input and re-encode (already planned) |
| Flat grey colours / washed out | Elgato HEVC HDR, PS5 HDR, ShadowPlay HDR, GoPro, iPhone (V) | PQ/HLG BT.2020 10-bit encoded to SDR without tone map | Detect `color_transfer` smpte2084/arib-std-b67; tone map `zscale=t=linear:npl=100, tonemap=hable (desat=0), zscale=bt709, yuv420p` (V, ffmpeg list). Needs a zimg build; fall back to `tonemapx`/`colorspace` if `zscale` missing (check `ffmpeg -filters`) |
| HDR tags missing (looks flat) | PS5 WebM/VP9, remuxed MKV | HDR metadata lost on remux (V, Google VP9 doc) | If 10-bit and BT.2020 primaries but transfer unspecified, assume PQ and warn in report |
| WebM won't open in some decoders / NLEs | PS5 (V?, DaVinci workaround is remux to MKV) | VP9 10-bit in WebM | ffmpeg reads it fine; just use the demuxer, warn if libvpx-vp9 decoder is missing |
| Seek is slow or fails | MKV with no cues, Twitch .ts | no index, truncated recording after crash | Prefer input seeking with `-ss` before `-i` for analysis only on proxy; if duration unknown run a cheap `-c copy` remux into a temp mp4 (I) |
| Only a mic or only game audio | OBS multi-track, Elgato | game and mic on different tracks | See 4(b) |
| Silence | Switch-docked, capture cards with no audio, muted | no audio stream | Visual-only mode (weights re-normalised); say so in report |
| Many short files | PS5, Xbox, Switch, Medal | clip-by-clip | See 4(a)/(e) |
| 4K / high bitrate | Elgato, PS5 4K, GoPro 5.3K | decode-bound | Hardware decode (VideoToolbox) for the 5 fps proxy (BENCHMARK #3 already flags 1080p60 as decode-bound) |
| Vertical or 4:3 sources | iPhone screen record, Switch handheld 16:9 only, older 4:3 | crop maths assumes 16:9 | See 4(c) |
| Tiny `.ts` chunks | Twitch HLS fragments | segment files | Sort naturally, concat demuxer (I) |

## 4. Required behaviour
**(a) Folder / many files = one session.** Accept a file, a folder or several paths. Sort by (container `creation_time` -> filename natural sort -> mtime), because PS5/Xbox filenames embed game name and date (I) and GoPro chapters are `GOPRnnnn`, `GPmmnnnn` (V). Treat files as one timeline only when gaps are small or they are chapters; otherwise score within a global pool but clip each from its own file (no stitching across files). Normalise the score over the whole pool so a quiet 30 s clip is not inflated. Keep the report per file.
**(b) Audio track.** Default: use all audio streams mixed for the analysis (energy from `amix`), because game audio is where the action is and a loud mic must not dominate. If more than one track: per-track loudness stats, drop tracks that are near silent, and prefer the track with the most dynamic range (highest 95th/50th percentile ratio) as the "game" track; give the mic track speech-only bonus use. For render, keep game plus mic mixed, with `--audio-track N` and `--audio mix|game|first` overrides. (I, no source for what users prefer.)
**(c) Vertical / odd aspect.** If height >= width, skip the 9:16 crop and just pass through at 1080x1920 (already vertical); 4:3 uses the same follow-the-action crop with a smaller window; ultra-wide (21:9) fine. (I)
**(d) HDR.** Detect, tone map for both the proxy and the final render, mark `hdr_tonemapped: true` in report.json. (V for the symptom, I for the exact chain.)
**(e) 30 s clip collections.** Score each file as one candidate window first (it was already chosen by the player as clip-worthy); then, if a clip is longer than `--max`, run normal peak picking inside it. Rank across files, cap at N, never emit two clips of the same file unless it is longer than 90 s. Flag "too short to improve: ranked, trimmed to the peak" in report. (I)

## 5. Prioritised requirements and coverage (estimates are I unless marked)
| # | Requirement | Covers | Why |
|---|---|---|---|
| 1 | Single file, any of mp4/mkv/mov/webm; HEVC/H.264/VP9/AV1 decode; VFR safe | ~85% | OBS, ShadowPlay, Game Bar, capture cards, PS5, Xbox |
| 2 | Folder / multi-file session with time sort | ~45% | PS5, Xbox, Switch, Medal, GoPro chapters |
| 3 | HDR (PQ/HLG, 10-bit) tone-map | ~25% | PS5/Xbox 4K HDR, Elgato HDR, ShadowPlay HDR, iPhone, GoPro |
| 4 | Multi-audio-track handling, no-audio fallback | ~25% | OBS Advanced, capture cards, some muted clips |
| 5 | Short-clip pool ranking (30 s) | ~30% | PS5, Xbox, Switch (V default) |
| 6 | Vertical/4:3 input pass-through | ~10% | iPhone screen records, 4:3 retro games |
| 7 | 4K/high-bitrate speed (HW decode) | ~25% | BENCHMARK #3 |
| 8 | Indexless mkv/.ts/crashed files | ~5% | crashed OBS, Twitch chunks |
| 9 | Action cam chapter joining | ~5% | stretch |
| 10 | Speech-first content (podcast/call) | 0% target | explicitly out; state in README |

Coverage numbers are overlapping, not additive. The share column in section 1 has **no primary data**: I found no survey of how gamers record. Treat percentages as ranking hints. To firm them up, ask the Discord/launch thread "how do you record" (one poll) after launch.

## 6. Open questions (could not verify)
- PS5: real codec and VFR/CFR of MP4 vs WebM, whether mic/party audio is a separate track, and the 4K HDR metadata. Needs one real file from the owner (`ffprobe -v error -show_streams`).
- Xbox: current OneDrive/Xbox app download path and clip length cap on Series X.
- Medal/Outplayed/AMD ReLive/Kick/YouTube VOD specifics: not researched.
- OBS default container per version: only a third-party site says Hybrid MP4 from OBS 32.
- Twitch .ts vs mp4 export format: no source found.

## 7. Sources
- PS5 length options, default 30 s, WebM default: https://www.gamesradar.com/ps5-capture-settings , https://androidcentral.com/how-change-ps5-video-capture-formats , https://www.thesixthaxis.com/2020/11/11/ps5-copy-videos-screenshots-usb-how-to/ , https://www.tweaktown.com/news/76220/ps5-can-capture-up-to-1-hour-of-4k-gameplay-video-with-create-button/index.html
- PS5 VP9+Opus 4K HDR WebM remux: https://www.letsplayindex.com/video/davinci-resolve-1731-playing-vp9-and-mkv-on-macbook-air-G2zQ7NBD80k ; VP9 HDR metadata: https://developers.google.com/media/vp9/hdr-encoding?hl=en
- USB exFAT/FAT32: https://www.slashgear.com/1678295/playstation-format-as-exfat-meaning/
- Xbox: https://www.windowscentral.com/how-record-and-share-video-clips-xbox-series-x-xbox-series-s , https://devdocs.xbox.com/reference/system/xappcapture/enums/xappcapturevideoencoding , https://insights.gg/blog/how-to-clip-on-xbox
- Game Bar: https://www.elevenforum.com/t/change-max-recording-length-for-gaming-captures-in-windows-11.17924/
- Switch 2 30 s: https://nintendowire.com/news/2025/05/20/recordings-on-the-switch-2-seem-to-still-be-restricted-to-30-seconds/ , https://nintendosoup.com/the-last-3-minutes-of-every-gamechat-session-will-be-recorded-for-user-safety-on-switch-2/amp/
- Elgato HDR: https://www.elgato.com/explorer/products/capture/elgato-studio-hdr/
- OBS tracks/remux: https://obsproject.com/forum/resources/high-quality-recording-with-multiple-audio-tracks-in-advanced-output-mode.1388 , https://obsproject.com/forum/threads/multiple-audio-tracks-remuxing-settings.175177/ , https://obs-versions.com/blog/obs-mkv-vs-mp4-hybrid-mp4
- NVIDIA: https://www.nvidia.com/en-eu/geforce/news/nvidia-app-beta-update-av1-performance-tuning/ , https://www.recmaster.net/?p=1726
- Steam: https://gamedeveloper.com/pc/steam-debuts-new-game-recording-tool-in-beta-form , https://shacknews.com/article/142140/how-to-use-steam-game-recording , https://steamdeckhq.com/tips-and-guides/how-to-use-game-recording-on-the-steam-deck-all-features-explained/
- Twitch retention: https://www.streamscheme.com/how-to-store-your-twitch-vods/ , https://pcgamer.com/twitch-eliminates-save-forever-option-as-it-moves-to-improve-video-on-demand-service
- iPhone VFR: https://community.adobe.com/t5/premiere-pro-discussions/workflow-for-iphone-video/m-p/9334943 , https://forum.shotcut.org/t/iphone-video-which-settings-for-conversion/50964
- HDR tone map: https://ffmpeg.org/pipermail/ffmpeg-user/2021-March/052535.html , https://dev.to/masonwritescode/ffmpeg-hdr-to-sdr-tone-mapping-that-doesnt-look-washed-out-2026-24ie
- GoPro chapters: https://gopro.github.io/labs/control/chapters , https://www.jeffgeerling.com/blog/2021/how-join-multiple-mp4-files-gopro-ffmpeg/
- OBS share (weak): https://voxbooster.com/blog/streaming-software-statistics-2026 ; Newzoo: https://www.pocketgamer.biz/newzoo-global-games-market-set-to-hit-1888bn-in-2025
