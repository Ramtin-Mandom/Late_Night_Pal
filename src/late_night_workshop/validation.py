"""Turn untrusted model text into the only bundle the renderer accepts."""

import json

from . import AppError

TEXT_KINDS = {"heading", "paragraph"}


class ValidationError(AppError):
    stage = "validating"


def _invalid(msg: str):
    return ValidationError("invalid_response", f"Gemini returned an unusable response: {msg}", retryable=True)


def validate_bundle(raw_text: str, task: dict, sources: list[dict]) -> dict:
    try:
        doc = json.loads(raw_text or "")
    except json.JSONDecodeError:
        raise _invalid("not valid JSON")
    if not isinstance(doc, dict):
        raise _invalid("expected an object")
    blocks = doc.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise _invalid("no content blocks")
    clean = []
    for b in blocks:
        if not isinstance(b, dict):
            raise _invalid("block is not an object")
        kind = b.get("kind")
        if kind in TEXT_KINDS:
            text = b.get("text")
            if isinstance(text, str) and text.strip():
                clean.append({"kind": kind, "text": text.strip()})
        elif kind == "list":
            items = [i.strip() for i in b.get("items") or [] if isinstance(i, str) and i.strip()]
            if items:
                clean.append({"kind": "list", "items": items})
        else:
            raise _invalid(f"unknown block kind {kind!r}")
    if not clean:
        raise _invalid("all blocks were empty")
    title = doc.get("title") if isinstance(doc.get("title"), str) and doc["title"].strip() else task["label"]
    role = task["expected"]["roles"][0]
    return {"documents": [{"document_id": role, "role": role, "day": None, "title": title.strip(), "blocks": clean}],
            "allocation": [], "sources": [s["source_id"] for s in sources]}
