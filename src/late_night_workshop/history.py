"""Generation history (P3-M3): Qt-free record construction, validation, loading and persistence.

One file per workshop, partitioned by the canonical (resolved, normcased) workshop root:
    %LOCALAPPDATA%\\late_night_workshop\\history\\<sha256(root)[:20]>.json
    {"schema": "late-night-pal/history", "version": 1, "workshop_root": "<root>", "records": [record, ...]}

Record (version 1). Every path is workshop-relative POSIX ("." = the root):
    generation_id   unique hex id, allocated once per Generate and kept through save retries
    completed_at    local ISO-8601 time with offset, taken after publication succeeded
    task_id, task_label, parameters (validated task settings), efficient
    destination     the folder captured at Generate;  output_root  the actual published folder
    inputs          [{path, mime_type, size, fingerprint, mode, pages, page_count}]
                    fingerprint = the ORIGINAL source's sha256 (never a page-subset payload's);
                    pages = None (All pages) or the normalized original page numbers
    outputs         [{document_id, role, day, path}]  final names, collision suffixes included
Excluded by construction: API keys, source contents, model responses, temp paths.

Writes are atomic (unique temp file + os.replace) and every read-modify-write runs under one
process-wide lock. save_record() is idempotent by generation_id and first-write-wins: once a
record is stored, only reconcile() changes its paths, so a late or repeated save/retry can never
bring back paths from before an organizer move (P3-M4).
reconcile(root, outcomes, before) applies confirmed organizer moves (status completed, change
moved: Move, Wrap, Rip, Super Wrap, cut-Paste, drag move, tag rename) to every stored path,
descendants included; deletions, copies and copied_source_kept leave records as they were
(a deleted path simply resolves as missing). check_reuse(root, record) validates a record
against the current files for Reuse settings without changing anything. A file that can't be used
(bad JSON, wrong schema, newer version) is never overwritten: load reports it, and the next save
moves it aside to "<name>.unreadable-<time>.json" before writing a fresh file.
"""

import hashlib
import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path, PurePosixPath

from . import AppError, inputs, pdf_pages, tasks, workshops

SCHEMA = "late-night-pal/history"
VERSION = 1
_LOCK = threading.Lock()


class HistoryError(AppError):
    stage = "history"


def new_generation_id() -> str:
    return uuid.uuid4().hex


def _key(root) -> str:
    return os.path.normcase(str(Path(root).resolve()))


def history_file(root) -> Path:
    return workshops.app_data_dir() / "history" / (hashlib.sha256(_key(root).encode("utf-8")).hexdigest()[:20] + ".json")


def _rel(root: Path, path) -> str:
    return Path(path).resolve().relative_to(root).as_posix()


def build_record(generation_id: str, root, destination, task: dict, efficient: bool, sources: list[dict],
                 rendered: list[dict], published: dict, completed_at: str | None = None) -> dict:
    """The history record of one published generation, from the pipeline's own metadata.
    rendered and published["paths"] are in the same order (outputs.publish guarantees it)."""
    root = Path(root).resolve()
    return {
        "generation_id": generation_id,
        "completed_at": completed_at or now_stamp(),
        "task_id": task["task_id"],
        "task_label": task["label"],
        "parameters": dict(task["parameters"]),
        "efficient": bool(efficient),
        "destination": _rel(root, destination),
        "output_root": _rel(root, published["output_root"]),
        "inputs": [{"path": s["relative_path"], "mime_type": s["mime_type"], "size": s["size"],
                    "fingerprint": s["fingerprint"], "mode": s["mode"],
                    "pages": list(s["pages"]) if s.get("pages") else None, "page_count": s.get("page_count")}
                   for s in sources],
        "outputs": [{"document_id": r["document_id"], "role": r["role"], "day": r.get("day"), "path": _rel(root, p)}
                    for r, p in zip(rendered, published["paths"])],
    }


def _is_rel(value) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    p = PurePosixPath(value)
    return not p.is_absolute() and ".." not in p.parts and ":" not in value


def record_problem(r) -> str | None:
    """Why a stored record can't be shown (None = valid version-1 record)."""
    if not isinstance(r, dict):
        return "not an object"
    for k, t in (("generation_id", str), ("completed_at", str), ("task_id", str), ("task_label", str),
                 ("parameters", dict), ("efficient", bool), ("inputs", list), ("outputs", list)):
        if not isinstance(r.get(k), t):
            return f"field {k} is missing or invalid"
    if not (_is_rel(r.get("destination")) and _is_rel(r.get("output_root"))):
        return "destination or output folder is not a workshop-relative path"
    for i in r["inputs"]:
        if not isinstance(i, dict) or not _is_rel(i.get("path")) or not isinstance(i.get("fingerprint"), str):
            return "an input entry is invalid"
        pages = i.get("pages")
        if pages is not None and not (isinstance(pages, list) and all(isinstance(n, int) and n >= 1 for n in pages)):
            return "an input's page choice is invalid"
    for o in r["outputs"]:
        if not isinstance(o, dict) or not _is_rel(o.get("path")) or not isinstance(o.get("document_id"), str):
            return "an output entry is invalid"
    return None


