"""The single Gemini transport: Google GenAI SDK, Interactions API.

Reads GEMINI_API_KEY (and optional GEMINI_MODEL) from the environment or a
.env file in the working directory. The key is never logged or returned.
"""

import base64
import json
import os
from pathlib import Path

from . import resource_path

DEFAULT_MODEL = "gemini-3.8-flash"  # verified available to this project on 2026-11-07
MAX_PDF_BYTES = 50 * 1024 * 1024    # documented PDF limit (50 MB / 1000 pages)

SUMMARY_SCHEMA = {
    "type": "object",
    "required": ["title", "blocks"],
    "properties": {
        "title": {"type": "string"},
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["kind"],
                "properties": {
                    "kind": {"type": "string", "enum": ["heading", "paragraph", "list"]},
                    "text": {"type": "string"},
                    "items": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}


class GeminiError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable


def _client():
    from dotenv import load_dotenv
    from google import genai

    load_dotenv(Path.cwd() / ".env")
    if not os.getenv("GEMINI_API_KEY"):
        raise GeminiError("missing_key", "GEMINI_API_KEY is not set. Add it to your environment or a .env file.")
    return genai.Client()


def model_name() -> str:
    return os.getenv("GEMINI_MODEL") or DEFAULT_MODEL


def _sanitize(exc: Exception) -> GeminiError:
    text = str(exc)
    low = text.lower()
    if "429" in text or "quota" in low or "resource_exhausted" in low:
        return GeminiError("api_quota", "Gemini quota or rate limit reached. Wait a moment, then retry.", True)
    if "401" in text or "403" in text or "api key" in low or "permission" in low:
        return GeminiError("api_auth", "Gemini rejected the API key. Check GEMINI_API_KEY.")
    if "404" in text and "model" in low:
        return GeminiError("api_model", f"Model '{model_name()}' is not available. Set GEMINI_MODEL to an available model.")
    if any(s in low for s in ("timeout", "connect", "network", "503", "500")):
        return GeminiError("api_network", "Could not reach Gemini. Check your connection and retry.", True)
    return GeminiError("api_error", f"Gemini request failed ({type(exc).__name__}).", True)


def summarize_pdf(pdf_path: str | Path) -> dict:
    """Send one PDF (inline) with the Summary prompt; return the parsed {title, blocks} dict."""
    pdf_path = Path(pdf_path)
    data = pdf_path.read_bytes()
    if len(data) > MAX_PDF_BYTES:
        raise GeminiError("input_too_large", f"{pdf_path.name} is larger than 50 MB.")
    prompt = resource_path("prompts/summary.md").read_text(encoding="utf-8")
    client = _client()
    try:
        interaction = client.interactions.create(
            model=model_name(),
            input=[
                {"type": "document", "mime_type": "application/pdf",
                 "data": base64.b64encode(data).decode("ascii")},
                {"type": "text", "text": f"Source file: {pdf_path.name}\n\n{prompt}"},
            ],
            response_format={"type": "text", "mime_type": "application/json", "schema": SUMMARY_SCHEMA},
        )
    except Exception as exc:  # SDK raises several transport/HTTP error types
        raise _sanitize(exc) from None
    raw = interaction.output_text or ""
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        raise GeminiError("invalid_response", "Gemini returned a response that was not valid JSON.", True)
    if not isinstance(doc, dict) or not isinstance(doc.get("blocks"), list) or not doc["blocks"]:
        raise GeminiError("invalid_response", "Gemini returned an empty or malformed summary.", True)
    return doc
