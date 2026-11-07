"""Publisher: safe final names in the captured destination; never overwrites, no partial output.

Layouts (names come from the registry, never from the model):
  single    <dest>/<filename>                     -> summary.pdf, summary (2).pdf, ...
  schedule  <dest>/<folder>/{schedule,file-guide,checklist}.pdf
  daily     <dest>/<folder>/Day NN/{notes,sample-questions,checklist}.pdf
Folder layouts are built in a hidden staging sibling, then renamed into place;
a collision suffixes the new folder (`Study Schedule (2)`) and leaves the old one alone.
"""

import os
import shutil
import uuid
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


def _numbered(name: str, n: int, is_file: bool) -> str:
    if n == 1:
        return name
    if is_file:
        stem, suffix = os.path.splitext(name)
        return f"{stem} ({n}){suffix}"
    return f"{name} ({n})"


def relative_output_paths(task: dict, rendered: list[dict]) -> dict:
    """document_id -> path relative to the output root, from local layout rules only."""
    kind = task["layout"]["kind"]
    if kind == "single":
        return {r["document_id"]: task["layout"]["filename"] for r in rendered}
    if kind == "schedule":
        return {r["document_id"]: f"{r['role']}.pdf" for r in rendered}
    if kind == "daily":
        return {r["document_id"]: f"Day {r['day']:02d}/{r['role']}.pdf" for r in rendered}
    raise PublishError("publish_failed", f"Unknown layout '{kind}'.")


def _publish_single(data: bytes, dest: Path, filename: str) -> Path:
    n = 1
    while True:
        final = dest / _numbered(filename, n, True)
        try:
            fd = os.open(final, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0))
            break
        except FileExistsError:
            n += 1
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    except BaseException:
        final.unlink(missing_ok=True)  # only the file this job just created
        raise PublishError("publish_failed", f"Could not write {final.name}.")
    return final


def _publish_folder(rendered: list[dict], rel: dict, dest: Path, folder: str) -> tuple[Path, list[Path]]:
    staging = dest / f".lnp-staging-{uuid.uuid4().hex[:8]}"
    try:
        staging.mkdir()
        for r in rendered:
            target = staging / rel[r["document_id"]]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(r["temp_path"], target)
        n = 1
        while True:
            final = dest / _numbered(folder, n, False)
            if not final.exists():
                try:
                    os.rename(staging, final)  # fails instead of replacing an existing folder
                    break
                except FileExistsError:
                    pass
            n += 1
    except PublishError:
        raise
    except OSError:
        shutil.rmtree(staging, ignore_errors=True)
        raise PublishError("publish_failed", f"Could not write the '{folder}' folder.", retryable=True)
    return final, [final / rel[r["document_id"]] for r in rendered]


def publish(rendered: list[dict], task: dict, destination, workshop_root) -> dict:
    dest = check_destination(destination, workshop_root)
    ids = [r["document_id"] for r in rendered]
    if len(ids) != len(set(ids)) or len(ids) != task["expected"]["document_count"]:
        raise PublishError("publish_failed", "Rendered documents do not match the expected layout.")
    rel = relative_output_paths(task, rendered)
    if task["layout"]["kind"] == "single":
        final = _publish_single(Path(rendered[0]["temp_path"]).read_bytes(), dest, rel[ids[0]])
        return {"output_root": str(dest), "paths": [str(final)]}
    root, paths = _publish_folder(rendered, rel, dest, task["layout"]["folder_name"])
    return {"output_root": str(root), "paths": [str(p) for p in paths]}
