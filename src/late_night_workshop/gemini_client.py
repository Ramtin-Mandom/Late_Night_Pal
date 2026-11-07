"""The single Gemini transport: Google GenAI SDK, Interactions API.

Reads GEMINI_API_KEY (and optional GEMINI_MODEL) from the environment or a
.env file in the working directory. The key is never logged or returned.
"""

import base64
import hashlib
import os
import sys
from pathlib import Path

from . import AppError

DEFAULT_MODEL = "gemini-3.8-flash"  # verified available to this project on 2026-11-07
MAX_PDF_BYTES = 50 * 1024 * 1024    # documented PDF limit (50 MB / 1000 pages)


class GeminiError(AppError):
    stage = "generating"


def get_capabilities() -> dict:
    return {"original_mime_types": ["application/pdf"], "input_limit": MAX_PDF_BYTES, "structured_output": True}


def _client():
    from dotenv import load_dotenv
    from google import genai

    # Environment variables win; then .env in the working directory; then .env next to the
    # packaged executable (so a recipient can drop one beside Late Night Pal.exe).
    load_dotenv(Path.cwd() / ".env")
    if getattr(sys, "frozen", False):
        load_dotenv(Path(sys.executable).parent / ".env")
    key = (os.getenv("GEMINI_API_KEY") or "").strip().strip('"').strip("'")  # pasted keys often carry CR/quotes
    if not key:
        raise GeminiError("missing_key", "GEMINI_API_KEY is not set. Add it to your environment or a .env file.")
    return genai.Client(api_key=key)


def model_name() -> str:
    return os.getenv("GEMINI_MODEL") or DEFAULT_MODEL


def _sanitize(exc: Exception) -> GeminiError:
    text = str(exc)
    low = text.lower()
    if "429" in text or "quota" in low or "resource_exhausted" in low:
        return GeminiError("api_quota", "Gemini quota or rate limit reached. Wait a moment, then retry.", retryable=True)
    if "401" in text or "403" in text or "api key" in low or "permission" in low:
        return GeminiError("api_auth", "Gemini rejected the API key. Check GEMINI_API_KEY.")
    if "404" in text and "model" in low:
        return GeminiError("api_model", f"Model '{model_name()}' is not available. Set GEMINI_MODEL to an available model.")
    if "400" in text and ("invalid_argument" in low or "too large" in low or "too complex" in low
                          or "token" in low or "schema" in low):
        return GeminiError("api_limit", "Gemini rejected the request as too large or too complex for the model "
                           "(input size, output length or schema). Select fewer files or, for study plans, "
                           "fewer days.")
    if any(s in low for s in ("timeout", "connect", "network", "503", "500")):
        return GeminiError("api_network", "Could not reach Gemini. Check your connection and retry.", retryable=True)
    return GeminiError("api_error", f"Gemini request failed ({type(exc).__name__}).", retryable=True)


def text_source_item(i: int, s: dict) -> str:
    """Locally extracted text, attributed by source ID and page/slide number."""
    parts = [f"Source {i}: {s['source_id']} (text extracted locally from {s['filename']})"]
    for u in s["text_parts"]:
        if u["unit"] in ("page", "slide"):
            parts.append(f"[{s['source_id']} - {u['unit']} {u['number']}]")
        parts.append(u["text"] or "(no text)")
    parts.append(f"[end of {s['source_id']}]")
    return "\n".join(parts)


def _source_items(sources: list[dict]) -> list[dict]:
    """Text sources become one attributed text item; each original is preceded by a text label."""
    items, total = [], 0
    for i, s in enumerate(sources, 1):
        if s["mode"] == "text":
            text = text_source_item(i, s)
            total += len(text.encode("utf-8"))
            if total > MAX_PDF_BYTES:
                raise GeminiError("input_too_large", "Selected files are too large together. Select fewer files.")
            items.append({"type": "text", "text": text})
            continue
        data = Path(s["original_path"]).read_bytes()
        if "sha256:" + hashlib.sha256(data).hexdigest() != s["fingerprint"]:
            raise GeminiError("source_changed", f"{s['source_id']} changed after it was selected. Generate again.",
                              source_id=s["source_id"])
        total += len(data)
        if total > MAX_PDF_BYTES:
            raise GeminiError("input_too_large", "Selected PDFs exceed 50 MB together. Select fewer files.")
        items.append({"type": "text", "text": f"Source {i}: {s['source_id']}"})
        items.append({"type": "document", "mime_type": s["mime_type"], "data": base64.b64encode(data).decode("ascii")})
    return items


def generate_content(task: dict, sources: list[dict], purpose: str = "initial") -> dict:
    """One request with every source + the task prompt; returns untrusted {raw_text, usage}."""
    input_items = _source_items(sources) + [{"type": "text", "text": task["prompt"]}]
    client = _client()
    try:
        interaction = client.interactions.create(
            model=model_name(),
            input=input_items,
            response_format={"type": "text", "mime_type": "application/json", "schema": task["response_schema"]},
        )
    except Exception as exc:  # SDK raises several transport/HTTP error types
        raise _sanitize(exc) from None
    return {"raw_text": interaction.output_text or "", "usage": {}}
