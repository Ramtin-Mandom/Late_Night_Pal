"""Organizer: click-time request -> validated plan -> executed per-item outcomes.

P2-M3: Wrap, Rip, Delete (Recycle Bin), Copy (file clipboard) and Paste (copy, or an external cut
tracked per item). Super Wrap planning belongs to P2-M4. Only execute_plan() and the adapters at
the bottom change files; planners only read.

Request (built on the UI thread at click time by capture_request; later navigation cannot redirect it):
    {"action": str, "workshop_root": str, "destination": str, "sources": [str], "parameters": dict}
    - Wrap/Super Wrap {"folder_name": raw text exactly as typed, or None if cancelled}
    - Paste {"clipboard": {"paths": [str], "effect": "copy"|"cut"}} read by clipboard_read()

Plan (plan_action; raises OrganizeError naming the conflicting paths before any mutation):
    {"action", "root", "destination", "create_folder": str|None, "items": [
        {"source", "destination": str|None, "kind": "file"|"dir", "op": move|copy|cut|recycle|rmdir|clipboard,
         "identity": {is_dir, size, mtime_ns}}], "batch_id"?, "skipped"?}

Result (execute_plan): {"action", "status": ok|partial|failed, "outcomes", "created", "removed", "batch_id", "skipped"}
Outcome, one per plan item, in plan order:
    {"source", "destination", "kind", "status": completed|failed|unattempted,
     "change": None|"moved"|"copied"|"deleted"|"copied_source_kept", "error": None|{code, message}}
    - "copied_source_kept": the destination copy was made and verified but removing the source
      failed. status is "failed" (not a completed move); both paths exist.
    - Execution stops at the first failure; every later item is "unattempted".
    - workshops.reconcile(state, outcomes) applies only completed changes to the selection.
"""


import hashlib
import json
import os
import shutil
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

_is_link = workshops.is_link  # one link/junction rule shared with selection


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

def identity(path) -> dict:
    """What the executor rechecks before touching a source: it must still be the same entry."""
    st = os.lstat(path)
    return {"is_dir": os.path.isdir(path), "size": st.st_size, "mtime_ns": st.st_mtime_ns}


def _item(source: Path, destination, op: str) -> dict:
    return {"source": str(source), "destination": None if destination is None else str(destination),
            "kind": "dir" if source.is_dir() else "file", "op": op, "identity": identity(source)}


def _plan(action, root, dest, items, **extra) -> dict:
    return {"action": action, "root": str(root), "destination": None if dest is None else str(dest),
            "create_folder": None, "items": items, **extra}


def _plan_wrap(root: Path, request: dict) -> dict:
    name = check_folder_name(request["parameters"].get("folder_name"))
    dest = preflight_destination(root, request["destination"])
    sources = preflight_sources(root, request["sources"])
    folder = dest / name
    if os.path.lexists(folder) or any(c.name.lower() == name.lower() for c in dest.iterdir()):
        raise OrganizeError("destination_exists", f"'{name}' already exists in {dest.name}. Choose another name.", [folder])
    items = [_item(p, folder / p.name, "move") for p in sources]
    check_not_into_self(items)
    check_unique_targets(items)
    return _plan("wrap", root, dest, items, create_folder=str(folder))


def _plan_rip(root: Path, request: dict) -> dict:
    """Each selected folder: children -> the folder's current parent, then remove the empty folder.
    Selected files are ignored. Any clash with an existing entry or another child is refused."""
    folders = [p for p in preflight_sources(root, request["sources"]) if p.is_dir()]
    if not folders:
        raise OrganizeError("no_folders", "There were no folders to unwrap. Rip works on selected folders.")
    items, clashes = [], []
    for f in folders:
        existing = {c.name.lower() for c in f.parent.iterdir()} - {f.name.lower()}
        for child in sorted(f.iterdir(), key=lambda c: c.name.lower()):
            _check_no_links(root, child)
            if child.name.lower() in existing or child.name.lower() == f.name.lower():
                clashes.append(f.parent / child.name)
            items.append(_item(child, f.parent / child.name, "move"))
        items.append(_item(f, None, "rmdir"))
    if clashes:
        raise OrganizeError("destination_exists", "Rip would merge with or overwrite existing entries: "
                            + ", ".join(sorted({c.name for c in clashes})) + ". Rename them first.", clashes)
    check_unique_targets([i for i in items if i["destination"]])
    return _plan("rip", root, None, items)


