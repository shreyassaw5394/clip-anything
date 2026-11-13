"""Every prompt the AI mode sends, in one place, so a hosted service can reuse them verbatim.

Only two things are ever sent: 3-4 small proxy frames of a candidate moment and (when captions
ran) the words spoken inside that moment. No file names, no paths, no other clips.
"""

from __future__ import annotations

TITLE_WORDS = "4 to 6 words"
HOOK_CHARS = 90

SYSTEM = (
    "You title short vertical gameplay highlight clips. You are terse, concrete and never "
    "invent events you cannot see or read. Reply with one JSON object and nothing else."
)

_RATE = (
    "Rate how clip-worthy the moment is for a short vertical highlight: 1 = menu, loading "
    "screen, map, inventory, idle or empty scene; 5 = ordinary play; 10 = intense action, a "
    "kill, a win, a crash, a big reveal."
)

_FIELDS_WITH_SCORE = (
    '{{"score": <integer 1-10>, "title": "<{words} word title>", '
    '"hook": "<one line, under {chars} characters, for the post text>", '
    '"reaction": "<the single best spoken line copied exactly, or an empty string>"}}'
)
_FIELDS_WITH_MATCH = (
    '{{"score": <integer 1-10>, "match": <integer 1-10>, '
    '"matches": "<one short line: what in the moment matches the brief, or empty>", '
    '"title": "<{words} word title>", '
    '"hook": "<one line, under {chars} characters, for the post text>", '
    '"reaction": "<the single best spoken line copied exactly, or an empty string>"}}'
)
_FIELDS_TEXT_ONLY = (
    '{{"title": "<{words} word title>", '
    '"hook": "<one line, under {chars} characters, for the post text>", '
    '"reaction": "<the single best spoken line copied exactly, or an empty string>"}}'
)


BRIEF_CHARS = 300


def brief_text(brief: str | None) -> str:
    """The user's brief, one line, bounded, quotes neutralised (it is data, not instructions)."""
    b = " ".join((brief or "").split())[:BRIEF_CHARS]
    return b.replace('"', "'")


def clip_prompt(
    transcript: str | None, with_frames: bool, action_hint: str = "", brief: str = ""
) -> str:
    """The one prompt used per candidate. `with_frames` = the provider also receives frames
    (then a score is requested); otherwise title/hook come from the transcript + action hint.
    `brief` = what the user said they are looking for: the model also rates the match 1-10."""
    parts: list[str] = []
    brief = brief_text(brief)
    if with_frames:
        parts.append("These frames are from one moment of a video game recording.")
        parts.append(_RATE)
    else:
        parts.append("This is one moment of a video game recording (no frames available).")
    if brief:
        parts.append(
            f'The person wants clips of: "{brief}". Rate "match" 1-10 for how well THIS moment '
            "fits that description (1 = nothing to do with it, 10 = exactly it), from what you "
            "can see and hear only, and say in one short line what matches (empty if nothing)."
        )
    if action_hint:
        parts.append(f"Action detector: {action_hint}.")
    if transcript:
        parts.append("Words spoken during the moment (may be noisy):\n" + transcript.strip()[:1200])
        parts.append(
            'For "reaction" pick the single most quotable spoken line, copied exactly as '
            "written above; empty string if nothing is worth featuring."
        )
    else:
        parts.append('Nothing was spoken: "reaction" must be an empty string.')
    fields = _FIELDS_WITH_SCORE if with_frames else _FIELDS_TEXT_ONLY
    if brief:
        fields = _FIELDS_WITH_MATCH if with_frames else _FIELDS_TEXT_ONLY
        if not with_frames:
            fields = fields.replace(
                '{{"title"', '{{"match": <integer 1-10>, "matches": "<one short line>", "title"'
            )
    parts.append("Reply with JSON only: " + fields.format(words=TITLE_WORDS, chars=HOOK_CHARS))
    return "\n".join(parts)
