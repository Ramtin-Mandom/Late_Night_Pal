"""Study progress for saved daily plans (P3-M5): Qt-free manifest, totals and persistence.

Completion is a student-controlled marker keyed by (workshop, generation_id, document_id). It lives
in its own file per workshop, next to (never inside) the History file, so a progress save can never
overwrite History records or their reconciled paths, and History updates never touch progress:
    %LOCALAPPDATA%\\late_night_workshop\\progress\\<same key as history_file>.json
    {"schema": "late-night-pal/progress", "version": 1, "workshop_root": "<root>",
     "plans": {"<generation_id>": {"<document_id>": {"done": true, "updated_at": "<iso>"}}}}
A plan or item without an entry is incomplete, so History records from before P3-M5 and new plans
start at 0/N. Totals come from the History record's outputs only (the manifest), so missing PDFs
still count and stray progress entries never change a denominator.

Writes reuse History's pattern: one process-wide lock around read-modify-write, unique temp file
+ os.replace. An unusable file (bad JSON, wrong schema, other version) is reported by load() and
left untouched; the next save moves it aside to "<name>.unreadable-<time>.json" first.
"""

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

from . import AppError, history, workshops

SCHEMA = "late-night-pal/progress"
VERSION = 1
PLAN_TASK = "daily-study-plan"
ROLES = ("notes", "sample-questions", "checklist")  # display order within a day
LABELS = {"notes": "Notes", "sample-questions": "Sample questions", "checklist": "Checklist"}
_LOCK = threading.Lock()


class ProgressError(AppError):
    stage = "progress"


def progress_file(root) -> Path:
    return workshops.app_data_dir() / "progress" / history.history_file(root).name


def manifest(record: dict) -> dict:
    """Tracked items of one daily-plan History record:
    {"days": [{"day": n, "items": [{document_id, role, label, day, path, status}]}], "total", "warnings"}.
    Each document_id counts once; outputs without a usable role/day are skipped with a warning."""
    days, seen, warnings = {}, set(), []
    for o in record.get("outputs", []):
        doc, role, day = o.get("document_id"), o.get("role"), o.get("day")
        if not isinstance(doc, str) or role not in ROLES or isinstance(day, bool) or not isinstance(day, int) or day < 1:
            warnings.append(f"An output of this plan has unusable metadata ({doc or 'no id'}); it is not tracked.")
            continue
        if doc in seen:
            warnings.append(f"{doc} is listed twice in this plan; it is counted once.")
            continue
        seen.add(doc)
        days.setdefault(day, []).append({"document_id": doc, "role": role, "label": LABELS[role], "day": day,
                                         "path": o.get("path"), "status": o.get("_status", "available")})
    out = [{"day": d, "items": sorted(items, key=lambda i: ROLES.index(i["role"]))} for d, items in sorted(days.items())]
    return {"days": out, "total": len(seen), "warnings": warnings}


def daily_plans(records) -> list[dict]:
    """The daily-study-plan records among History records (already newest first)."""
    return [r for r in records if r.get("task_id") == PLAN_TASK]


def describe_plan(record: dict) -> str:
    """Plan chooser text: output folder (its name carries the plan title) and completion time."""
    folder = "Workshop root" if record["output_root"] == "." else record["output_root"]
    return f"{folder} · {record['completed_at'].replace('T', ' ')[:16]}"


def totals(plan: dict, done: dict) -> dict:
    """{"done", "total", "days": {day: (done, total)}} from the manifest; done = {document_id: bool}."""
    days = {d["day"]: (sum(1 for i in d["items"] if done.get(i["document_id"])), len(d["items"]))
            for d in plan["days"]}
    return {"done": sum(v[0] for v in days.values()), "total": plan["total"], "days": days}


def _read(f: Path):
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
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("plans"), dict):
        return None, "is not a Late Night Pal study progress file"
    if data.get("version") != VERSION:
        return None, f"has unsupported version {data.get('version')!r} (this app reads version {VERSION})"
    return data, None


def _done_map(entries) -> dict:
    if not isinstance(entries, dict):
        return {}
    return {doc: bool(v.get("done")) for doc, v in entries.items() if isinstance(doc, str) and isinstance(v, dict)}


def load(root) -> dict:
    """{"root", "plans": {generation_id: {document_id: bool}}, "warnings"}; never raises, never writes."""
    f = progress_file(root)
    with _LOCK:
        data, problem = _read(f)
    out = {"root": str(Path(root).resolve()), "plans": {}, "warnings": []}
    if problem:
        out["warnings"].append(f"Study progress for this workshop {problem}. The file was left untouched for recovery: "
                               f"{f}. Checkboxes start empty; your next change saves a fresh file (the old one is "
                               "kept beside it).")
        return out
    out["plans"] = {gid: _done_map(e) for gid, e in ((data or {}).get("plans") or {}).items() if isinstance(gid, str)}
    return out


def _atomic_write(f: Path, data: dict) -> None:
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f"{f.stem}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, f)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def set_done(root, generation_id: str, document_id: str, done: bool) -> dict:
    """Save one checkbox. Returns {"generation_id", "document_id", "done", "moved_aside"} as stored.
    Raises ProgressError (progress_not_saved) without changing the file on failure."""
    if not (isinstance(generation_id, str) and generation_id and isinstance(document_id, str) and document_id):
        raise ProgressError("progress_invalid", "That study item has no stable id; nothing was saved.")
    f = progress_file(root)
    moved = None
    with _LOCK:
        try:
            data, bad = _read(f)
            if bad:
                moved = f.with_name(f"{f.stem}.unreadable-{datetime.now():%Y%m%d-%H%M%S}.json")
                os.replace(f, moved)
                data = None
            data = data or {"schema": SCHEMA, "version": VERSION, "workshop_root": str(Path(root).resolve()), "plans": {}}
            plan = data["plans"].setdefault(generation_id, {})
            if not isinstance(plan, dict):
                plan = data["plans"][generation_id] = {}
            plan[document_id] = {"done": bool(done), "updated_at": history.now_stamp()}
            _atomic_write(f, data)
        except OSError as e:
            raise ProgressError("progress_not_saved", f"Study progress could not be saved ({e.strerror or e}); "
                                "the checkbox shows the last saved value.", retryable=True) from None
    return {"generation_id": generation_id, "document_id": document_id, "done": bool(done),
            "moved_aside": str(moved) if moved else None}


def view(root) -> dict:
    """Everything the Study progress view needs, loaded off the UI thread:
    {"root", "plans": [record...] newest first (with output availability), "done": {gid: {doc: bool}}, "warnings"}."""
    hist = history.view(root)
    prog = load(root)
    return {"root": hist["root"], "plans": daily_plans(hist["records"]), "done": prog["plans"],
            "warnings": hist["warnings"] + prog["warnings"]}