def _plan_delete(root: Path, request: dict) -> dict:
    sources = preflight_sources(root, request["sources"])
    if not recycle_available(root):
        raise OrganizeError("recycle_unavailable",
                            "The Recycle Bin is not available for this drive, so nothing was deleted.", [root])
    return _plan("delete", root, None, [_item(p, None, "recycle") for p in sources])


def _plan_copy(root: Path, request: dict) -> dict:
    """Copy only places references on the clipboard (done by the UI); this validates them."""
    return _plan("copy", root, None, [_item(p, None, "clipboard") for p in preflight_sources(root, request["sources"])])


def _free_name(dest: Path, name: str, taken: set) -> str:
    """name, 'stem (2).ext', 'stem (3).ext', ... not used in dest or by earlier items (case-insensitive)."""
    stem, ext = (Path(name).stem, Path(name).suffix) if "." in name[1:] else (name, "")
    candidate, n = name, 1
    while candidate.lower() in taken:
        n += 1
        candidate = f"{stem} ({n}){ext}"
    taken.add(candidate.lower())
    return candidate


def _tree_links(path: Path) -> list[Path]:
    if _is_link(path):
        return [path]
    if not path.is_dir():
        return []
    found = []
    for dirpath, dirnames, filenames in os.walk(path):
        for n in dirnames + filenames:
            if _is_link(Path(dirpath) / n):
                found.append(Path(dirpath) / n)
        dirnames[:] = [d for d in dirnames if not _is_link(Path(dirpath) / d)]
    return found


def _paste_sources(clip: dict, cut: bool) -> list[Path]:
    paths = clip.get("paths") or []
    if not paths:
        raise OrganizeError("no_files", "The clipboard has no files or folders to paste.")
    out = []
    for s in paths:
        p = Path(s)
        if cut and (str(s).startswith("\\\\") or not p.is_absolute()):
            raise OrganizeError("unsafe_cut", f"{p.name} is not on a local drive. Late Night Pal can't safely track a "
                                "partial move from there, so nothing was moved. Copy it instead, or move it in Explorer.", [s])
        if not p.is_absolute() or not os.path.lexists(p):
            raise OrganizeError("missing_source", f"{p.name} is no longer available.", [s])
        links = _tree_links(p)
        if links:
            raise OrganizeError("link_rejected", f"{p.name} is or contains a link or junction; it can't be pasted.", links)
        out.append(p.resolve())
    return out


def _plan_paste(root: Path, request: dict) -> dict:
    clip = request["parameters"].get("clipboard") or {}
    cut = clip.get("effect") == "cut"
    dest = preflight_destination(root, request["destination"])
    if cut:  # a recognized earlier cut is resumed from its record, even though item 1's source is gone
        record = load_cut_record(batch_id(clip.get("paths") or []))
        if record is not None:
            return _plan_cut_retry(root, dest, batch_id(clip["paths"]), record)
    sources = _paste_sources(clip, cut)
    if cut:
        return _plan_cut(root, dest, sources)
    taken = {c.name.lower() for c in dest.iterdir()}
    items = [_item(p, dest / _free_name(dest, p.name, taken), "copy") for p in sources]
    check_not_into_self(items)
    return _plan("paste", root, dest, items)


def batch_id(sources) -> str:
    """Clipboard cut request identity: the exact ordered source list."""
    keys = [os.path.normcase(os.path.abspath(str(s))) for s in sources]
    return hashlib.sha256("|".join(["cut"] + keys).encode()).hexdigest()[:16]


def _plan_cut(root: Path, dest: Path, sources: list[Path]) -> dict:
    here = [p for p in sources if os.path.normcase(p.parent) == os.path.normcase(dest)]
    if here:
        raise OrganizeError("same_folder", "Some cut items are already in this folder; nothing was moved.", here)
    taken = {c.name.lower() for c in dest.iterdir()}
    items = [_item(p, dest / _free_name(dest, p.name, taken), "cut") for p in sources]
    check_not_into_self(items)
    return _plan("paste", root, dest, items, batch_id=batch_id(sources), skipped=[])


