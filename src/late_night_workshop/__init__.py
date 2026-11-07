"""Late Night Pal desktop study sidekick."""

import sys
from pathlib import Path


def resource_path(relative: str) -> Path:
    """Locate a packaged resource (prompts/, templates/) in source or frozen runs."""
    base = Path(getattr(sys, "_MEIPASS", "")) / "late_night_workshop" if getattr(sys, "frozen", False) else Path(__file__).parent
    return base / relative


class AppError(Exception):
    """The one local error type: carries the failure envelope {code, stage, message, ...}."""

    stage = ""

    def __init__(self, code: str, message: str, details: str = "", retryable: bool = False, source_id=None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details
        self.retryable, self.source_id = retryable, source_id

    def envelope(self) -> dict:
        return {"code": self.code, "stage": self.stage, "message": self.message, "source_id": self.source_id,
                "retryable": self.retryable, "details": {"log": self.details} if self.details else {}}
