"""Deterministic local text extraction with a content-addressed cache.

    convert(path, data) -> {"converter", "units": [{"unit", "number", "text"}], "cache": "hit"|"miss"}

Units: PDF -> page (1-based), PPTX -> slide (1-based), DOCX/TXT/MD -> document (number None).
Cache key = sha256(file bytes) + converter + CONVERTER_VERSION + options, stored in local app
data (never in the workshop). Only conversions with some text are cached.
"""

import hashlib
import io
import json
from pathlib import Path

from . import AppError
from .workshops import app_data_dir

CONVERTER_VERSION = 2  # bump whenever extraction output changes (2: normalize CRLF in text files)
OPTIONS = "v1"  # bump when extraction options change


class ConversionError(AppError):
    stage = "preparing"


def _pdf(data: bytes) -> list[dict]:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return [{"unit": "page", "number": i, "text": (p.extract_text() or "").strip()}
            for i, p in enumerate(reader.pages, 1)]


def _shape_text(shape) -> list[str]:
    out = []
    if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
        out += [p for p in (para.text.strip() for para in shape.text_frame.paragraphs) if p]
    if getattr(shape, "has_table", False) and shape.has_table:
        for row in shape.table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                out.append(" | ".join(cells))
    for child in getattr(shape, "shapes", []) or []:  # group shapes
        out += _shape_text(child)
    return out


def _pptx(data: bytes) -> list[dict]:
    from pptx import Presentation
    prs = Presentation(io.BytesIO(data))
    return [{"unit": "slide", "number": i, "text": "\n".join(t for s in slide.shapes for t in _shape_text(s))}
            for i, slide in enumerate(prs.slides, 1)]


def _docx(data: bytes) -> list[dict]:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    doc = Document(io.BytesIO(data))
    lines = []
    for child in doc.element.body.iterchildren():  # body order: paragraphs and tables interleaved
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            text = Paragraph(child, doc).text.strip()
            if text:
                lines.append(text)
        elif tag == "tbl":
            for row in Table(child, doc).rows:
                cells = [c.text.strip() for c in row.cells]
                if any(cells):
                    lines.append(" | ".join(cells))
    return [{"unit": "document", "number": None, "text": "\n".join(lines)}]


def _plain(data: bytes) -> list[dict]:
    for enc in ("utf-8-sig", "utf-16"):
        try:
            if enc == "utf-16" and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
                continue
            text = data.decode(enc).replace("\r\n", "\n").replace("\r", "\n")
            return [{"unit": "document", "number": None, "text": text.strip()}]
        except UnicodeDecodeError:
            pass
    raise ConversionError("unsupported_encoding", "is not UTF-8 text. Save it as UTF-8 and try again.")


CONVERTERS = {".pdf": ("pypdf", _pdf), ".pptx": ("python-pptx", _pptx), ".docx": ("python-docx", _docx),
              ".txt": ("text", _plain), ".md": ("text", _plain)}


def supported(path) -> bool:
    return Path(path).suffix.lower() in CONVERTERS


def _cache_file(data: bytes, converter: str) -> Path:
    key = f"{hashlib.sha256(data).hexdigest()}-{converter}-v{CONVERTER_VERSION}-{OPTIONS}"
    return app_data_dir() / "conversions" / f"{key}.json"


def convert(path, data: bytes) -> dict:
    path = Path(path)
    name, fn = CONVERTERS[path.suffix.lower()]
    cache = _cache_file(data, name)
    try:
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if cached.get("version") == CONVERTER_VERSION and cached.get("units"):
            return {"converter": name, "units": cached["units"], "cache": "hit"}
    except (OSError, ValueError):
        pass
    try:
        units = fn(data)
    except ConversionError as e:
        raise ConversionError(e.code, f"{path.name} {e.message}")
    except Exception as e:  # corrupt or password-protected files
        raise ConversionError("conversion_failed", f"Could not read text from {path.name} ({type(e).__name__}).")
    if any(u["text"].strip() for u in units):  # never cache an empty/failed conversion
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"converter": name, "version": CONVERTER_VERSION, "units": units}),
                             encoding="utf-8")
        except OSError:
            pass  # cache is an optimization only
    return {"converter": name, "units": units, "cache": "miss"}
