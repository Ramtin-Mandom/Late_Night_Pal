"""Organizer contracts: click-time request -> validated plan -> (later) per-item outcomes.

P2-M1 scope: the data contracts, the shared preflight, and a real Wrap planner.
Nothing in this module mutates the filesystem yet; execute_plan() and the other
actions' planners belong to P2-M3 (Delete/Rip/Wrap/Copy/Paste) and P2-M4 (Super Wrap).

Request (built on the UI thread at click time by capture_request; later navigation cannot redirect it):
    {"action": str, "workshop_root": str, "destination": str, "sources": [str], "parameters": dict}
    - destination is the folder open in the browser when the button was pressed.
    - sources are canonical absolute paths in stable workshop-relative order.
    - parameters: Wrap/Super Wrap {"folder_name": raw text exactly as typed, or None if cancelled}.

Plan (plan_action; raises OrganizeError naming the conflicting paths before any mutation):
    {"action", "root", "destination", "create_folder": str|None,
     "items": [{"source": str, "destination": str|None, "kind": "file"|"dir"}]}

Outcome (execute_plan, P2-M3), one per plan item, in plan order:
    {"source": str, "destination": str|None, "kind": str,
     "status": "completed"|"failed"|"unattempted",
     "change": None|"moved"|"copied"|"deleted"|"copied_source_kept",
     "error": None|{code, message}}
    - "copied_source_kept": the destination copy was made and verified but removing the
      source failed. status is "failed" (not a completed move); both paths exist.
    - Consumers (workshop selection, tags, UI) update only from status == "completed"
      plus the copied_source_kept case, which adds a path but removes none.
    - Execution stops at the first failure; every later item is "unattempted".
"""

import os
import stat
from pathlib import Path

from . import AppError, tasks, workshops

ACTIONS = ("delete", "rip", "wrap", "copy", "paste", "super_wrap")
STATUSES = ("completed", "failed", "unattempted")
CHANGES = ("moved", "copied", "deleted", "copied_source_kept")


class OrganizeError(AppError):
    stage = "planning"

    def __init__(self, code, message, paths=()):
        super().__init__(code, message, details="\n".join(str(p) for p in paths))
        self.paths = [str(p) for p in paths]


def capture_request(state: dict, action: str, parameters: dict | None = None) -> dict:
    """Snapshot root, current folder and selection at click time (mirrors ui.build_request)."""
    return {
        "action": action,
        "workshop_root": str(state["root"]),
        "destination": str(state["current"]),
        "sources": [str(p) for p in workshops.selected_sorted(state)],
        "parameters": dict(parameters or {}),
    }


def outcome(item: dict, status: str, change=None, error=None) -> dict:
    """Build one executor outcome record (shape fixed here so M3 and its consumers agree)."""
    if status not in STATUSES or (change is not None and change not in CHANGES):
        raise ValueError(f"bad outcome {status}/{change}")
    return {"source": item["source"], "destination": item.get("destination"), "kind": item["kind"],
            "status": status, "change": change, "error": error}


# ---------- shared preflight (every mutating planner uses these; M3 executor rechecks them) ----------

_LINK_TAGS = {0xA000000C, 0xA0000003}  # IO_REPARSE_TAG_SYMLINK, IO_REPARSE_TAG_MOUNT_POINT (junction)


