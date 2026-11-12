"""Rich progress + summary table for the CLI (stderr only)."""

from __future__ import annotations

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from .events import Event
from .report import Report

STAGES = ["probe", "audio", "video", "score", "vision", "render"]


class ProgressUI:
    def __init__(self, console: Console, enabled: bool = True):
        self.console = console
        self.enabled = enabled
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description:<8}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
            transient=False,
            disable=not enabled,
        )
        self.tasks: dict[str, int] = {}

    def __enter__(self):
        self.progress.__enter__()
        return self

    def __exit__(self, *exc):
        for _stage, tid in self.tasks.items():
            task = self.progress.tasks[tid]
            if task.total is None:
                self.progress.update(tid, total=1, completed=1)
        return self.progress.__exit__(*exc)

    def _task(self, stage: str) -> int:
        if stage not in self.tasks:
            self.tasks[stage] = self.progress.add_task(stage, total=None)
        return self.tasks[stage]

    def on_event(self, ev: Event) -> None:
        tid = self._task(ev.stage)
        if ev.kind == "start":
            self.progress.update(tid, total=ev.total, completed=0)
        elif ev.kind == "progress":
            self.progress.update(tid, total=ev.total, completed=ev.done)
        elif ev.kind in ("done", "cached", "skipped"):
            total = ev.total if ev.total else 1
            label = ev.stage if ev.kind == "done" else f"{ev.stage} ({ev.kind})"
            self.progress.update(tid, total=total, completed=total, description=label)
        elif ev.kind == "warn" and self.enabled:
            self.console.print(f"[yellow]! {ev.stage}: {ev.message}[/yellow]")


def _mmss(t: float) -> str:
    m, s = divmod(int(t), 60)
    return f"{m:02d}:{s:02d}"


def print_summary(console: Console, report: Report) -> None:
    table = Table(title="clips", show_lines=False)
    table.add_column("#", justify="right")
    table.add_column("time")
    table.add_column("len", justify="right")
    table.add_column("score", justify="right")
    table.add_column("signals")
    table.add_column("file")
    for c in report.clips:
        comps = " ".join(f"{k}={v:.2f}" for k, v in sorted(c.components.items()))
        name = c.path.rsplit("/", 1)[-1] if c.path else f"({c.status})"
        if c.status == "failed":
            name = f"[red]failed: {c.error}[/red]"
        table.add_row(
            str(c.rank),
            f"{_mmss(c.start)}-{_mmss(c.end)}",
            f"{c.duration_s:.0f}s",
            f"{c.score:.2f}",
            comps,
            name,
        )
    console.print(table)
    for w in report.warnings:
        console.print(f"[yellow]! {w.stage}: {w.message}[/yellow]")
    t = report.timings
    console.print(
        f"{len(report.ok_clips)}/{len(report.clips)} clips -> {report.out_dir}  "
        f"(analysis {t.get('analyze_s', 0):.1f}s, render {t.get('render_s', 0):.1f}s, "
        f"total {t.get('total_s', 0):.1f}s)  report: {report.report_path}"
    )