def _read(f: Path):
    """(data or None, problem or None). Missing file = empty history, not a problem."""
    try:
        raw = f.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, None
    except OSError as e:
        return None, f"could not be read ({e.strerror or e})"
    try:
        data = json.loads(raw)
    except ValueError:
        return None, "is not valid JSON"
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("records"), list):
        return None, "is not a Late Night Pal history file"
    if data.get("version") != VERSION:
        return None, f"has unsupported version {data.get('version')!r} (this app reads version {VERSION})"
    return data, None


def load(root) -> dict:
    """{"root", "records": newest first, "warnings": [str]}; never raises, never writes."""
    f = history_file(root)
    with _LOCK:
        data, problem = _read(f)
    warnings = []
    if problem:
        warnings.append(f"History for this workshop {problem}. The file was left untouched for recovery: {f}. "
                        "New generations will be saved to a fresh history file (the old one is kept beside it).")
        return {"root": str(Path(root).resolve()), "records": [], "warnings": warnings}
    records = []
    skipped = 0
    for r in (data or {}).get("records", []):
        if record_problem(r):
            skipped += 1
        else:
            records.append(r)
    if skipped:
        warnings.append(f"{skipped} history entr{'y' if skipped == 1 else 'ies'} could not be read and "
                        f"{'is' if skipped == 1 else 'are'} hidden; they stay in {f}.")
    order = {id(r): i for i, r in enumerate(records)}  # same instant: the later-saved record is newer

    def when(r):
        try:
            return datetime.fromisoformat(r["completed_at"]).timestamp()
        except (TypeError, ValueError):
            return 0.0
    records.sort(key=lambda r: (when(r), order[id(r)]), reverse=True)
    return {"root": str(Path(root).resolve()), "records": records, "warnings": warnings}


def _atomic_write(f: Path, data: dict) -> None:
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f"{f.stem}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, f)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def save_record(root, record: dict) -> dict:
    """Add (or replace, by generation_id) one record in the workshop's history.
    Returns {"file", "moved_aside": path or None}; raises HistoryError, never half-writes."""
    problem = record_problem(record)
    if problem:
        raise HistoryError("history_invalid", f"The history entry is invalid ({problem}); it was not saved.")
    f = history_file(root)
    moved = None
    with _LOCK:
        try:
            data, bad = _read(f)
            if bad:  # keep the unusable original for recovery, start a fresh file
                moved = f.with_name(f"{f.stem}.unreadable-{datetime.now():%Y%m%d-%H%M%S}.json")
                os.replace(f, moved)
                data = None
            data = data or {"schema": SCHEMA, "version": VERSION, "workshop_root": str(Path(root).resolve()),
                            "records": []}
            if any(isinstance(r, dict) and r.get("generation_id") == record["generation_id"] for r in data["records"]):
                return {"file": str(f), "moved_aside": None, "already_saved": True}  # stored paths win
            data["records"].append(record)
            _atomic_write(f, data)
        except OSError as e:
            raise HistoryError("history_not_saved", f"History could not be saved ({e.strerror or e}).",
                               retryable=True) from None
    return {"file": str(f), "moved_aside": str(moved) if moved else None, "already_saved": False}


# ---------- P3-M4: organizer reconciliation ----------
def confirmed_moves(outcomes) -> list[dict]:
    """Only completed moves change history; failed, unattempted, copies and deletions never do."""
    return [o for o in outcomes or [] if o.get("status") == "completed" and o.get("change") == "moved"
            and o.get("source") and o.get("destination")]


def _remap_rel(root: Path, rel: str, moves) -> str:
    if not _is_rel(rel):
        return rel
    old = root.joinpath(*PurePosixPath(rel).parts)
    new = workshops.remap_paths([old], moves)[0]  # moves only: remap_paths never drops here
    out = os.path.relpath(new, root).replace("\\", "/")
    return rel if out.startswith("..") or os.path.isabs(out) else out


def remap_record(record: dict, root, outcomes) -> tuple[dict, bool]:
    """A copy of record with input, destination, output-folder and output paths moved by the
    confirmed moves; ids, roles, days, page choices and fingerprints are untouched."""
    moves = confirmed_moves(outcomes)
    if not moves:
        return record, False
    root = Path(root).resolve()
    new = json.loads(json.dumps(record))
    new["destination"] = _remap_rel(root, record["destination"], moves)
    new["output_root"] = _remap_rel(root, record["output_root"], moves)
    for i in new["inputs"]:
        i["path"] = _remap_rel(root, i["path"], moves)
    for o in new["outputs"]:
        o["path"] = _remap_rel(root, o["path"], moves)
    return new, new != record


def now_stamp() -> str:
    """Local ISO-8601 time with microseconds and offset (fine enough to order a move and a save)."""
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def _after(stamp: str, before: str) -> bool:
    try:
        return datetime.fromisoformat(stamp) > datetime.fromisoformat(before)
    except (TypeError, ValueError):
        return stamp > before