def _plan_cut_retry(root: Path, dest: Path, bid: str, record: dict) -> dict:
    """Retry of a recognized partial cut: only failed/unattempted items, at their reserved destinations."""
    if os.path.normcase(record["destination"]) != os.path.normcase(dest):
        raise OrganizeError("cut_elsewhere", "This cut was partly pasted into another folder. Paste it there to finish.",
                            [record["destination"]])
    kept = [r for r in record["items"] if r["change"] == "copied_source_kept"]
    if kept:
        raise OrganizeError("cut_needs_review", "A previous attempt copied an item but could not remove its source, so "
                            "both exist. Check them, delete the one you don't want, then paste again.",
                            [p for r in kept for p in (r["source"], r["destination"])])
    remaining = [r for r in record["items"] if r["status"] != "completed"]
    if not remaining:
        raise OrganizeError("cut_done", "Every item of this cut was already moved. Nothing to do.")
    items, problems = [], []
    for r in remaining:
        src = Path(r["source"])
        if not os.path.lexists(src) or _tree_links(src) or identity(src) != r["identity"]:
            problems.append(src)  # never guess: the source changed or vanished since the first attempt
        elif os.path.lexists(r["destination"]):
            problems.append(Path(r["destination"]))  # never delete a source because a destination exists
        else:
            items.append({k: r[k] for k in ("source", "destination", "kind", "identity")} | {"op": "cut"})
    if problems:
        raise OrganizeError("cut_changed", "Some remaining cut items changed or their reserved destination is now "
                            "taken, so nothing was moved. Check these paths:", problems)
    skipped = [r["source"] for r in record["items"] if r["status"] == "completed"]
    return _plan("paste", root, dest, items, batch_id=bid, skipped=skipped)


_PLANNERS = {"wrap": _plan_wrap, "rip": _plan_rip, "delete": _plan_delete, "copy": _plan_copy, "paste": _plan_paste}
_OWNER = {"super_wrap": "P2-M4"}


def plan_action(request: dict) -> dict:
    """Validate the whole request and return a plan; never changes the filesystem."""
    action = request.get("action")
    if action not in ACTIONS:
        raise OrganizeError("unknown_action", f"Unknown action '{action}'.")
    if action not in _PLANNERS:
        raise OrganizeError("not_implemented", f"{action} arrives in {_OWNER[action]}.")
    root = Path(request["workshop_root"]).resolve()
    if not root.is_dir():
        raise OrganizeError("missing_workshop", f"Workshop folder not found: {root}", [root])
    return _PLANNERS[action](root, request)


def label(plan_or_root, path) -> str:
    """Workshop-relative label, or the absolute path for external entries."""
    root = Path(plan_or_root["root"] if isinstance(plan_or_root, dict) else plan_or_root)
    try:
        return Path(path).relative_to(root).as_posix()
    except ValueError:
        return str(path)


def preview(plan: dict) -> list[str]:
    """'source -> destination' (or 'delete source') lines for a confirmation dialog or log."""
    lines = []
    for i in plan["items"]:
        if i["destination"]:
            lines.append(f"{label(plan, i['source'])} -> {label(plan, i['destination'])}")
        else:
            lines.append(f"{'remove empty' if i['op'] == 'rmdir' else 'recycle'} {label(plan, i['source'])}")
    return lines


# ---------- executor (the only code that mutates files) ----------

class _SourceKept(Exception):
    """Copy verified at the destination but the source could not be removed."""


def _tree_size(p: Path) -> tuple:
    if p.is_file():
        return (1, p.stat().st_size)
    files = [Path(d) / f for d, _, fs in os.walk(p) for f in fs]
    return (len(files), sum(f.stat().st_size for f in files))


def _copy(src: Path, dst: Path) -> None:
    """Copy and verify file count/bytes; a failed copy removes only what it created."""
    try:
        if src.is_dir():
            shutil.copytree(src, dst, symlinks=True)  # trees were checked link-free when planned
        else:
            with open(dst, "xb") as out, open(src, "rb") as inp:  # x: never overwrite
                shutil.copyfileobj(inp, out)
            shutil.copystat(src, dst)
        if _tree_size(src) != _tree_size(dst):
            raise OSError(f"copy of {src.name} did not verify")
    except FileExistsError:
        raise  # the destination was already there: it is not ours to remove
    except BaseException:
        if os.path.lexists(dst):  # created by this copy (copytree/"xb" refuse existing targets)
            shutil.rmtree(dst, ignore_errors=True) if dst.is_dir() else dst.unlink(missing_ok=True)
        raise


def _remove(p: Path) -> None:
    shutil.rmtree(p) if p.is_dir() and not _is_link(p) else p.unlink()


def _move(src: Path, dst: Path) -> None:
    """Rename on the same volume; across volumes copy, verify, then remove the source."""
    try:
        os.rename(src, dst)
        return
    except OSError as e:
        if getattr(e, "winerror", None) != 17 and e.errno != 18:  # ERROR_NOT_SAME_DEVICE / EXDEV
            raise
    _copy(src, dst)
    try:
        _remove(src)
    except OSError as e:
        raise _SourceKept(str(e)) from e


