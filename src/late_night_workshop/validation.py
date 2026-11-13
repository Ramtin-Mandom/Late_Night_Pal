"""Turn untrusted model text into the only bundle the renderer accepts.

validate_bundle() checks the JSON contract for the whole bundle: expected roles, days and
counts, a non-empty latex_code per document, distinct daily notes and the planning
allocation. Any failure there rejects the entire bundle (one bundle repair in generation).
document_problems() checks one document: the static LaTeX safety rules (latex_problems) and
task-specific content (schedule day headings, file-guide coverage). Those failures, like
compile and page-count failures, get one targeted repair of that document only.
"""

import json
import re

from . import AppError

MAX_LATEX_CHARS = 200_000

# Generated bodies may not touch the preamble, files, Lua, catcodes, or build command names
# indirectly. \begin{x} runs \x, so environment names are checked against the same set.
FORBIDDEN_COMMANDS = frozenset("""
documentclass usepackage RequirePackage RequirePackageWithOptions LoadClass ProvidesPackage document
input include includeonly InputIfFileExists IfFileExists endinput openin openout read readline write
immediate newwrite newread closein closeout special everyjob everyeof
directlua latelua luaexec luadirect luacode luaescapestring luafunction
csname ifcsname UseName UseExpandableName ExpandArgs csuse csdef cslet expandafter
catcode lccode uccode scantokens scantextokens ExplSyntaxOn makeatletter
pdfextension pdfvariable pdffeedback pdfobj pdfliteral saveimageresource useimageresource includegraphics
filecontents verbatiminput lstinputlisting usetikzlibrary pgfplotstableread
""".split())
_COMMAND = re.compile(r"\\([A-Za-z]+)")
_TCOLORBOX = re.compile(r"tcb|tcolorbox|titleformat|titlespacing", re.I)  # also blocks restyling the headings
_ENVIRONMENT = re.compile(r"\\(?:begin|end)\s*\{\s*([^}]*)\}")


class ValidationError(AppError):
    stage = "validating"


def _invalid(msg: str):
    return ValidationError("invalid_response", f"The provider returned an unusable response: {msg}", retryable=True)


def latex_problems(code: str) -> list[str]:
    """Static safety check of one document body; [] when it may be compiled."""
    problems = []
    if len(code) > MAX_LATEX_CHARS:
        problems.append(f"latex_code is longer than {MAX_LATEX_CHARS} characters")
    if "^^" in code:
        problems.append("the ^^ character notation is not allowed")
    names = set(_COMMAND.findall(code)) | {n.strip().rstrip("*") for n in _ENVIRONMENT.findall(code)}
    # tcolorbox options can save or load files (saveto, record, \tcbincludegraphics...): bodies use only the
    # template's own boxes (definition, theorem, ...), never tcolorbox's commands or raw tcolorbox environment.
    bad = sorted(n for n in names if n in FORBIDDEN_COMMANDS or _TCOLORBOX.search(n))
    if bad:
        problems.append("these commands or environments are not allowed: " + ", ".join("\\" + n for n in bad))
    return problems


def plain(code: str) -> str:
    """latex_code with escaped specials undone, for finding names such as Lectures/a_b.pdf."""
    code = re.sub(r"\\(?:textunderscore|_)(?:\{\})?", "_", code)
    code = re.sub(r"\\allowbreak\b|\\-|\\[,;:! ]", "", code)
    return re.sub(r"\\([&%#$])", r"\1", code)


def document_problems(doc: dict, task: dict, sources: list[dict]) -> list[str]:
    """Per-document checks before compiling; each problem is phrased for Gemini to fix."""
    problems = latex_problems(doc["latex_code"])
    text = plain(doc["latex_code"])
    if doc["role"] == "schedule" and task["layout"]["kind"] == "schedule":
        missing = [n for n in task["expected"]["days"] if not re.search(rf"\bDay\s*~?0*{n}\b", text, re.I)]
        if missing:
            problems.append(f"the schedule has no heading for Day {missing[0]}")
    if doc["role"] == "file-guide":
        for sid in sorted(s["source_id"] for s in sources):
            if sid not in text:
                problems.append(f"the file guide does not mention the exact source label {sid}")
    return problems


def parse_document_repair(raw_text: str) -> str:
    """A targeted repair returns {"latex_code": "..."} for one document."""
    try:
        data = json.loads(raw_text or "")
    except json.JSONDecodeError:
        raise _invalid("the repaired document was not valid JSON")
    code = data.get("latex_code") if isinstance(data, dict) else None
    if not isinstance(code, str) or not code.strip():
        raise _invalid("the repaired document has no latex_code")
    return code.strip()


def parse_layout_repair(raw_text: str, count: int) -> list[str]:
    """A layout fix returns {"snippets": [{"id", "latex"}]}: a non-empty replacement for each id 1..count."""
    try:
        data = json.loads(raw_text or "")
    except json.JSONDecodeError:
        raise _invalid("the layout fix was not valid JSON")
    items = data.get("snippets") if isinstance(data, dict) else None
    by_id = {x["id"]: x["latex"] for x in (items if isinstance(items, list) else [])
             if isinstance(x, dict) and isinstance(x.get("id"), int)
             and isinstance(x.get("latex"), str) and x["latex"].strip()}
    if sorted(by_id) != list(range(1, count + 1)):
        raise _invalid("the layout fix did not return every snippet")
    return [by_id[i] for i in range(1, count + 1)]


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
        code = raw.get("latex_code")
        if not isinstance(code, str) or not code.strip():
            raise _invalid(f"{where} has no latex_code")
        docs.append({"role": role, "day": day if kind == "daily" else None, "title": title,
                     "latex_code": code.strip()})

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
        notes = [d["latex_code"] for d in docs if d["role"] == "notes"]
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

    order = {r: i for i, r in enumerate(expected.get("roles") or expected.get("roles_per_day"))}
    docs.sort(key=lambda d: (d["day"] or 0, order[d["role"]]))
    return {"documents": docs, "allocation": allocation, "sources": sorted(source_ids)}
