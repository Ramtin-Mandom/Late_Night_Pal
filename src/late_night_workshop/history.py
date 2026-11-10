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
process-wide lock. save_record() is idempotent by generation_id. A file that can't be used
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

from . import AppError, workshops

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
        "completed_at": completed_at or datetime.now().astimezone().isoformat(timespec="seconds"),
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
    order = {id(r): i for i, r in enumerate(records)}  # same second: the later-saved record is newer
    records.sort(key=lambda r: (r["completed_at"], order[id(r)]), reverse=True)
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
            data["records"] = [r for r in data["records"]
                               if not (isinstance(r, dict) and r.get("generation_id") == record["generation_id"])]
            data["records"].append(record)
            _atomic_write(f, data)
        except OSError as e:
            raise HistoryError("history_not_saved", f"History could not be saved ({e.strerror or e}).",
                               retryable=True) from None
    return {"file": str(f), "moved_aside": str(moved) if moved else None}


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
