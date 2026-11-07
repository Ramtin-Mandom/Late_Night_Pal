"""Workshop folders: open/create, browse, selection across navigation, recents, containment.

A workshop is a real folder. State is a plain dict:
    {"root": Path, "current": Path, "selected": set[Path]}   # canonical absolute paths
Recents live in local app data under the internal id (not the display name),
so renaming the app never loses them.
"""

import json
import os
from pathlib import Path

from . import AppError

MAX_RECENTS = 10


class WorkshopError(AppError):
    stage = "validating"


def app_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "late_night_workshop"


def _recents_file() -> Path:
    return app_data_dir() / "recents.json"


def load_recents() -> list[dict]:
    """[{path, exists}] newest first; unreadable storage counts as empty."""
    try:
        paths = json.loads(_recents_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        paths = []
    return [{"path": p, "exists": Path(p).is_dir()} for p in paths if isinstance(p, str)]


def _save_recents(paths: list[str]) -> None:
    f = _recents_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(paths[:MAX_RECENTS], indent=1), encoding="utf-8")


def add_recent(path) -> None:
    p = str(Path(path).resolve())
    _save_recents([p] + [r["path"] for r in load_recents() if os.path.normcase(r["path"]) != os.path.normcase(p)])


def remove_recent(path) -> None:
    _save_recents([r["path"] for r in load_recents() if os.path.normcase(r["path"]) != os.path.normcase(str(path))])


def open_workshop(path) -> dict:
    root = Path(path).resolve()
    if not root.is_dir():
        raise WorkshopError("missing_workshop", f"Workshop folder not found: {root}")
    add_recent(root)
    return {"root": root, "current": root, "selected": set()}


def create_workshop(path) -> dict:
    root = Path(path)
    if root.exists():
        raise WorkshopError("workshop_exists", f"A file or folder named '{root.name}' already exists there.")
    root.mkdir(parents=True)
    return open_workshop(root)


def is_inside(root: Path, path: Path) -> bool:
    try:
        return Path(path).resolve().is_relative_to(Path(root).resolve())
    except OSError:
        return False


def relative(state_or_root, path) -> str:
    root = state_or_root["root"] if isinstance(state_or_root, dict) else Path(state_or_root)
    return Path(path).resolve().relative_to(root).as_posix()


def browse(state: dict, folder=None) -> list[dict]:
    """Move to folder (default: current) and list it: folders first, then files.
    Entries resolving outside the workshop (links) are left out."""
    target = Path(folder).resolve() if folder is not None else state["current"]
    if not target.is_dir() or not is_inside(state["root"], target):
        raise WorkshopError("outside_workshop", "That folder is outside the workshop.")
    state["current"] = target
    entries = []
    for child in sorted(target.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
        if child.name.startswith(".") or not is_inside(state["root"], child):
            continue
        resolved = child.resolve()
        entries.append({"name": child.name, "path": resolved, "is_dir": child.is_dir(),
                        "selected": resolved in state["selected"]})
    return entries


def toggle_selection(state: dict, path) -> bool:
    """Toggle one file; returns whether it is now selected."""
    p = Path(path).resolve()
    if not is_inside(state["root"], p):
        raise WorkshopError("outside_workshop", f"{p.name} is outside the workshop.")
    if not p.is_file():
        raise WorkshopError("not_a_file", f"{p.name} is not a file.")
    if p in state["selected"]:
        state["selected"].discard(p)
        return False
    state["selected"].add(p)
    return True


def selected_sorted(state: dict) -> list[Path]:
    """Selected paths in stable workshop-relative order."""
    return sorted(state["selected"], key=lambda p: relative(state, p).lower())


def validate_paths(root, destination, paths) -> dict:
    """Recheck containment/readability at generation time. Returns canonical values."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise WorkshopError("missing_workshop", f"Workshop folder not found: {root}")
    dest = Path(destination).resolve()
    if not dest.is_dir() or not is_inside(root, dest):
        raise WorkshopError("outside_workshop", "The destination folder is outside the workshop or missing.")
    canonical = []
    for p in paths:
        rp = Path(p).resolve()
        if not is_inside(root, rp):
            raise WorkshopError("outside_workshop", f"{Path(p).name} is outside the workshop.", source_id=str(p))
        if not rp.is_file() or not os.access(rp, os.R_OK):
            raise WorkshopError("unreadable_input", f"Cannot read {Path(p).name}.", source_id=relative(root, rp))
        canonical.append(rp)
    canonical.sort(key=lambda p: relative(root, p).lower())
    return {"root": root, "destination": dest, "paths": canonical}