DEFAULT_OPS = {"move": lambda s, d: _move(s, d), "copy": lambda s, d: _copy(s, d),
               "recycle": lambda s, d: recycle(s), "rmdir": lambda s, d: os.rmdir(s)}


def _recheck(plan: dict, item: dict) -> None:
    """Immediately before mutating: the plan's assumptions must still hold."""
    root, src = Path(plan["root"]), Path(item["source"])
    external = item["op"] in ("copy", "cut")  # paste sources may come from outside the workshop
    if not os.path.lexists(src):
        raise OrganizeError("missing_source", f"{src.name} no longer exists.", [src])
    if _is_link(src) or (not external and (src == root or not workshops.is_inside(root, src))):
        raise OrganizeError("unsafe_source", f"{src.name} is a link or outside the workshop.", [src])
    if not external:
        _check_no_links(root, src)
    if item["op"] != "rmdir" and identity(src) != item["identity"]:
        raise OrganizeError("source_changed", f"{src.name} changed since you clicked; it was left alone.", [src])
    if item["destination"]:
        dst = Path(item["destination"])
        if os.path.lexists(dst):
            raise OrganizeError("destination_exists", f"{dst.name} already exists; nothing was overwritten.", [dst])
        if not dst.parent.is_dir() or not workshops.is_inside(root, dst.parent) or _is_link(dst.parent):
            raise OrganizeError("unsafe_destination", f"{dst.parent.name} is missing or outside the workshop.", [dst])


def execute_plan(plan: dict, ops: dict | None = None) -> dict:
    """Run a validated plan in order, stopping at the first failure.
    -> {action, status: ok|partial|failed, outcomes, created, removed, batch_id, skipped}"""
    ops = {**DEFAULT_OPS, **(ops or {})}
    outcomes, created, removed = [], [], []
    cut_record = None
    if plan.get("batch_id"):  # external cut: persist per-item state before the first change
        cut_record = load_cut_record(plan["batch_id"]) or {
            "destination": plan["destination"],
            "items": [{**{k: i[k] for k in ("source", "destination", "kind", "identity")},
                       "status": "unattempted", "change": None} for i in plan["items"]]}
        try:
            save_cut_record(plan["batch_id"], cut_record)
        except OSError as e:
            return {"action": plan["action"], "status": "failed", "created": [], "removed": [],
                    "batch_id": plan["batch_id"], "skipped": [],
                    "outcomes": [outcome(i, "unattempted") for i in plan["items"]],
                    "error": {"code": "unsafe_cut", "message": f"Could not save the move record ({e}); nothing was moved."}}
    folder = plan.get("create_folder")
    failed = False
    try:
        if folder:
            os.mkdir(folder)  # Wrap: FileExistsError if something appeared since planning
            created.append(folder)
    except OSError as e:
        failed = True
        outcomes = [outcome(plan["items"][0], "failed", error={"code": "destination_exists", "message": str(e)})]
        outcomes += [outcome(i, "unattempted") for i in plan["items"][1:]]
    for item in plan["items"] if not failed else []:
        if failed:
            outcomes.append(outcome(item, "unattempted"))
            continue
        src = Path(item["source"])
        dst = Path(item["destination"]) if item["destination"] else None
        try:
            _recheck(plan, item)
            op = "move" if item["op"] == "cut" else item["op"]
            ops[op](src, dst)
            change = {"move": "moved", "copy": "copied", "recycle": "deleted", "rmdir": "deleted"}[op]
            if op == "recycle" and os.path.lexists(src):
                raise OSError("the Recycle Bin did not take it")
            outcomes.append(outcome(item, "completed", change))
            if op == "rmdir":
                removed.append(str(src))
        except _SourceKept as e:
            failed = True
            outcomes.append(outcome(item, "failed", "copied_source_kept",
                                    {"code": "source_kept", "message": f"Copied, but the original could not be removed ({e})."}))
        except (OrganizeError, OSError) as e:
            failed = True
            msg = e.message if isinstance(e, OrganizeError) else (e.strerror or str(e))
            outcomes.append(outcome(item, "failed", None, {"code": getattr(e, "code", "io_error"), "message": msg}))
        if cut_record is not None:
            rec = next(r for r in cut_record["items"] if r["source"] == item["source"])
            rec.update(status=outcomes[-1]["status"], change=outcomes[-1]["change"])
            try:
                save_cut_record(plan["batch_id"], cut_record)
            except OSError:
                pass  # the item already happened; the report still says exactly what changed
    if folder and created and not any(o["status"] == "completed" for o in outcomes):
        try:
            os.rmdir(folder)  # remove only the empty folder this run created
            created.remove(folder)
        except OSError:
            pass
    done = sum(o["status"] == "completed" for o in outcomes)
    status = "ok" if done == len(outcomes) else ("partial" if done else "failed")
    return {"action": plan["action"], "status": status, "outcomes": outcomes, "created": created,
            "removed": removed, "batch_id": plan.get("batch_id"), "skipped": plan.get("skipped", [])}


