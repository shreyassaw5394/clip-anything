"""Error classes shared by the library. The CLI maps them to exit codes."""


class ClipAnythingError(Exception):
    """Base class."""


class InputError(ClipAnythingError):
    """Bad input (missing file, unreadable media, bad option). Exit 2."""


class FFmpegMissing(ClipAnythingError):
    """ffmpeg/ffprobe not found or too old. Exit 3."""

    def __init__(self, message: str, help_text: str = ""):
        super().__init__(message)
        self.help_text = help_text


class StageError(ClipAnythingError):
    """A pipeline stage failed."""

    def __init__(self, stage: str, message: str):
        super().__init__(f"{stage}: {message}")
        self.stage = stage
