"""Task registry: the eight task IDs, their prompts, parameters, expected roles and layouts.

resolve_task(request, sources) -> task dict consumed by the client, validator,
renderer and publisher. Model output never chooses filenames; layouts here do.
"""

import re

from . import AppError, resource_path

STYLES = {"Technical": "styles/technical.md", "Standard": "styles/standard.md", "Simple": "styles/simple.md"}
DEFAULT_STYLE = "Standard"
MAX_DAYS = 30

SINGLE_FILE, STUDY_PLAN = "Single file", "Study plan"

# Order here is the order shown in the UI.
TASKS = {
    "schedule": {"label": "Make schedule", "output_type": STUDY_PLAN, "prompt_file": "prompts/schedule.md",
                 "roles": ["schedule", "file-guide", "checklist"], "layout": {"kind": "schedule"},
                 "default_folder": "Study Schedule"},
    "daily-study-plan": {"label": "Make daily study plan", "output_type": STUDY_PLAN,
                         "prompt_file": "prompts/daily-study-plan.md",
                         "roles": ["notes", "sample-questions", "checklist"], "layout": {"kind": "daily"},
                         "default_folder": "Daily Study Plan"},
    "checklist": {"label": "Checklist", "output_type": SINGLE_FILE, "prompt_file": "prompts/checklist.md",
                  "roles": ["checklist"], "layout": {"kind": "single", "filename": "checklist.pdf"}},
    "notes": {"label": "Notes", "output_type": SINGLE_FILE, "prompt_file": "prompts/notes.md",
              "roles": ["notes"], "layout": {"kind": "single", "filename": "notes.pdf"}},
    "summary": {"label": "Summary", "output_type": SINGLE_FILE, "prompt_file": "prompts/summary.md",
                "roles": ["summary"], "layout": {"kind": "single", "filename": "summary.pdf"}},
    "answer-key": {"label": "Answer key", "output_type": SINGLE_FILE, "prompt_file": "prompts/answer-key.md",
                   "roles": ["answer-key"], "layout": {"kind": "single", "filename": "answer-key.pdf"}},
    "cheat-sheet": {"label": "One-page cheat sheet", "output_type": SINGLE_FILE, "prompt_file": "prompts/cheat-sheet.md",
                    "roles": ["cheat-sheet"], "layout": {"kind": "single", "filename": "cheat-sheet.pdf"},
                    "template": "cheat-sheet", "max_pages": 1},
    "sample-questions": {"label": "Sample questions", "output_type": SINGLE_FILE,
                         "prompt_file": "prompts/sample-questions.md",
                         "roles": ["sample-questions"], "layout": {"kind": "single", "filename": "sample-questions.pdf"}},
}

BLOCK_SCHEMA = {
    "type": "object",
    "required": ["kind"],
    "properties": {
        "kind": {"type": "string", "enum": ["heading", "paragraph", "list", "question"]},
        "text": {"type": "string"},
        "items": {"type": "array", "items": {"type": "string"}},
        "label": {"type": "string"},
    },
}


class TaskError(AppError):
    stage = "validating"


def tasks_for(output_type: str) -> list[tuple[str, str]]:
    return [(tid, t["label"]) for tid, t in TASKS.items() if t["output_type"] == output_type]


_BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$", re.I)


def safe_folder_name(name: str, default: str) -> str:
    name = (name or "").strip()
    if not name:
        return default
    if name in (".", "..") or _BAD_NAME.search(name) or name.endswith((".", " ")) or _RESERVED.match(name) \
            or len(name) > 100:
        raise TaskError("invalid_parameter",
                        f"Folder name '{name}' is not allowed. Avoid \\ / : * ? \" < > | and reserved names.")
    return name


def validate_parameters(task_id: str, parameters: dict) -> dict:
    """Checked, normalized parameters; raises invalid_task / invalid_parameter before any API call."""
    spec = TASKS.get(task_id)
    if not spec:
        raise TaskError("invalid_task", f"Unknown task '{task_id}'.")
    p = parameters or {}
    if spec["output_type"] == STUDY_PLAN:
        days = p.get("days")
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= MAX_DAYS:
            raise TaskError("invalid_parameter", f"Days must be a whole number from 1 to {MAX_DAYS}.")
        return {"days": days, "folder_name": safe_folder_name(p.get("folder_name", ""), spec["default_folder"]),
                "language_style": DEFAULT_STYLE}
    style = p.get("language_style") or DEFAULT_STYLE
    if style not in STYLES:
        raise TaskError("invalid_parameter", f"Unknown language style '{style}'.")
    return {"language_style": style}


def _schema(roles: list[str], count: int) -> dict:
    doc = {"type": "object", "required": ["role", "day", "title", "blocks"],
           "properties": {"role": {"type": "string", "enum": roles}, "day": {"type": "integer"},
                          "title": {"type": "string"}, "blocks": {"type": "array", "items": BLOCK_SCHEMA}}}
    alloc = {"type": "object", "required": ["day", "topics", "workload_minutes", "source_ids"],
             "properties": {"day": {"type": "integer"}, "topics": {"type": "array", "items": {"type": "string"}},
                            "workload_minutes": {"type": "integer"},
                            "source_ids": {"type": "array", "items": {"type": "string"}}}}
    return {"type": "object", "required": ["documents", "allocation"],
            "properties": {"documents": {"type": "array", "items": doc, "minItems": count, "maxItems": count},
                           "allocation": {"type": "array", "items": alloc}}}


def assemble_prompt(task_id: str, params: dict, sources: list[dict]) -> str:
    spec = TASKS[task_id]
    index = "\n".join(f"- Source {i}: {s['source_id']}" for i, s in enumerate(sources, 1))
    body = resource_path(spec["prompt_file"]).read_text(encoding="utf-8").replace("{days}", str(params.get("days", "")))
    style = resource_path("prompts/" + STYLES[params["language_style"]]).read_text(encoding="utf-8")
    fmt = resource_path("prompts/format.md").read_text(encoding="utf-8")
    return (f"You are a study assistant.\n\nAttached sources (each document is preceded by its source label):\n"
            f"{index}\n\n{body}\n\n{style}\n\n{fmt}")


def resolve_task(request: dict, sources: list[dict]) -> dict:
    task_id = request.get("task_id")
    params = validate_parameters(task_id, request.get("parameters"))
    spec = TASKS[task_id]
    days = params.get("days")
    if spec["layout"]["kind"] == "daily":
        expected = {"days": list(range(1, days + 1)), "roles_per_day": spec["roles"], "document_count": 3 * days}
    else:
        expected = {"days": list(range(1, days + 1)) if days else None, "roles": spec["roles"],
                    "document_count": len(spec["roles"])}
    layout = dict(spec["layout"])
    if spec["output_type"] == STUDY_PLAN:
        layout["folder_name"] = params["folder_name"]
    return {
        "task_id": task_id,
        "label": spec["label"],
        "parameters": params,
        "prompt": assemble_prompt(task_id, params, sources),
        "response_schema": _schema(spec["roles"], expected["document_count"]),
        "expected": expected,
        "layout": layout,
        "template": spec.get("template", "document"),
        "max_pages": spec.get("max_pages"),
    }
