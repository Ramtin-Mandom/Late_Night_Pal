"""PDF page choices (P3-M2): Qt-free parsing, validation, inspection and subset payloads.

A page choice is an ordinary value: None (All pages) or an ascending list of unique one-based
physical page numbers, e.g. [1, 3, 4]. That is what requests carry and what history can persist.

    parse_spec("3-4, 1, 4", filename)        -> [1, 3, 4]      (syntax only; None for "" = All pages)
    validate(choice, page_count, filename)   -> [1, 3, 4] | None (bounds; a list naming every page -> None)
    inspect(path) -> page count               (raises PageError for encrypted / unreadable PDFs)
    write_subset(path, pages, out_path)      -> {path, fingerprint, size, page_map}
    format_pages([1, 3, 4]) -> "1, 3-4";  describe(choice, count) -> "Pages 1, 3-4 (3 of 12)"
"""

import hashlib
import io
import re
from pathlib import Path

from . import AppError

_PART = re.compile(r"^\s*(-?\d+)\s*(?:-\s*(-?\d+)\s*)?$")


class PageError(AppError):
    stage = "validating"


def parse_spec(text, filename: str):
    """'1, 3-5, 8' -> sorted unique pages; '' or None -> None (All pages). Bounds are not known here."""
    if text is None or not str(text).strip():
        return None
    pages = set()
    for part in str(text).split(","):
        if not part.strip():
            raise PageError("invalid_pages", f"{filename}: empty item in page list \"{text}\". "
                            "Use numbers and ranges like 1, 3-5, 8.")
        m = _PART.match(part)
        if not m:
            raise PageError("invalid_pages", f"{filename}: \"{part.strip()}\" is not a page number or range. "
                            "Use numbers and ranges like 1, 3-5, 8.")
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) is not None else a
        if a < 1 or b < 1:
            raise PageError("invalid_pages", f"{filename}: page numbers start at 1 (\"{part.strip()}\").")
        if b < a:
            raise PageError("invalid_pages", f"{filename}: range \"{part.strip()}\" is reversed; write {b}-{a}.")
        pages.update(range(a, b + 1))
    return sorted(pages)


def validate(choice, page_count: int, filename: str):
    """A request's choice (None, a list, or legacy/raw text) checked against the real page count."""
    if isinstance(choice, str) or choice is None:
        pages = parse_spec(choice, filename)
    elif isinstance(choice, (list, tuple)) and all(isinstance(p, int) and not isinstance(p, bool) for p in choice):
        pages = sorted(set(choice)) or None
        if pages and pages[0] < 1:
            raise PageError("invalid_pages", f"{filename}: page numbers start at 1.")
    else:
        raise PageError("invalid_pages", f"{filename}: the page choice is not a list of page numbers.")
    if pages is None:
        return None
    if pages[-1] > page_count:
        raise PageError("invalid_pages", f"{filename} has {page_count} page{'s' * (page_count != 1)}; "
                        f"page {pages[-1]} is out of range.")
    return None if len(pages) == page_count else pages


def format_pages(pages) -> str:
    out, i = [], 0
    while i < len(pages):
        j = i
        while j + 1 < len(pages) and pages[j + 1] == pages[j] + 1:
            j += 1
        out.append(str(pages[i]) if i == j else f"{pages[i]}-{pages[j]}")
        i = j + 1
    return ", ".join(out)


def describe(choice, page_count=None) -> str:
    if choice is None:
        return f"All {page_count} pages" if page_count else "All pages"
    of = f" of {page_count}" if page_count else ""
    return f"Page{'s' * (len(choice) != 1)} {format_pages(choice)} ({len(choice)}{of})"


def _reader(data: bytes, filename: str):
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise PageError("pdf_encrypted", f"{filename} is password-protected. Save an unprotected copy "
                            "and select that file instead.")
        len(reader.pages)
        return reader
    except PageError:
        raise
    except Exception as e:  # corrupt or unsupported PDF structure
        raise PageError("pdf_unreadable", f"{filename} could not be read as a PDF ({type(e).__name__}).")


def inspect(path, data: bytes | None = None) -> int:
    """Page count; raises PageError (pdf_encrypted / pdf_unreadable) before anything is sent."""
    path = Path(path)
    return len(_reader(data if data is not None else path.read_bytes(), path.name).pages)


def write_subset(path, pages, out_path, data: bytes | None = None) -> dict:
    """A new PDF holding only `pages` (original numbers, ascending). page_map[i] is the original
    number of payload page i + 1. The fingerprint is of the written bytes, not of the source."""
    from pypdf import PdfWriter
    path = Path(path)
    reader = _reader(data if data is not None else path.read_bytes(), path.name)
    writer = PdfWriter()
    for n in pages:
        writer.add_page(reader.pages[n - 1])
    buf = io.BytesIO()
    writer.write(buf)
    payload = buf.getvalue()
    out_path = Path(out_path)
    out_path.write_bytes(payload)
    return {"path": str(out_path), "fingerprint": "sha256:" + hashlib.sha256(payload).hexdigest(),
            "size": len(payload), "page_map": list(pages)}


def mapping_note(source: dict) -> str:
    """Prompt text describing which original pages a source carries ('' for whole documents)."""
    pages = source.get("pages")
    if not pages:
        return ""
    if source.get("mode") == "original":
        pairs = ", ".join(f"{i}→{n}" for i, n in enumerate(pages, 1))
        return (f" (only original pages {format_pages(pages)} of {source.get('page_count')}; attachment page → "
                f"original page: {pairs}. Cite original page numbers)")
    return f" (only original pages {format_pages(pages)} of {source.get('page_count')}; markers use original numbers)"
