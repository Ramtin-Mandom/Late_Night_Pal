"""Input preparation: decide original vs locally extracted text for each selected file.

    prepare_inputs(root, paths, efficient, capabilities, original_overrides=set())
        -> {"sources": [...], "decisions": [...], "warnings": [...]}

Routing
  TXT / MD          always text (passed through).
  Efficient off     original if the client supports its MIME type (PDF); otherwise local
                    conversion with a warning naming the file; otherwise unsupported_input.
  Efficient on      local conversion (PDF pages, PPTX slides, DOCX body order).
  Little text       (PDF: < 40 non-whitespace chars/page on average, or empty pages; other
                    formats: no text) -> a needs_original decision if the original is supported,
                    else unsupported_input with an export suggestion. Never sent silently.
original_overrides holds source IDs the student approved for "Process original" in this job.
"""

import hashlib
import mimetypes
import os
from pathlib import Path

from . import AppError, converters
from .workshops import relative

MIME = {
    ".pdf": "application/pdf",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain", ".md": "text/markdown",
}
PASS_THROUGH = {".txt", ".md"}
SELECTABLE = set(MIME)  # extensions Make me can use
MIN_CHARS_PER_PAGE = 40
SUPPORTED_NAMES = "PDF, PPTX, DOCX, TXT or MD"


class InputError(AppError):
    stage = "preparing"


def generation_blockers(paths) -> dict:
    """Make me eligibility: {path: reason} for each selected entry generation cannot use.
    Empty means every entry is a readable supported file. The UI only uses this for
    feedback; generation still rechecks with workshops.validate_paths()."""
    blockers = {}
    for p in map(Path, paths):
        if not os.path.lexists(p):
            blockers[p] = "no longer exists"
        elif p.is_dir():
            blockers[p] = "is a folder; Make me uses files only"
        elif p.suffix.lower() not in SELECTABLE:
            blockers[p] = f"{p.suffix or 'this'} type is not supported; use {SUPPORTED_NAMES}"
        elif not os.access(p, os.R_OK):
            blockers[p] = "cannot be read"
    return blockers


def _low_text_units(ext: str, units: list[dict]) -> list:
    if ext == ".pdf":
        counts = [len("".join(u["text"].split())) for u in units]
        empty = [u["number"] for u, c in zip(units, counts) if c == 0]
        if not counts:
            return [None]
        if empty or sum(counts) / len(counts) < MIN_CHARS_PER_PAGE:
            return empty or [u["number"] for u, c in zip(units, counts) if c < MIN_CHARS_PER_PAGE]
        return []
    return [] if any(u["text"].strip() for u in units) else [None]


def _export_hint(ext: str) -> str:
    return "Export it as a text-based PDF, DOCX or TXT and select that file instead."


def prepare_inputs(root, selected_paths, efficient: bool = False, capabilities=None,
                   original_overrides=frozenset()) -> dict:
    if not selected_paths:
        raise InputError("no_inputs", "Select at least one file first.")
    originals_ok = set((capabilities or {}).get("original_mime_types") or [MIME[".pdf"]])
    sources, decisions, warnings = [], [], []
    for path in selected_paths:
        path = Path(path)
        ext = path.suffix.lower()
        source_id = relative(root, path)
        mime = MIME.get(ext) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = path.read_bytes()
        record = {"source_id": source_id, "filename": path.name, "relative_path": source_id, "mime_type": mime,
                  "fingerprint": "sha256:" + hashlib.sha256(data).hexdigest(), "size": len(data),
                  "mode": "original", "text_parts": [], "original_path": None, "cache": None}
        can_original = mime in originals_ok and ext not in PASS_THROUGH

        def as_original():
            record.update(mode="original", original_path=str(path))
            sources.append(record)

        if source_id in original_overrides and can_original:
            as_original()
            continue
        if not efficient and can_original:
            as_original()
            continue
        if not converters.supported(path):
            raise InputError("unsupported_input", f"{source_id}: this file type can't be sent to Gemini or "
                             f"converted locally. {_export_hint(ext)}", source_id=source_id)
        try:
            conv = converters.convert(path, data)
        except converters.ConversionError as e:
            raise InputError(e.code, f"{source_id}: {e.message}", source_id=source_id)
        low = _low_text_units(ext, conv["units"])
        if low:
            if can_original:
                decisions.append({"source_id": source_id, "filename": path.name, "code": "needs_original",
                                  "reason": "little_text", "units": [u for u in low if u is not None],
                                  "unit_kind": conv["units"][0]["unit"] if conv["units"] else "page",
                                  "choices": ["process_original", "cancel"]})
                sources.append(record)  # placeholder; not sent while decisions are unresolved
                continue
            raise InputError("unsupported_input", f"{source_id}: no usable text could be extracted, and Gemini "
                             f"can't take this file type as an original. {_export_hint(ext)}", source_id=source_id)
        record.update(mode="text", text_parts=conv["units"], cache=conv["cache"])
        if not efficient and ext not in PASS_THROUGH:
            warnings.append({"code": "converted_locally", "source_id": source_id,
                             "message": f"{source_id} was converted to text locally (Gemini doesn't accept "
                                        f"this file type directly)."})
        sources.append(record)
    return {"sources": sources, "decisions": decisions, "warnings": warnings}
