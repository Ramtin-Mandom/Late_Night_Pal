"""Task registry. M2 registers Summary only; the other seven tasks arrive in M3."""

from . import AppError, resource_path

BLOCK_SCHEMA = {
    "type": "object",
    "required": ["kind"],
    "properties": {
        "kind": {"type": "string", "enum": ["heading", "paragraph", "list"]},
        "text": {"type": "string"},
        "items": {"type": "array", "items": {"type": "string"}},
    },
}

TASKS = {
    "summary": {
        "label": "Summary",
        "output_type": "Single file",
        "prompt_file": "prompts/summary.md",
        "roles": ["summary"],
        "layout": {"kind": "single", "filename": "summary.pdf"},
        "template": "document",
    },
}

SINGLE_DOC_SCHEMA = {
    "type": "object",
    "required": ["title", "blocks"],
    "properties": {"title": {"type": "string"}, "blocks": {"type": "array", "items": BLOCK_SCHEMA}},
}


class TaskError(AppError):
    stage = "validating"


def resolve_task(request: dict, sources: list[dict]) -> dict:
    task_id = request.get("task_id")
    spec = TASKS.get(task_id)
    if not spec:
        raise TaskError("invalid_task", f"Task '{task_id}' is not available yet.")
    index = "\n".join(f"- Source {i}: {s['source_id']}" for i, s in enumerate(sources, 1))
    prompt = resource_path(spec["prompt_file"]).read_text(encoding="utf-8")
    return {
        "task_id": task_id,
        "label": spec["label"],
        "prompt": f"Attached sources (each document is preceded by its source label):\n{index}\n\n{prompt}",
        "response_schema": SINGLE_DOC_SCHEMA,
        "expected": {"roles": spec["roles"], "document_count": len(spec["roles"])},
        "layout": dict(spec["layout"]),
        "template": spec["template"],
        "max_pages": None,
    }
