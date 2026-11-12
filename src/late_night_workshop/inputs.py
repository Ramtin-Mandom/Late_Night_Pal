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
                  With capabilities["scan_images"] (Codex, which has no PDF input), a little-text
                  PDF instead stays a text source whose image_parts are JPEGs of its rendered pages
                  under MIN_CHARS_PER_PAGE, written into payload_dir; no decision is asked (codex_client
                  transcribes them before generating).
original_overrides holds source IDs the student approved for "Process original" in this job.

PDF page choices (P3-M2): page_selections maps a selected PDF's canonical path to None (All pages)
or a list of original page numbers. Each PDF is inspected first (encrypted/unreadable PDFs fail
here, before any API call) and the choice is checked against its page count. Original mode then
sends a subset PDF written into payload_dir (the generation job's temp folder): the record keeps
the source's own fingerprint/original_path for change checks and adds payload_path,
payload_fingerprint, payload_size and page_map. Text mode filters the (cached, full-file) units
to the chosen pages, keeping their original numbers; the low-text test sees only those pages.
"""

import hashlib
import mimetypes
import os
from pathlib import Path

from . import AppError, converters, pdf_pages
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
                   original_overrides=frozenset(), page_selections=None, payload_dir=None) -> dict:
    if not selected_paths:
        raise InputError("no_inputs", "Select at least one file first.")
    originals_ok = set((capabilities or {}).get("original_mime_types", [MIME[".pdf"]]))
    sources, decisions, warnings = [], [], []
    choices = {Path(k): v for k, v in (page_selections or {}).items()}
    for index, path in enumerate(selected_paths, 1):
        path = Path(path)
        ext = path.suffix.lower()
        source_id = relative(root, path)
        mime = MIME.get(ext) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = path.read_bytes()
        record = {"source_id": source_id, "filename": path.name, "relative_path": source_id, "mime_type": mime,
                  "fingerprint": "sha256:" + hashlib.sha256(data).hexdigest(), "size": len(data),
                  "mode": "original", "text_parts": [], "original_path": None, "cache": None,
                  "pages": None, "page_count": None, "image_parts": []}
        can_original = mime in originals_ok and ext not in PASS_THROUGH
        if ext == ".pdf":
            try:
                record["page_count"] = pdf_pages.inspect(path, data)
                record["pages"] = pdf_pages.validate(choices.get(path), record["page_count"], source_id)
            except pdf_pages.PageError as e:
                raise InputError(e.code, e.message if e.message.startswith(source_id) else
                                 e.message.replace(path.name, source_id, 1), source_id=source_id)
        pages = record["pages"]

        def as_original():
            record.update(mode="original", original_path=str(path))
            if pages:
                if payload_dir is None:
                    raise InputError("no_payload_dir", "Internal error: no job folder for the page subset.")
                sub = pdf_pages.write_subset(path, pages, Path(payload_dir) / f"source-{index:03d}-pages.pdf", data)
                record.update(payload_path=sub["path"], payload_fingerprint=sub["fingerprint"],
                              payload_size=sub["size"], page_map=sub["page_map"])
            sources.append(record)

        if source_id in original_overrides and can_original:
            as_original()
            continue
        if not efficient and can_original:
            as_original()
            continue
        if not converters.supported(path):
            raise InputError("unsupported_input", f"{source_id}: this file type can't be sent to the selected provider or "
                             f"converted locally. {_export_hint(ext)}", source_id=source_id)
        try:
            conv = converters.convert(path, data)
        except converters.ConversionError as e:
            raise InputError(e.code, f"{source_id}: {e.message}", source_id=source_id)
        units = conv["units"]
        if pages:
            wanted = set(pages)
            units = [u for u in units if u["unit"] == "page" and u["number"] in wanted]  # cache stays full-file
        low = _low_text_units(ext, units)
        if low and ext == ".pdf" and (capabilities or {}).get("scan_images"):
            # Image-capable provider without PDF input (Codex): attach each little-text page as a picture.
            scanned = [u["number"] for u in units if len("".join(u["text"].split())) < MIN_CHARS_PER_PAGE] \
                or pages or list(range(1, record["page_count"] + 1))
            if payload_dir is None:
                raise InputError("no_payload_dir", "Internal error: no job folder for the scanned pages.")
            try:
                images = pdf_pages.write_page_images(path, scanned, payload_dir, f"source-{index:03d}", data)
            except pdf_pages.PageError as e:
                raise InputError(e.code, e.message.replace(path.name, source_id, 1), source_id=source_id)
            record.update(mode="text", text_parts=units, cache=conv["cache"], image_parts=images)
            warnings.append({"code": "scan_images", "source_id": source_id,
                             "message": f"{source_id}: {len(scanned)} page(s) with little or no text will be read from page images."})
            sources.append(record)
            continue
        if low:
            if can_original:
                decisions.append({"source_id": source_id, "filename": path.name, "code": "needs_original",
                                  "reason": "little_text", "units": [u for u in low if u is not None],
                                  "unit_kind": units[0]["unit"] if units else "page", "pages": pages,
                                  "choices": ["process_original", "cancel"]})
                sources.append(record)  # placeholder; not sent while decisions are unresolved
                continue
            if ext == ".pdf":
                raise InputError("unsupported_input", f"{source_id}: too little extractable text. Select Gemini API in "
                                 "Settings to send the original PDF, or use an OCR copy.", source_id=source_id)
            raise InputError("unsupported_input", f"{source_id}: no usable text could be extracted, and the selected provider "
                             f"can't take this file type as an original. {_export_hint(ext)}", source_id=source_id)
        record.update(mode="text", text_parts=units, cache=conv["cache"])
        if not efficient and ext not in PASS_THROUGH:
            warnings.append({"code": "converted_locally", "source_id": source_id,
                             "message": f"{source_id} was converted to text locally (the selected provider doesn't accept "
                                        f"this file type directly)."})
        sources.append(record)
    return {"sources": sources, "decisions": decisions, "warnings": warnings}
