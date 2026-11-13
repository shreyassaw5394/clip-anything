"""Word-synced ASS captions: 2-4 words per line, the spoken word highlighted, bold white with a
black outline, placed in the lower third of the 9:16 frame (clear of HUD and bottom UI).
Burned by the ffmpeg `ass` filter when libass is present; otherwise the .ass stays next to
the clip."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .config import SpeechOptions
from .speech import Word

ASS_NAME = "captions.ass"  # bare filename inside the render tmp dir (no path escaping)


@dataclass
class Line:
    words: list[Word]

    @property
    def start(self) -> float:
        return self.words[0].start

    @property
    def end(self) -> float:
        return self.words[-1].end


def group_lines(words: list[Word], max_words: int = 4, max_gap_s: float = 0.8) -> list[Line]:
    """Split words into lines of 2-4 words; break on long pauses, sentence punctuation or the
    word cap. A trailing single word is folded into the previous line when that stays <= 5."""
    lines: list[Line] = []
    cur: list[Word] = []
    for w in words:
        if cur and (w.start - cur[-1].end > max_gap_s or len(cur) >= max_words):
            lines.append(Line(cur))
            cur = []
        cur.append(w)
        if len(cur) >= 2 and w.text[-1:] in ".?!":
            lines.append(Line(cur))
            cur = []
    if cur:
        if len(cur) == 1 and lines and len(lines[-1].words) < 5:
            lines[-1].words.append(cur[0])
        else:
            lines.append(Line(cur))
    return lines


def _ts(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def build_ass(
    words: list[Word],
    opts: SpeechOptions,
    width: int = 1080,
    height: int = 1920,
    duration: float | None = None,
    reaction: str | None = None,
) -> str:
    """ASS script with clip-relative times. One Dialogue per spoken word: the whole line is
    shown, the current word in the highlight colour, so playback never flickers. `reaction`
    (AI mode): a spoken line to feature once, big and upper, while those words are said."""
    sy = height / 1920
    size = int(round(opts.font_size * sy))
    margin_v = int(round(opts.margin_v * sy))
    outline = max(2, int(round(4 * sy)))
    font = _esc(opts.font).replace(",", " ")
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n"
        "YCbCr Matrix: TV.709\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Cap,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,"
        f"100,100,0,0,1,{outline},0,2,{int(60 * sy)},{int(60 * sy)},{margin_v},1\n"
        f"Style: Big,{font},{int(size * 1.5)},{hl_colour(opts)},&H00FFFFFF,&H00000000,"
        f"&H80000000,-1,0,0,0,100,100,0,0,1,{outline + 2},0,8,{int(60 * sy)},{int(60 * sy)},"
        f"{int(420 * sy)},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events: list[str] = []
    hl = opts.highlight
    for line in group_lines(words, opts.max_words_per_line):
        n = len(line.words)
        for i, w in enumerate(line.words):
            start = w.start
            end = line.words[i + 1].start if i + 1 < n else max(w.end, start + 0.3) + 0.15
            if duration is not None:
                end = min(end, duration)
            if end <= start:
                continue
            parts = []
            for j, other in enumerate(line.words):
                t = _esc(other.text)
                parts.append(f"{{\\c{hl}&}}{t}{{\\c&HFFFFFF&}}" if j == i else t)
            events.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Cap,,0,0,0,,{' '.join(parts)}")
    span = reaction_span(words, reaction) if reaction else None
    if span is not None:
        start, end = span
        if duration is not None:
            end = min(end, duration)
        if end > start:
            events.append(
                f"Dialogue: 1,{_ts(start)},{_ts(end)},Big,,0,0,0,,{_esc(reaction.upper())}"
            )
    return header + "\n".join(events) + ("\n" if events else "")


def hl_colour(opts: SpeechOptions) -> str:
    return opts.highlight if opts.highlight.startswith("&H") else "&H0000FFFF"


_TOKEN_RE = re.compile(r"[^a-z0-9']+")


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.split(text.lower()) if t]


def reaction_span(words: list[Word], reaction: str) -> tuple[float, float] | None:
    """(start, end) of the first run of `words` that spells `reaction`; None when the model
    did not quote the transcript faithfully (then nothing is featured)."""
    want = _tokens(reaction)
    if not want or not words:
        return None
    toks = [_tokens(w.text) for w in words]
    flat: list[tuple[str, int]] = [(t, i) for i, ts in enumerate(toks) for t in ts]
    n = len(want)
    for k in range(len(flat) - n + 1):
        if [t for t, _ in flat[k : k + n]] == want:
            first, last = words[flat[k][1]], words[flat[k + n - 1][1]]
            return first.start, max(last.end, first.start + 0.6) + 0.4
    return None


def write_ass(path: str | os.PathLike, text: str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p
