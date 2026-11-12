# DISTRIBUTION — after friends test it, then "to the best" (owner 2026-11-12)

Lesson from the owner's last launch (memory `project_distribution.md`): seven packages on npm/PyPI, four registries, three awesome-list PRs gave about zero downloads. Registries are shelves, not traffic. Awareness is the problem. Two things are different this time: the GTA 6 release window (2026-11-19) is a hook with built-in search volume, and the product emits video, so every demo clip the tool makes is itself the ad. Rule: no post without a clip made by the tool attached.

## (a) Feedback intake this week (friends + first strangers)

- GitHub issue template `.github/ISSUE_TEMPLATE/tried-it.yml` titled "Tried it" with exactly three questions: (1) What did you record and on what (game, OS, source: OBS / PS5 / Xbox / ShadowPlay / phone)? (2) Of the clips it returned, how many would you post without edits, and which ones were duds (menu / loading / idle)? (3) Paste `report.json` warnings and the one line you would change. (Template file is created by the security/legal pass that owns `.github/`; this plan only specifies it.)
- Discord: one `#clip-anything` channel in the Ship at Midnight server (s8wj7tBAM); pin the install lines and the "Tried it" link; ask testers to drop one clip + the report.
- Measure per tester, in a table in `.planning/FEEDBACK.md`: duds per 10 returned; time to first clip (wall seconds from command to first `.mp4`); install failures per OS (uv missing, ffmpeg missing, libass missing, Python version); clips returned vs asked; whether they posted any clip anywhere. Target before wide release: ≤ 1 dud / 10, first clip < 2 min on a 1-h file, zero unexplained install failures.

## (b) Release gates before wide distribution (owner's rules)

1. Full security + legal gates: `security-hardening`, `abuse-prevention` (n/a: no server, note why), `legal-compliance`, `legal-suite` launch review + marketing-claims review + OSS licence review; NOTICE complete; README claims audited (numbers with a method, no "best", no "never misses").
2. BENCHMARK.md rows: each of 1, 3, 4, 5, 9, 10, 11 green, or the miss listed in README "Known limits" in plain words. Row 5 (postable without edits) needs the human review of 30 clips: the friends' round is that review.
3. Third game measured (row 2): at least one recording of a game not used for tuning, scored and written down, before any post says "any game".
4. PyPI publish done and `UV_CACHE_DIR=$(mktemp -d) uvx clip-anything --version` passes from a clean cache on macOS, Linux and one Windows machine; npm launcher published after PyPI, never before.
5. Demo assets made by the tool from owner footage or openly licensed footage only (public domain / CC BY with credit in the post). No copyrighted stream VODs of other people.

## (c) Channels ranked by expected reach for gamers and streamers (not developers)

