"""Task registry: the eight task IDs, their prompts, parameters, expected roles and layouts.

resolve_task(request, sources) -> task dict consumed by the client, validator,
renderer and publisher. Model output never chooses filenames; layouts here do.
"""

import re

from . import AppError, pdf_pages, resource_path

STYLES = {"Technical": "styles/technical.md", "Standard": "styles/standard.md", "Simple": "styles/simple.md"}
DEFAULT_STYLE = "Standard"

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

# One document's content: a LaTeX body that Python wraps in its own preamble (rendering.py).
DOCUMENT_SCHEMA_PROPERTIES = {"latex_code": {"type": "string"}}
REPAIR_SCHEMA = {"type": "object", "required": ["latex_code"], "properties": DOCUMENT_SCHEMA_PROPERTIES}


# "Use my prompt" (last in the Task list) overrides the selected task's instructions; it is not a task itself.
CUSTOM_PROMPT_ID, CUSTOM_PROMPT_LABEL = "custom-prompt", "Use my prompt"


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
    extra = {}
    if "custom_prompt" in p:  # Use my prompt: replaces the task and style instructions sent to the writer
        text = p["custom_prompt"]
        if not isinstance(text, str) or not text.strip():
            raise TaskError("invalid_parameter", "Your prompt is empty. Write what you want, then generate.")
        extra = {"custom_prompt": text.strip()}
    if spec["output_type"] == STUDY_PLAN:
        days = p.get("days")
        if isinstance(days, bool) or not isinstance(days, int) or days < 1:
            raise TaskError("invalid_parameter", "Days must be a positive whole number (1 or more).")
        return {"days": days, "folder_name": safe_folder_name(p.get("folder_name", ""), spec["default_folder"]),
                "language_style": DEFAULT_STYLE, **extra}
    style = p.get("language_style") or DEFAULT_STYLE
    if style not in STYLES:
        raise TaskError("invalid_parameter", f"Unknown language style '{style}'.")
    return {"language_style": style, **extra}


def _schema(roles: list[str], count: int) -> dict:
    doc = {"type": "object", "required": ["role", "day", "title", "latex_code"],
           "properties": {"role": {"type": "string", "enum": roles}, "day": {"type": "integer"},
                          "title": {"type": "string"}, **DOCUMENT_SCHEMA_PROPERTIES}}
    alloc = {"type": "object", "required": ["day", "topics", "workload_minutes", "source_ids"],
             "properties": {"day": {"type": "integer"}, "topics": {"type": "array", "items": {"type": "string"}},
                            "workload_minutes": {"type": "integer"},
                            "source_ids": {"type": "array", "items": {"type": "string"}}}}
    return {"type": "object", "required": ["documents", "allocation"],
            "properties": {"documents": {"type": "array", "items": doc, "minItems": count, "maxItems": count},
                           "allocation": {"type": "array", "items": alloc}}}


def package_list() -> str:
    from .rendering import ALLOWED_PACKAGES
    return ", ".join(f"{n} ({o})" if o else n for n, o in ALLOWED_PACKAGES)


def output_contract(task_id: str, params: dict) -> str:
    """What the pipeline needs back for this task, stated without its content or style instructions.
    Sent in place of prompts/<task>.md when the user's own prompt replaces them."""
    spec, days = TASKS[task_id], params.get("days")
    kind = spec["layout"]["kind"]
    roles = ", ".join(spec["roles"])
    if kind == "daily":
        return (f"Create a study plan of exactly {days} day(s). Return one allocation entry per day numbered 1 "
                f"through {days}, with topics, workload_minutes and source_ids (exact source labels); use every "
                f"source on at least one day. For each day N return exactly three documents, in this order: "
                f"{roles}, each with day set to N and a title starting with the literal prefix Day N:.")
    if kind == "schedule":
        return (f"Build a study schedule of exactly {days} day(s). Return one allocation entry per day numbered 1 "
                f"through {days}, with topics, workload_minutes and source_ids (exact source labels); use every "
                f"source at least once. Return exactly three documents, in this order, each with day set to 0: "
                f"{roles}. The schedule must name every day as Day N. The file-guide must use each exact source "
                f"label as a \\section* heading (escape underscores as \\_).")
    note = " It must fit on exactly one page." if spec.get("max_pages") == 1 else ""
    return (f"Return exactly one document with role {roles} and day 0, and an empty allocation list.{note}")


def assemble_prompt(task_id: str, params: dict, sources: list[dict]) -> str:
    spec = TASKS[task_id]
    index = "\n".join(f"- Source {i}: {s['source_id']}"
                      + (" (locally extracted text; page/slide markers in brackets"
                         + ("; scanned pages transcribed from page images, marked (transcribed from the page image)" if s.get("image_parts") else "") + ")"
                         if s.get("mode") == "text" else "")
                      + pdf_pages.mapping_note(s)
                      for i, s in enumerate(sources, 1))
    if params.get("custom_prompt"):  # the user's text replaces the task and style instructions; the contract stays
        body = (f"The student's own instructions for this {spec['label']} (follow them for content, scope and "
                f"wording):\n\n{params['custom_prompt']}")
        style = "Required output (the app needs this to build the PDF):\n" + output_contract(task_id, params)
    else:
        body = resource_path(spec["prompt_file"]).read_text(encoding="utf-8").replace("{days}", str(params.get("days", "")))
        style = resource_path("prompts/" + STYLES[params["language_style"]]).read_text(encoding="utf-8")
    fmt = resource_path("prompts/format.md").read_text(encoding="utf-8").replace("{packages}", package_list())
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
