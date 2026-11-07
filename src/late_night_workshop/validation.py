"""Turn untrusted model text into the only bundle the renderer accepts.

Checks the whole bundle against the task's expected roles, days and counts,
plus task-specific rules (schedule day headings, file-guide coverage, daily
allocation, answer-key labels). Any failure rejects the entire bundle.
"""

import json
import re

from . import AppError

TEXT_KINDS = {"heading", "paragraph"}


class ValidationError(AppError):
    stage = "validating"


def _invalid(msg: str):
    return ValidationError("invalid_response", f"Gemini returned an unusable response: {msg}", retryable=True)


def _clean_blocks(blocks, where: str) -> list[dict]:
    if not isinstance(blocks, list) or not blocks:
        raise _invalid(f"{where} has no content")
    clean = []
    for b in blocks:
        if not isinstance(b, dict):
            raise _invalid(f"{where} has a block that is not an object")
        kind = b.get("kind")
        text = b.get("text").strip() if isinstance(b.get("text"), str) else ""
        if kind in TEXT_KINDS:
            if text:
                clean.append({"kind": kind, "text": text})
        elif kind == "list":
            items = [i.strip() for i in b.get("items") or [] if isinstance(i, str) and i.strip()]
            if items:
                clean.append({"kind": "list", "items": items})
        elif kind == "question":
            label = b.get("label").strip() if isinstance(b.get("label"), str) else ""
            if not label or not text:
                raise _invalid(f"{where} has a question without a label or text")
            clean.append({"kind": "question", "label": label, "text": text})
        else:
            raise _invalid(f"{where} has unknown block kind {kind!r}")
    if not clean:
        raise _invalid(f"{where} is empty")
    return clean


def _doc_text(doc: dict) -> str:
    parts = []
    for b in doc["blocks"]:
        parts += [b.get("label", ""), b.get("text", "")] + b.get("items", [])
    return "\n".join(parts)


def _check_allocation(raw, days: list[int], source_ids: set) -> list[dict]:
    if not isinstance(raw, list):
        raise _invalid("allocation is missing")
    alloc = []
    for a in raw:
        if not isinstance(a, dict) or isinstance(a.get("day"), bool) or not isinstance(a.get("day"), int):
            raise _invalid("allocation entry without a day number")
        ids = [s for s in a.get("source_ids") or [] if isinstance(s, str)]
        unknown = [s for s in ids if s not in source_ids]
        if unknown:
            raise _invalid(f"allocation names unknown source {unknown[0]!r}")
        topics = [t.strip() for t in a.get("topics") or [] if isinstance(t, str) and t.strip()]
        minutes = a.get("workload_minutes") if isinstance(a.get("workload_minutes"), int) else 0
        alloc.append({"day": a["day"], "topics": topics, "workload_minutes": minutes, "source_ids": ids})
    if sorted(a["day"] for a in alloc) != days:
        raise _invalid(f"allocation covers days {sorted(a['day'] for a in alloc)}, expected {days}")
    unused = source_ids - {s for a in alloc for s in a["source_ids"]}
    if unused:
        raise _invalid(f"allocation never uses {sorted(unused)[0]}")
    return sorted(alloc, key=lambda a: a["day"])


def validate_bundle(raw_text: str, task: dict, sources: list[dict]) -> dict:
    try:
        data = json.loads(raw_text or "")
    except json.JSONDecodeError:
        raise _invalid("not valid JSON")
    if not isinstance(data, dict) or not isinstance(data.get("documents"), list):
        raise _invalid("no documents list")
    kind = task["layout"]["kind"]
    expected = task["expected"]
    source_ids = {s["source_id"] for s in sources}

    docs = []
    for raw in data["documents"]:
        if not isinstance(raw, dict):
            raise _invalid("document is not an object")
        role = raw.get("role")
        day = raw.get("day") if isinstance(raw.get("day"), int) and not isinstance(raw.get("day"), bool) else None
        where = f"{role} (day {day})" if kind == "daily" else str(role)
        title = raw.get("title").strip() if isinstance(raw.get("title"), str) and raw["title"].strip() else task["label"]
        docs.append({"role": role, "day": day if kind == "daily" else None, "title": title,
                     "blocks": _clean_blocks(raw.get("blocks"), where)})

    if kind == "daily":
        want = {(d, r) for d in expected["days"] for r in expected["roles_per_day"]}
        got = [(d["day"], d["role"]) for d in docs]
        if len(got) != len(set(got)):
            raise _invalid("duplicate document for the same day and role")
        if set(got) != want:
            missing = sorted(want - set(got))
            extra = sorted(set(got) - want, key=str)
            raise _invalid(f"missing {missing[0][1]} for day {missing[0][0]}" if missing
                           else f"unexpected document {extra[0][1]} for day {extra[0][0]}")
        notes = [_doc_text(d) for d in docs if d["role"] == "notes"]
        if len(notes) > 1 and len(set(notes)) < len(notes):
            raise _invalid("two days have identical notes")
        for d in docs:
            d["document_id"] = f"day-{d['day']:02d}-{d['role']}"
    else:
        roles = [d["role"] for d in docs]
        if sorted(roles) != sorted(expected["roles"]):
            raise _invalid(f"expected documents {expected['roles']}, got {roles}")
        for d in docs:
            d["document_id"] = d["role"]

    allocation = []
    if kind in ("daily", "schedule"):
        allocation = _check_allocation(data.get("allocation"), expected["days"], source_ids)
    if kind == "schedule":
        by_role = {d["role"]: d for d in docs}
        headings = [b["text"] for b in by_role["schedule"]["blocks"] if b["kind"] == "heading"]
        for n in expected["days"]:
            if not any(re.match(rf"day\s*0*{n}\b", h, re.I) for h in headings):
                raise _invalid(f"schedule has no heading for Day {n}")
        guide = _doc_text(by_role["file-guide"])
        for sid in sorted(source_ids):
            if sid not in guide:
                raise _invalid(f"file guide does not mention {sid}")
    if task["task_id"] == "answer-key":
        if not any(b["kind"] == "question" for b in docs[0]["blocks"]) and len(docs[0]["blocks"]) > 1:
            raise _invalid("answer key has no labelled answers")

    order = {r: i for i, r in enumerate(expected.get("roles") or expected.get("roles_per_day"))}
    docs.sort(key=lambda d: (d["day"] or 0, order[d["role"]]))
    return {"documents": docs, "allocation": allocation, "sources": sorted(source_ids)}
