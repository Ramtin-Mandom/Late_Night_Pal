"""Input preparation. M2: originals only (PDF). Efficient text conversion arrives in M4."""

import hashlib
from pathlib import Path

from . import AppError
from .workshops import relative

ORIGINAL_MIME_TYPES = {".pdf": "application/pdf"}


class InputError(AppError):
    stage = "preparing"


def prepare_inputs(root, selected_paths, efficient: bool = False, capabilities=None) -> dict:
    """Selected canonical paths -> {"sources": [...], "decisions": [], "warnings": []}."""
    if efficient:
        raise InputError("unsupported_mode", "Efficient mode is not available yet.")
    if not selected_paths:
        raise InputError("no_inputs", "Select at least one PDF first.")
    allowed = (capabilities or {}).get("original_mime_types") or list(ORIGINAL_MIME_TYPES.values())
    sources = []
    for path in selected_paths:
        path = Path(path)
        source_id = relative(root, path)
        mime = ORIGINAL_MIME_TYPES.get(path.suffix.lower())
        if mime not in allowed:
            raise InputError("unsupported_input", f"{source_id}: only PDF files are supported for now.",
                             source_id=source_id)
        data = path.read_bytes()
        sources.append({
            "source_id": source_id, "filename": path.name, "relative_path": source_id,
            "mime_type": mime, "fingerprint": "sha256:" + hashlib.sha256(data).hexdigest(),
            "mode": "original", "text_parts": [], "original_path": str(path), "size": len(data),
        })
    return {"sources": sources, "decisions": [], "warnings": []}
