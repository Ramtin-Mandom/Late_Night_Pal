"""Workshop folders: open/create, browse, selection across navigation, recents, containment.

A workshop is a real folder. State is a plain dict:
    {"root": Path, "current": Path, "selected": set[Path]}   # canonical absolute paths
Recents live in local app data under the internal id (not the display name),
so renaming the app never loses them.
"""

import json
import os
import stat
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


_LINK_TAGS = {0xA000000C, 0xA0000003}  # IO_REPARSE_TAG_SYMLINK, IO_REPARSE_TAG_MOUNT_POINT (junction)


def is_link(path) -> bool:
    """Symlink or junction, checked without following it. Other reparse points
    (OneDrive cloud placeholders) are ordinary files and stay allowed."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISLNK(st.st_mode) or getattr(st, "st_reparse_tag", 0) in _LINK_TAGS


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
    """Toggle one file or folder in the shared selection; returns whether it is now selected.
    Any ordinary file type may be selected (Make me checks its own stricter rules)."""
    if is_link(path):
        raise WorkshopError("link_rejected", f"{Path(path).name} is a link or junction and cannot be selected.")
    p = Path(path).resolve()
    if not is_inside(state["root"], p):
        raise WorkshopError("outside_workshop", f"{p.name} is outside the workshop.")
    if p == state["root"]:
        raise WorkshopError("root_selected", "The workshop folder itself cannot be selected.")
    if not (p.is_file() or p.is_dir()):
        raise WorkshopError("missing_entry", f"{p.name} no longer exists. Click Refresh.")
    if p in state["selected"]:
        state["selected"].discard(p)
        return False
    state["selected"].add(p)
    return True


def select_range(state: dict, ordered, anchor, target) -> list[Path]:
    """Shift+click: add every row from anchor to target (inclusive, in the listed order) to the shared
    selection; never deselects. Without the anchor in the list only target is added.
    Rows that can't be selected (links, gone) are skipped. Returns the added paths."""
    keys = [os.path.normcase(str(Path(p).resolve())) for p in ordered]
    t = os.path.normcase(str(Path(target).resolve()))
    a = os.path.normcase(str(Path(anchor).resolve())) if anchor is not None else t
    if t not in keys:
        return []
    i, j = keys.index(t), keys.index(a) if a in keys else keys.index(t)
    added = []
    for p in list(ordered)[min(i, j):max(i, j) + 1]:
        rp = Path(p).resolve()
        if rp in state["selected"] or is_link(p) or rp == state["root"] or not rp.exists():
            continue
        state["selected"].add(rp)
        added.append(rp)
    return added


def deselect(state: dict, path) -> bool:
    """Remove one entry by its canonical path, even if it is missing or outside the current view.
    Never touches the file. Returns whether anything was removed."""
    key = os.path.normcase(str(path))
    hits = [p for p in state["selected"] if os.path.normcase(str(p)) == key]
    for p in hits:
        state["selected"].discard(p)
    return bool(hits)


def prune(state: dict) -> list[Path]:
    """Explicit Refresh only: drop selected entries that no longer exist and, if the current
    folder was removed, move to its nearest surviving folder inside the workshop.
    Returns the removed paths so the UI can report them (nothing is pruned silently)."""
    gone = [p for p in selected_sorted(state) if not os.path.lexists(p)]
    for p in gone:
        state["selected"].discard(p)
    current = state["current"]
    while current != state["root"] and not current.is_dir():
        current = current.parent
    state["current"] = current
    return gone


def _under(path: Path, top: Path) -> bool:
    p, t = os.path.normcase(str(path)), os.path.normcase(str(top))
    return p == t or p.startswith(t.rstrip("\\/") + os.sep)


def remap_paths(paths, outcomes) -> list[Path]:
    """Apply only completed changes: moved entries (and anything inside them) get their new path,
    deleted entries (and anything inside them) are dropped, everything else is kept as is."""
    out = []
    for p in map(Path, paths):
        for o in outcomes:
            if o["status"] != "completed":
                continue
            src = Path(o["source"])
            if o["change"] == "moved" and _under(p, src):
                p = Path(o["destination"]) / Path(os.path.relpath(p, src)) if p != src else Path(o["destination"])
            elif o["change"] == "deleted" and _under(p, src):
                p = None
                break
        if p is not None:
            out.append(Path(os.path.normpath(p)))
    return out


def reconcile(state: dict, outcomes) -> None:
    """After an organizer run: remap completed moves, drop completed deletions, keep failed,
    unattempted and copied_source_kept entries (their sources still exist). The current folder
    follows a move, or falls back to its nearest surviving folder."""
    state["selected"] = set(remap_paths(state["selected"], outcomes))
    current = (remap_paths([state["current"]], outcomes) or [state["current"]])[0]
    while current != state["root"] and not current.is_dir():
        current = current.parent
    state["current"] = current


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