def _is_link(path: Path) -> bool:
    """Symlink or junction, checked without following it. Other reparse points
    (OneDrive cloud placeholders) are ordinary files and stay allowed."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISLNK(st.st_mode) or getattr(st, "st_reparse_tag", 0) in _LINK_TAGS


def _check_no_links(root: Path, path: Path) -> None:
    """Reject a link/junction at path or at any folder between root and path."""
    p = path
    while p != root and root in p.parents:
        if _is_link(p):
            raise OrganizeError("link_rejected", f"{p.name} is a link or junction; organizer actions do not follow links.", [p])
        p = p.parent


def check_folder_name(raw) -> str:
    """Validate the name exactly as typed. None = cancelled. No trimming, no default."""
    if raw is None:
        raise OrganizeError("cancelled", "Cancelled. Nothing was changed.")
    if not raw.strip():
        raise OrganizeError("invalid_name", "Enter a folder name.")
    if raw != raw.strip():
        raise OrganizeError("invalid_name", f"Folder name '{raw}' has leading or trailing spaces.")
    try:  # input is already non-empty and unpadded, so the helper's strip/default cannot alter it
        return tasks.safe_folder_name(raw, default="")
    except tasks.TaskError as e:
        raise OrganizeError("invalid_name", e.message) from None


def preflight_sources(root: Path, sources) -> list[Path]:
    """Canonical, existing, in-workshop, non-root, link-free sources with parent/descendant overlap reduced."""
    if not sources:
        raise OrganizeError("empty_selection", "Select at least one file or folder.")
    paths = []
    for s in sources:
        p = Path(s)
        if not p.is_absolute():
            raise OrganizeError("bad_source", f"{s} is not an absolute path.", [s])
        _check_no_links(root, p)
        p = p.resolve()
        if p == root:
            raise OrganizeError("root_selected", "The workshop folder itself cannot be organized.", [p])
        if not workshops.is_inside(root, p):
            raise OrganizeError("outside_workshop", f"{p.name} is outside the workshop.", [p])
        if not p.exists():
            raise OrganizeError("missing_source", f"{p.name} no longer exists. Refresh and try again.", [p])
        paths.append(p)
    keys = {os.path.normcase(p) for p in paths}
    reduced, seen = [], set()
    for p in paths:  # drop anything under another selected folder; drop duplicates
        k = os.path.normcase(p)
        if k in seen or any(os.path.normcase(a) in keys for a in p.parents):
            continue
        seen.add(k)
        reduced.append(p)
    return reduced


def preflight_destination(root: Path, destination) -> Path:
    d = Path(destination)
    _check_no_links(root, d)
    d = d.resolve()
    if not d.is_dir() or not workshops.is_inside(root, d):
        raise OrganizeError("outside_workshop", "The current folder is missing or outside the workshop.", [d])
    return d


def check_not_into_self(items: list[dict]) -> None:
    """A folder may not be copied/moved to itself or inside itself (suffixes do not bypass this)."""
    bad = [i["source"] for i in items if i["kind"] == "dir"
           and (os.path.normcase(i["destination"]) == os.path.normcase(i["source"])
                or Path(os.path.normcase(i["source"])) in Path(os.path.normcase(i["destination"])).parents)]
    if bad:
        raise OrganizeError("into_itself", "A folder cannot be moved or copied into itself.", bad)


def check_unique_targets(items: list[dict]) -> None:
    """Windows case-insensitive: two items may not claim the same destination name."""
    seen, clash = {}, []
    for i in items:
        k = os.path.normcase(i["destination"])
        if k in seen:
            clash += [seen[k], i["source"]]
        seen[k] = i["source"]
    if clash:
        raise OrganizeError("name_conflict", "Two selected entries have the same name.", clash)


# ---------- planners ----------

def _plan_wrap(root: Path, request: dict) -> dict:
    name = check_folder_name(request["parameters"].get("folder_name"))
    dest = preflight_destination(root, request["destination"])
    sources = preflight_sources(root, request["sources"])
    folder = dest / name
    if os.path.lexists(folder) or any(c.name.lower() == name.lower() for c in dest.iterdir()):
        raise OrganizeError("destination_exists", f"'{name}' already exists in {dest.name}. Choose another name.", [folder])
    items = [{"source": str(p), "destination": str(folder / p.name), "kind": "dir" if p.is_dir() else "file"}
             for p in sources]
    check_not_into_self(items)
    check_unique_targets(items)
    return {"action": "wrap", "root": str(root), "destination": str(dest), "create_folder": str(folder),
            "items": items}


_PLANNERS = {"wrap": _plan_wrap}
_OWNER = {"delete": "P2-M3", "rip": "P2-M3", "copy": "P2-M3", "paste": "P2-M3", "super_wrap": "P2-M4"}


def plan_action(request: dict) -> dict:
    """Validate the whole request and return a plan; never touches the filesystem except to read it."""
    action = request.get("action")
    if action not in ACTIONS:
        raise OrganizeError("unknown_action", f"Unknown action '{action}'.")
    if action not in _PLANNERS:
        raise OrganizeError("not_implemented", f"{action} planning arrives in {_OWNER[action]}.")
    root = Path(request["workshop_root"]).resolve()
    if not root.is_dir():
        raise OrganizeError("missing_workshop", f"Workshop folder not found: {root}", [root])
    return _PLANNERS[action](root, request)


def preview(plan: dict) -> list[str]:
    """Workshop-relative 'source -> destination' lines for a confirmation dialog or log."""
    root = Path(plan["root"])
    rel = lambda p: Path(p).relative_to(root).as_posix()
    return [f"{rel(i['source'])} -> {rel(i['destination'])}" for i in plan["items"]]