| # | Channel | When | What to post (one line) | What it needs |
|---|---|---|---|---|
| 1 | Short demo videos: TikTok, YouTube Shorts, Instagram Reels, X | daily from 11-16; 2/day on 11-19 and 11-20 | A clip the tool made, with a 2-s title card "found by one command, no upload" and the command in the caption | Owner accounts; owner or openly licensed footage; a vertical screen capture of the terminal run for one of the posts |
| 2 | Reddit: r/GTA (+ game subs for the footage used), r/Twitch, r/streaming, r/VideoEditing | 11-17 (r/VideoEditing, r/streaming), 11-19 evening (r/GTA), 11-20 (r/Twitch) | "I made a free local tool that finds the action in a 3-hour recording with no speech. Here are the 10 clips it picked from X." with the clips | Read each sub's rules first: anonymous fetch of the rules pages was blocked on 2026-11-12, so the owner opens each sidebar before posting. Known pattern on all four: self-promo only with substance, no link-only posts, often a 1:10 own-content ratio, flair required; r/Twitch and r/streaming generally remove channel/product plugs unless framed as a how-to. Post as a how-to with results, link in a comment, answer every reply |
| 3 | Hacker News "Show HN" | 11-18 morning US (before GTA 6 news floods) | "Show HN: Clip Anything – a local CLI that finds highlights in gameplay with no transcript" + how the scoring works; honest limits in the first comment | README numbers final; the owner's account posts; be at the keyboard for 4 h |
| 4 | YouTube tutorial (3-5 min) | 11-21 | "One command, ten clips: how I clip a 4-hour session on a laptop" with the terminal + results | Screen recording, owner voice or captions, timestamps in description |
| 5 | Discord servers for OBS / streaming tooling / game-specific modding | 11-17 onward, one per day | Only in #showcase or #tools channels, one message, clips attached | Read each server's rules; no DMs; a real answer to every question |
| 6 | Product Hunt | 11-20 (not launch day: PH traffic is makers, not gamers) | Tagline "Your 10-hour session has 10 great moments"; gallery = clips + demo.gif | Owner account, first comment with the "why not transcript" story, 5 screenshots |
| 7 | Claude Code plugin marketplace (`.claude-plugin/`, done) + MCP registry later if an MCP server is added | marketplace: at PyPI publish; MCP registry: only after an MCP server exists | "`/plugin marketplace add shreyassaw5394/clip-anything` and ask Claude to clip your recording" | GitHub repo public; an MCP server is a later decision, not v1 |
| 8 | PyPI, npm launcher, Homebrew tap (`shreyassaw5394/homebrew-tap`, formula depends on ffmpeg) | PyPI 11-15; npm 11-16; tap 11-22 | Nothing to post; these are shelves that the posts above point to | Trusted publishing set up by the owner (section e) |
| 9 | Awesome lists: awesome-cli-apps, awesome-python (Video section), awesome-ffmpeg, awesome-selfhosted (no: not a service) | 11-23 onward, after stars exist | One-line PR per list following each list's contribution rules | A public repo with a release, a demo gif, and tests |
| 10 | Streamer outreach (small creators, 1-10k) | 11-24 onward | Offer to run their VOD locally on their machine via a call, zero upload; ask for feedback, not a shout-out | A list of 20 creators who post gameplay shorts; the owner's DM |

## (d) Calendar

- Sun 11-15: midnight ship: tag v0.1.0, PyPI publish, GitHub release with demo.gif, Ship at Midnight products page + log; friends get the install line and the "Tried it" link.
- Mon 11-16: npm launcher publish; first two demo shorts (owner GTA 5 footage); Discord channel open; collect first feedback rows.
- Tue 11-17: fix round from feedback (duds, install failures); r/VideoEditing + r/streaming how-to posts; first Discord showcase.
- Wed 11-18: Show HN morning; v0.1.1 if fixes landed; plugin marketplace announced in the HN thread and Discord.
- Thu 11-19 (GTA 6 day): record own GTA 6 session if the owner has the game; run the tool the same night; post the clips as "day one, no profile, no upload" on TikTok/Shorts/Reels/X and r/GTA in the evening. If no copy: use whatever new footage the owner has; the claim stays "any game", shown on a game released that week.
- Fri 11-20: Product Hunt; r/Twitch how-to; second batch of shorts from the 11-19 session.
- Sat 11-21: YouTube tutorial; weekly feedback table; decide v0.2 scope from the dud list.
- After: Homebrew tap (11-22), awesome-list PRs (11-23+), streamer outreach (11-24+), monthly: re-run BENCHMARK and post the numbers.

## (e) What only the owner can do

- Accounts and posting: TikTok, YouTube, Instagram, X, Reddit, Hacker News, Product Hunt, Discord server admin. Agents draft text and make the clips; the owner posts and replies.
- PyPI: create the project on first upload (token) or add a pending trusted publisher (owner/clip-anything, workflow `publish.yml`, environment `pypi`); 2FA on the account.
- npm: `npm login`, first `npm publish` of `npm/` (public, provenance), then configure trusted publishing (GitHub Actions OIDC) in the package settings so CI can publish later; 2FA on.
- GitHub: create the public repo, enable Discussions or not, add the `.github` templates from the security/legal pass, set branch protection, add the Homebrew tap repo when the time comes.
- Footage rights: decide which own recordings may be posted; credit for any CC BY footage used in demos.
- Game purchase and recording on 11-19.