# ---------- cut records (per clipboard request; survive restart) ----------

def _cut_file() -> Path:
    return workshops.app_data_dir() / "organizer-cuts.json"


def _load_cuts() -> dict:
    try:
        return json.loads(_cut_file().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise OrganizeError("unsafe_cut", f"The saved move records can't be read ({e}); no cut is resumed.") from None


def load_cut_record(bid: str):
    return _load_cuts().get(bid)


def save_cut_record(bid: str, record: dict) -> None:
    """Atomic replace so a crash never leaves a half-written record."""
    cuts = _load_cuts()
    cuts[bid] = record
    f = _cut_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(cuts, indent=1), encoding="utf-8")
    os.replace(tmp, f)


# ---------- OS adapters: Recycle Bin (ctypes) and file clipboard (Qt, UI thread only) ----------

def recycle_available(path) -> bool:
    """True when the drive holding path has a Recycle Bin (SHQueryRecycleBinW succeeds)."""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    class Info(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("i64Size", ctypes.c_longlong), ("i64NumItems", ctypes.c_longlong)]
    info = Info(ctypes.sizeof(Info), 0, 0)
    drive = os.path.splitdrive(str(Path(path).resolve()))[0] + "\\"
    return ctypes.windll.shell32.SHQueryRecycleBinW(drive, ctypes.byref(info)) == 0


def recycle(path) -> None:
    """Send one entry to the Recycle Bin. FOF_ALLOWUNDO recycles; FOF_WANTNUKEWARNING makes Windows ask
    instead of silently deleting permanently when an item can't be recycled."""
    import ctypes
    from ctypes import wintypes

    class Op(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]
    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI, FOF_WANTNUKEWARNING = 3, 4, 0x10, 0x40, 0x400, 0x4000
    op = Op(None, FO_DELETE, str(Path(path)) + "\0", None,
            FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI | FOF_WANTNUKEWARNING, False, None, None)
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc or op.fAnyOperationsAborted:
        raise OSError(f"Recycle Bin refused {Path(path).name} (code {rc}); it was not deleted.")


_DROP_EFFECT = 'application/x-qt-windows-mime;value="Preferred DropEffect"'
_OWN_MARK = "application/x-late-night-pal-copy"


def clipboard_put(paths) -> None:
    """Copy semantics: CF_HDROP file list + Preferred DropEffect = COPY. No data is copied now."""
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtGui import QGuiApplication
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    md.setData(_DROP_EFFECT, (1).to_bytes(4, "little"))
    md.setData(_OWN_MARK, b"1")
    QGuiApplication.clipboard().setMimeData(md)


def clipboard_read() -> dict:
    """{paths, effect: copy|cut, own}; text-only clipboard content gives no paths."""
    from PySide6.QtGui import QGuiApplication
    md = QGuiApplication.clipboard().mimeData()
    if md is None:
        return {"paths": [], "effect": "copy", "own": False}
    paths = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
    raw = bytes(md.data(_DROP_EFFECT))
    effect = "cut" if len(raw) >= 4 and int.from_bytes(raw[:4], "little") & 2 else "copy"
    return {"paths": paths, "effect": effect, "own": md.hasFormat(_OWN_MARK)}


def clipboard_after(result: dict) -> None:
    """Keep the clipboard truthful after an operation: clear a fully moved cut (no acknowledgment is
    ever written back to the source), and remap/drop our own copied references that moved or were deleted."""
    from PySide6.QtGui import QGuiApplication
    clip = clipboard_read()
    if result.get("batch_id") and result["status"] == "ok" and clip["effect"] == "cut" \
            and batch_id(clip["paths"]) == result["batch_id"]:
        QGuiApplication.clipboard().clear()
        return
    if not clip["own"]:
        return
    paths = workshops.remap_paths([Path(p) for p in clip["paths"]], result["outcomes"])
    if [str(p) for p in paths] != [str(Path(p)) for p in clip["paths"]]:
        clipboard_put(paths) if paths else QGuiApplication.clipboard().clear()