def reconcile(root, outcomes, before: str | None = None) -> dict:
    """Serialized read-modify-write: apply confirmed moves to the stored records completed at or
    before `before` (default: all). {"changed": n, "warning": str|None}; raises HistoryError
    (history_not_reconciled) if the file can't be written. An unusable file is left untouched."""
    moves = confirmed_moves(outcomes)
    if not moves:
        return {"changed": 0, "warning": None}
    f = history_file(root)
    with _LOCK:
        data, bad = _read(f)
        if bad:
            return {"changed": 0, "warning": f"History for this workshop {bad}, so its paths were not updated. "
                                             f"The file was left untouched for recovery: {f}."}
        if data is None:
            return {"changed": 0, "warning": None}
        changed = 0
        for k, r in enumerate(data["records"]):
            if record_problem(r) or (before and _after(r["completed_at"], before)):
                continue  # invalid records stay as they are; newer records already use the new paths
            new, did = remap_record(r, root, moves)
            if did:
                data["records"][k] = new
                changed += 1
        if changed:
            try:
                _atomic_write(f, data)
            except OSError as e:
                raise HistoryError("history_not_reconciled", f"History paths could not be updated "
                                   f"({e.strerror or e}).", retryable=True) from None
    return {"changed": changed, "warning": None}


# ---------- P3-M4: Reuse settings ----------
def _fingerprint(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def check_input(root, entry: dict) -> dict:
    """One recorded input against the current file (hashing and PDF inspection: off the UI thread).
    status: ok | changed | missing | unusable | unsafe;  page_problem for an invalid page choice."""
    root = Path(root).resolve()
    rel, pages = entry["path"], entry.get("pages")
    path, where = resolve(root, rel)
    out = {"rel": rel, "path": str(path) if path else None, "pages": list(pages) if pages else None,
           "fingerprint": entry["fingerprint"], "current_fingerprint": None, "page_count": None,
           "page_problem": None, "status": "ok", "message": None}
    if where == "outside":
        out.update(status="unsafe", message=f"{rel} is outside the workshop or reached through a link or "
                                             "junction, so it can't be reused.")
        return out
    if where == "missing":
        out.update(status="missing", message=f"{rel} no longer exists. Remove it from Selected Inputs or "
                                              "restore the file.")
        return out
    blocked = inputs.generation_blockers([path])
    if blocked:
        out.update(status="unusable", message=f"{rel} {next(iter(blocked.values()))}.")
        return out
    try:
        out["current_fingerprint"] = _fingerprint(path)
    except OSError as e:
        out.update(status="unusable", message=f"{rel} could not be read ({e.strerror or e}).")
        return out
    if path.suffix.lower() == ".pdf":
        try:
            out["page_count"] = pdf_pages.inspect(path)
            pdf_pages.validate(pages, out["page_count"], rel)
        except pdf_pages.PageError as e:
            out["page_problem"] = e.message
    if out["current_fingerprint"] != entry["fingerprint"]:
        out.update(status="changed", message=f"{rel} changed since this generation (its contents differ). "
                                             "Accept the current file to use it, or remove it.")
    return out


def check_reuse(root, record: dict) -> dict:
    """Everything Reuse settings needs, validated against the workshop as it is now. Read-only."""
    root = Path(root).resolve()
    out = {"root": str(root), "generation_id": record["generation_id"], "task_id": record["task_id"],
           "task_label": record["task_label"], "completed_at": record["completed_at"],
           "parameters": dict(record["parameters"]), "efficient": record["efficient"], "task_problem": None,
           "inputs": [check_input(root, i) for i in record["inputs"]]}
    try:
        tasks.validate_parameters(record["task_id"], record["parameters"])
    except tasks.TaskError as e:
        out["task_problem"] = f"{record['task_label']}: {e.message}"
    except Exception as e:
        out["task_problem"] = f"{record['task_label']}: the saved settings can't be used ({type(e).__name__})."
    path, where = resolve(root, record["destination"])
    shown = "Workshop root" if record["destination"] == "." else record["destination"]
    out["destination"] = {"rel": record["destination"], "path": str(path) if path else None,
                          "problem": None if where == "available" and path.is_dir() else
                          f"The saved destination {shown} is unavailable (moved, deleted or outside the workshop)."}
    return out


def resolve(root, rel: str):
    """A stored relative path -> (Path, "available" | "missing" | "outside").
    Rechecks containment after resolve() and the browser's link rule, so a record can never
    point outside the workshop or through a link or junction."""
    root = Path(root).resolve()
    if not _is_rel(rel):
        return None, "outside"
    path = root.joinpath(*PurePosixPath(rel).parts)
    probe = root
    for part in PurePosixPath(rel).parts:  # no link anywhere along the stored path
        if part == ".":
            continue
        probe = probe / part
        if workshops.is_link(probe):
            return None, "outside"
    if not workshops.is_inside(root, path):
        return None, "outside"
    return path, ("available" if path.exists() else "missing")


def view(root) -> dict:
    """load() plus availability of every output and output folder (runs off the UI thread)."""
    result = load(root)
    for r in result["records"]:
        _, r["_output_root_status"] = resolve(root, r["output_root"])
        for o in r["outputs"]:
            _, o["_status"] = resolve(root, o["path"])
    return result
