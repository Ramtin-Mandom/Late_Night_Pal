"""The generation method saved for this installation."""
from PySide6.QtCore import QSettings

METHODS = {"codex": "Codex", "gemini": "Gemini API"}
DEFAULT_METHOD = "codex"


def preferences():
    return QSettings("Late Night Pal", "Late Night Pal")


def extras_open() -> bool:
    """Whether the panels under the file list (drop area, Recent downloads, Name tags) are shown."""
    return str(preferences().value("layout/extras_open", "true")).lower() != "false"


def set_extras_open(show: bool):
    preferences().setValue("layout/extras_open", "true" if show else "false")


def generation_method():
    value = preferences().value("generation/method", DEFAULT_METHOD)
    return value if value in METHODS else DEFAULT_METHOD
