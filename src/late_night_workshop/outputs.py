"""Publisher: safe final names in the captured destination; never overwrites, no partial files."""

import os
from pathlib import Path

from . import AppError
from .workshops import is_inside


class PublishError(AppError):
    stage = "publishing"


def check_destination(destination, workshop_root) -> Path:
    dest = Path(destination).resolve()
    if not dest.is_dir() or not is_inside(workshop_root, dest):
        raise PublishError("publish_failed", "The output folder is missing or outside the workshop.")
    if not os.access(dest, os.W_OK):
        raise PublishError("publish_failed", f"Cannot write to {dest.name}.")
    return dest


def _claim(dest: Path, filename: str):
    """Exclusively create the first free name: summary.pdf, summary (2).pdf, ... -> (path, fd)."""
    stem, suffix = os.path.splitext(filename)
    n = 1
    while True:
        candidate = dest / (filename if n == 1 else f"{stem} ({n}){suffix}")
        try:
            return candidate, os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0))
        except FileExistsError:
            n += 1


def publish(rendered: list[dict], task: dict, destination, workshop_root) -> dict:
    dest = check_destination(destination, workshop_root)
    layout = task["layout"]
    if layout["kind"] != "single" or len(rendered) != 1:
        raise PublishError("publish_failed", f"Layout '{layout['kind']}' is not available yet.")
    data = Path(rendered[0]["temp_path"]).read_bytes()
    final, fd = _claim(dest, layout["filename"])
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    except BaseException:
        final.unlink(missing_ok=True)  # only the file this job just created
        raise PublishError("publish_failed", f"Could not write {final.name}.")
    return {"output_root": str(dest), "paths": [str(final)]}
