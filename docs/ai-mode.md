# AI mode (`--ai`) and one-shot setup

Clip Anything picks moments by action (sound bursts, motion, cuts) and needs no AI at all. The
plain run stays exactly that. `--ai` is an optional, advanced layer on top for people who have a
local LLM or their own API key.

## Want AI titles and smarter picks?

```sh
clip-anything setup          # checks ffmpeg, captions, local AI; offers to install what is missing
clip-anything gameplay.mp4 --ai
```

`setup` prints one line per item (✓ present, → missing), shows the exact command it would run,
and runs it only after you say yes (`--yes` accepts everything, `--no-ai` skips the Ollama part,
`--no-captions` skips faster-whisper). A second run is all ✓ and finishes in well under a second.
Nothing is ever installed silently.

## What `--ai` adds

With the action detector's top 3N candidates (N = `--count`), the model is asked once per
candidate and nothing else:

| Output | Where it lands |
|---|---|
| A clip-worthiness score (1–10) from 3–4 small frames | `components.ai`; final score = 0.7 action + 0.3 AI; the top N are re-ranked |
| A 4–6 word title | `clips[].title`, the file name slug (`game_01_12-40_clutch-triple-kill.mp4`) |
| A one-line hook for the post text | `clips[].ai.hook` and a `<clip>.txt` sidecar next to the video |
| When captions ran: the single best spoken line | burned once as a big upper-case "reaction" caption, also in the sidecar |

Every AI text in `report.json` carries `ai_generated: true`, and the run prints one disclosure
line. Check titles and hooks before you post: they come from a model and can be wrong. If the
model is unreachable, times out, or answers badly, the run keeps the action-only order and leaves
one warning (the same behaviour as the older `--vision` flag, which still works).

Multi-file sessions (a folder of short clips) are ranked action-only in this version.

## Tell it what you are looking for

```bash
clip-anything gameplay.mp4 --ai --ai-brief "funny fails and my reactions"
```

The brief goes into every prompt. The model rates each candidate twice: how clip-worthy it is,
and how well it **matches** the brief (1–10), with one line saying what matched. With a brief the
tool looks further down the action order (5N candidates instead of 3N, at most 40) and the final
score is 0.6 action + 0.4 AI, where the AI part is the mean of the two ratings (match alone for a
text-only model). Each clip gets `ai.match`, `ai.matches` ("Matches: he trips on the ledge") in
`report.json`, in the `<clip>.txt` sidecar and on the app's clip card; the run's brief is stored as
`ai.brief` at the top of the report. An empty brief is the plain `--ai` behaviour. The brief is
bounded to 300 characters and is quoted to the model as data, not instructions.

In the app the same box sits under "What are you looking for?"; it needs the AI toggle on. The
chips next to it (Fights, Funny, Big plays, Crashes, Calm but tense) are `--preset` weight sets and
work without AI.

## Providers and what leaves your machine

| `--ai-provider` | What is sent | Where | Cost |
|---|---|---|---|
| `ollama` (default when running) | frames + spoken lines | `127.0.0.1:11434` only, nothing leaves the machine | free; a 4B vision model needs ~3–4 GB disk and a few GB of RAM |
| `openai` | frames + spoken lines of up to 3N moments | `api.openai.com` | your key; roughly a few cents per run with `gpt-4o-mini` (`detail: low` images) |
| `anthropic` | frames + spoken lines of up to 3N moments | `api.anthropic.com` | your key; similar order with `claude-haiku-4-5` |
| `none` | nothing | — | — |

`auto` (the default) tries Ollama first, then `OPENAI_API_KEY`, then `ANTHROPIC_API_KEY`. Keys
are read from the environment or `--ai-key`; they are used for the one run, never written to
disk, the report or logs. Prefer the environment variable over `--ai-key` (command lines are
visible to other processes). No file names, paths or other clips are included in prompts. All
prompts live in `clip_anything/ai_prompts.py`.

Model choice: `--ai-model` (text/API model, e.g. `llama3.2`, `gpt-4o-mini`) and
`--ai-vision-model` (Ollama only; frames go to this one). With Ollama, a vision model
(`qwen3-vl:4b`, `gemma3:4b`, `minicpm-v`, `moondream`) is auto-picked from `ollama list`; a
text-only model still gives titles and hooks but cannot re-rank (no frames).

## Status

Tested against stub HTTP servers for all three providers (request shape, headers, image
encoding, timeouts, bad JSON, oversized replies). Real Ollama, OpenAI and Anthropic calls have
not been exercised on the development machine (no Ollama, no keys): the first real run may need
prompt tuning. Please report what the model got wrong.

<!-- Note for the main session: after README PR #5 merges, add this two-line paragraph to README:
"Want AI titles and smarter picks? Run `clip-anything setup`, then add `--ai`. Local Ollama by
default, or your own OpenAI/Anthropic key; see docs/ai-mode.md." -->
