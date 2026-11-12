"""Progress events emitted by the pipeline. The library never prints."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class Event:
    stage: str  # probe | audio | video | score | vision | render
    kind: str  # start | progress | done | cached | skipped | warn
    done: float = 0.0
    total: float | None = None
    unit: str = ""  # "s" (media seconds) or "clips"
    message: str = ""
    extra: dict = field(default_factory=dict)


OnEvent = Callable[[Event], None]


def emit(on_event: OnEvent | None, event: Event) -> None:
    if on_event is not None:
        on_event(event)
