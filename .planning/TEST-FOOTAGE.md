# Test footage for tuning the detector (local only)

Status 2026-11-12: a scan of this Mac found no gameplay recordings (only unrelated personal video, screen recordings and iPhone HEVC HDR clips). Owner must supply GTA 5 footage.

## What we need
1. One long GTA 5 session, >= 30 min, mixing action (chases, crashes, shootouts, explosions) with quiet driving/idle. Used to tune weights and check false positives in quiet stretches.
2. One OBS recording with variable frame rate (VFR) to test timestamp handling (check: ffprobe pts_time deltas of first 300 frames are uneven). MKV or MP4.
3. If possible, one console capture in HEVC (PS5/Xbox), ideally HDR (arib-std-b67 / smpte2084) to test tone mapping and 4K proxy speed.
Also useful: a clip with facecam in a corner, and one with speech.

## Legal
- Testing on your own captures, privately, on your own machine is fine.
- Never commit, upload or redistribute footage. Nothing goes in the repo (keep in ~/clip-test-media, add to .gitignore).
- No footage in README demos unless it is your own or properly licensed.
- Downloaded third-party footage below is for local testing only; keep attribution notes with it.

## If the owner has none: free / licensed candidates (checked 2026-11-12)
- https://archive.org/details/youtube-SMYltMw_-QM  Persona 3 gameplay 4K, ShadowPlay 60 fps 65 Mbps. Page shows "Attribution 3.0" (CC BY 3.0) but description says CC0: conflicting, treat as CC BY 3.0 with attribution. Good for hi-bitrate 60 fps.
- https://archive.org/details/Gameplay_Footage_Collection  Retronyash collection, 565 files (H.264 / MKV, 56 MB to 3 GB each, e.g. Ghost Recon AW 182 MB, NWN 344 MB). Page shows NO licence (only IA terms of service): not cleared; local testing at own risk, do not redistribute.
- https://archive.org/details/gameplays_archive  and /gameplays_archive2  Various gameplay uploads; licence not verified.
- Wing Force (Atlus arcade) longplay on archive.org: listed as CC BY 4.0 in the IA collection feed (https://archive.org/services/collection-rss.php?collection=gamevideos); item URL not yet confirmed.
- CC-BY YouTube: filter Search > Features > Creative Commons, query "gameplay no commentary 1 hour"; confirm "Creative Commons Attribution license (reuse allowed)" under the video description before downloading (yt-dlp, local only).
Caveat: CC licence on the upload does not remove the game publisher's rights; fine for private tuning, not for redistribution.
