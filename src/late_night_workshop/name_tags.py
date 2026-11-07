"""Folder-specific name tags: chips, counters, rename reservations, outcome-based remapping.

No Qt and no file moves here: the UI emits events, organizing plans/executes the rename, and
this module only changes tag metadata. Stored in %LOCALAPPDATA%/late_night_workshop/organizer.json:

    {"folders": {<normcased canonical folder>: {
        "chips": ["assignment", ...],            # at most six visible chips, display spelling
        "counters": {"assignment": 6, ...},      # next number per lowercase name; kept when a chip is removed
        "pending": {"assignment": 5}}}}          # reservation in flight (cleared on finish or next load)

Every change goes through save() (atomic replace); a failed save restores the previous state
and raises TagError, so the UI never claims a tag was saved when it was not.
"""

import copy
import json
import os
from pathlib import Path

from . import AppError, organizing, workshops

MAX_CHIPS = 6


class TagError(AppError):
    stage = "tags"


def _file() -> Path:
    return workshops.app_data_dir() / "organizer.json"


def key(folder) -> str:
    return os.path.normcase(str(Path(folder)))


def load() -> dict:
    """Read stored tags. A reservation left by a crash keeps its advanced counter (a gap is fine)."""
    try:
        data = json.loads(_file().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"folders": {}}
    except (OSError, ValueError) as e:
        raise TagError("tags_unreadable", f"Name tags could not be loaded ({e}); tag changes are off.") from None
    for state in data.get("folders", {}).values():
        state.pop("pending", None)
    return data


def _commit(data: dict, before: dict) -> None:
    f = _file()
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, f)
    except OSError as e:
        data.clear()
        data.update(before)
        raise TagError("tags_not_saved", f"Name tags could not be saved ({e.strerror or e}); nothing was changed.") from None


def _folder(data: dict, folder) -> dict:
    return data["folders"].setdefault(key(folder), {"chips": [], "counters": {}})


def chips(data: dict, folder) -> list[str]:
    return list(data["folders"].get(key(folder), {}).get("chips", []))


def add_chip(data: dict, folder, raw) -> str:
    """Validate like a folder name (no trimming), refuse a seventh chip or a case-insensitive duplicate."""
    try:
        name = organizing.check_folder_name(raw)
    except organizing.OrganizeError as e:
        raise TagError("invalid_tag", e.message.replace("Folder name", "Tag").replace("folder name", "tag name")) from None
    current = chips(data, folder)
    if len(current) >= MAX_CHIPS:
        raise TagError("too_many_tags", f"This folder already has {MAX_CHIPS} tags. Remove one to add another.")
    if name.lower() in (c.lower() for c in current):
        raise TagError("duplicate_tag", f"This folder already has a '{name}' tag.")
    before = copy.deepcopy(data)
    _folder(data, folder)["chips"].append(name)
    _commit(data, before)
    return name


def remove_chip(data: dict, folder, name: str) -> None:
    """Hide the chip; its counter history stays, so recreating it continues the numbering."""
    before = copy.deepcopy(data)
    state = _folder(data, folder)
    state["chips"] = [c for c in state["chips"] if c.lower() != name.lower()]
    _commit(data, before)


def reserve(data: dict, folder, tag: str, file) -> dict:
    """Pick the next free number for one ordinary file in this folder, persist the advanced counter
    before the rename runs, and return {tag, number, new_name}. Occupied numbers are skipped:
    any entry whose stem is tag_N (any extension, any case) counts as occupied."""
    file, folder = Path(file), Path(folder)
    if file.is_dir() or not file.exists():
        raise TagError("not_a_file", "Drop a tag on a file in this folder.")
    if key(file.parent) != key(folder):
        raise TagError("other_folder", "Tags rename files in the folder they belong to.")
    stems = {Path(c.name).stem.lower() if not c.is_dir() else c.name.lower() for c in folder.iterdir()}
    state = _folder(data, folder)
    n = state["counters"].get(tag.lower(), 1)
    while f"{tag}_{n}".lower() in stems:
        n += 1
    before = copy.deepcopy(data)
    state.setdefault("pending", {})[tag.lower()] = n
    state["counters"][tag.lower()] = n + 1
    _commit(data, before)
    return {"tag": tag, "number": n, "new_name": f"{tag}_{n}{file.suffix}"}


def finish(data: dict, folder, reservation: dict, succeeded: bool) -> None:
    """Success keeps the advanced counter; an ordinary failure or refusal releases the reservation."""
    before = copy.deepcopy(data)
    state = _folder(data, folder)
    name = reservation["tag"].lower()
    state.get("pending", {}).pop(name, None)
    if not succeeded and state["counters"].get(name) == reservation["number"] + 1:
        state["counters"][name] = reservation["number"]
    _commit(data, before)


def reconcile(data: dict, outcomes) -> bool:
    """Apply confirmed changes only (the same rule as workshops.reconcile): a completed move remaps a
    tagged folder and every tagged folder inside it; a completed delete (Delete or Rip's wrapper removal)
    clears chips and counters for that folder and everything inside it. Copies, failed and unattempted
    items change nothing. Returns whether anything changed (the caller saves)."""
    moved_or_deleted = [o for o in outcomes if o["status"] == "completed" and o["change"] in ("moved", "deleted")]
    if not moved_or_deleted:
        return False
    old = data["folders"]
    new, changed = {}, False
    for k, state in old.items():
        mapped = workshops.remap_paths([Path(k)], moved_or_deleted)
        if not mapped:
            changed = True
            continue
        nk = key(mapped[0])
        changed |= nk != k
        if nk != k or nk not in new:  # a folder that moved here wins over stale state at that path
            new[nk] = state
    data["folders"] = new
    return changed


def save_reconciled(data: dict, outcomes) -> None:
    before = copy.deepcopy(data)
    if reconcile(data, outcomes):
        _commit(data, before)
