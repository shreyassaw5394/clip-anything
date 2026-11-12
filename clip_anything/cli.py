"""Thin CLI over clip_anything.pipeline.run. The only module that prints or exits."""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Annotated

import typer

from . import __version__

app = typer.Typer(add_completion=False, rich_markup_mode=None, no_args_is_help=True)

EXIT_BAD_INPUT = 2
EXIT_NO_FFMPEG = 3


def _version(value: bool) -> None:
    if value:
        print(f"clip-anything {__version__}")
        raise typer.Exit()


@app.command()
def main(
    video: Annotated[
        list[Path], typer.Argument(help="Recording(s): file, several files or a folder")
    ],
    count: Annotated[int, typer.Option("--count", "-n", help="Clips to produce")] = 10,
    min_s: Annotated[float, typer.Option("--min", help="Min clip length (s)")] = 15.0,
    max_s: Annotated[float, typer.Option("--max", help="Max clip length (s)")] = 45.0,
    out: Annotated[Path, typer.Option("--out", "-o", help="Output folder")] = Path("./clips"),
    no_captions: Annotated[bool, typer.Option("--no-captions", help="Never burn captions")] = False,
    facecam: Annotated[str, typer.Option("--facecam", help="auto | off")] = "auto",
    crop: Annotated[str, typer.Option("--crop", help="follow the action | center")] = "follow",
    vision: Annotated[bool, typer.Option("--vision/--no-vision", help="Ollama re-rank")] = False,
    config: Annotated[Path | None, typer.Option("--config", help="TOML config")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Report JSON to stdout")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Report only, no render")] = False,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Ignore signal cache")] = False,
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing clips")] = False,
    workers: Annotated[int | None, typer.Option("--workers", help="Parallel renders")] = None,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Allow the one-time Whisper model download")
    ] = False,
    download_models: Annotated[
        bool, typer.Option("--download-models", help="Same as --yes (download, then continue)")
    ] = False,
    whisper_model: Annotated[
        str | None, typer.Option("--whisper-model", help="tiny.en | base.en | small ...")
    ] = None,
    speech_rank: Annotated[
        bool, typer.Option("--speech-rank", help="Transcribe top 3N candidates, re-rank")
    ] = False,
    version: Annotated[
        bool | None, typer.Option("--version", callback=_version, is_eager=True)
    ] = None,
    audio_track: Annotated[
        str, typer.Option("--audio-track", help="auto | all | game | mic | N (stream number)")
    ] = "auto",
    resume: Annotated[
        bool, typer.Option("--resume/--no-resume", help="Continue an interrupted analysis")
    ] = True,
    min_score: Annotated[
        float | None,
        typer.Option(
            "--min-score",
            help="Action bar 0..1 a moment must clear to become a clip (default 0.5; "
            "--count is a maximum). 0 = rank the file against itself only",
        ),
    ] = None,
) -> None:
    """Long gameplay recording in, top N vertical highlight clips + report.json out."""
    from rich.console import Console

    err = Console(stderr=True)
    if facecam not in ("auto", "off"):
        err.print("[red]--facecam must be auto or off[/red]")
        raise typer.Exit(EXIT_BAD_INPUT)
    if crop not in ("follow", "center"):
        err.print("[red]--crop must be follow or center[/red]")
        raise typer.Exit(EXIT_BAD_INPUT)

    # ffmpeg check first, before importing numpy/scipy
    from .errors import FFmpegMissing, InputError, StageError
    from .probe import preflight

    try:
        caps = preflight()
    except FFmpegMissing as exc:
        err.print(f"[red]{exc}[/red]\n{exc.help_text}")
        raise typer.Exit(EXIT_NO_FFMPEG) from None

    from .config import Options, load_config_file

    try:
        file_layer = load_config_file(config)
        cli_layer = {
            "clips": {"count": count, "min_s": min_s, "max_s": max_s},
            "render": {
                "out_dir": os.fspath(out),
                "dry_run": dry_run,
                "force": force,
                "workers": workers,
            },
            "speech": {
                "captions": False if no_captions else None,
                "yes": True if (yes or download_models) else None,
                "model": whisper_model,
                "rank": True if speech_rank else None,
            },
            "vision": {"enabled": vision},
            "layout": {"facecam": facecam, "crop": crop},
            "scoring": {"min_evidence": min_score},
            "analysis": {
                "cache": False if no_cache else None,
                "audio_track": audio_track,
                "resume": resume,
            },
        }
        opts = Options.from_layers(file_layer, cli_layer)
    except InputError as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(EXIT_BAD_INPUT) from None
    if opts.clips.min_s > opts.clips.max_s or opts.clips.min_s <= 0:
        err.print("[red]--min must be > 0 and <= --max[/red]")
        raise typer.Exit(EXIT_BAD_INPUT)
    if not 0.0 <= opts.scoring.min_evidence <= 1.0:
        err.print("[red]--min-score must be between 0 and 1[/red]")
        raise typer.Exit(EXIT_BAD_INPUT)

    # Whisper weights: the only network use. Ask once on a TTY, never silently.
    if (opts.speech.captions or opts.speech.rank) and not opts.speech.yes and not as_json:
        from .speech import MODEL_SIZES_MB, model_status

        if model_status(opts.speech.model) == "download" and sys.stdin.isatty():
            mb = MODEL_SIZES_MB.get(opts.speech.model, "?")
            if typer.confirm(f"Download Whisper {opts.speech.model} (~{mb} MB) for captions?"):
                opts.speech.yes = True

    from .pipeline import run
    from .ui import ProgressUI, print_summary

    cancel = threading.Event()
    ui = ProgressUI(err, enabled=not as_json)
    try:
        with ui:
            target = video[0] if len(video) == 1 else video
            report = run(target, opts, on_event=ui.on_event, cancel=cancel, caps=caps)
    except KeyboardInterrupt:
        cancel.set()
        err.print("[yellow]cancelled[/yellow]")
        raise typer.Exit(130) from None
    except InputError as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(EXIT_BAD_INPUT) from None
    except StageError as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None

    # --vision: optional local Ollama re-rank + titles. Applied here after the run until the
    # pipeline grows a `vision` stage of its own (then this block is a no-op).
    if opts.vision.enabled and not any(s.name == "vision" for s in report.stages):
        from .vision import rerank_report

        src = Path(str(report.input.get("path", "")))
        if src.is_file():
            rerank_report(report, src, caps.ffmpeg, model=opts.vision.model)
            if report.report_path:
                report.write(report.report_path)

    if as_json:
        json.dump(report.to_dict(), sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print_summary(err, report)
    if not dry_run and report.clips and not report.ok_clips:
        raise typer.Exit(1)


if __name__ == "__main__":  # pragma: no cover
    app()
