"""Late Night Pal desktop study sidekick."""

import sys
from pathlib import Path


def resource_path(relative: str) -> Path:
    """Locate a packaged resource (prompts/, templates/) in source or frozen runs."""
    base = Path(getattr(sys, "_MEIPASS", "")) / "late_night_workshop" if getattr(sys, "frozen", False) else Path(__file__).parent
    return base / relative
