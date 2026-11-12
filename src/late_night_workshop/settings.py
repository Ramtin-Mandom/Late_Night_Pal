"""The generation method saved for this installation."""
from PySide6.QtCore import QSettings

METHODS = {"codex": "Codex", "gemini": "Gemini API"}
DEFAULT_METHOD = "codex"


def preferences():
    return QSettings("Late Night Pal", "Late Night Pal")


def generation_method():
    value = preferences().value("generation/method", DEFAULT_METHOD)
    return value if value in METHODS else DEFAULT_METHOD
