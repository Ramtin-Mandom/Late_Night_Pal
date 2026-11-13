"""Workshop Markdown cache: the prepared text of each PDF, kept next to the workshop's files.

    entry_path(root, source_id)                    -> <root>/cache/<source_id with .md>
    lookup(root, source_id, fingerprint, page_count) -> {page: {"text", "kind"}} of valid pages ({} when none)
    publish(root, source_id, fingerprint, page_count, pages) -> the .md path (merged with valid pages)

Biology/Lectures/Week 2/Cells.pdf (workshop root Biology) -> Biology/cache/Lectures/Week 2/Cells.md, plus a
sidecar Cells.md.meta.json. The Markdown is readable on its own: one "## Page n" section per page in page order,
each preceded by a marker comment; a transcribed page keeps the "(transcribed from the page image)" line the
writer sees. kind is "text" (local PDF extraction) or "transcribed" (Luna read the page image, with any
extracted text kept above it).

The sidecar records the source's SHA-256 and page count, every page's kind and exact length, the extractor
and transcription versions, and the Markdown's own SHA-256. lookup() returns nothing for an entry whose source
bytes, page count, versions or Markdown no longer match (stale, edited or half-written); only the pages the
entry holds are returned, so callers convert the rest. A full entry can serve any page subset; a subset entry
only serves its own pages. publish() writes both files through temporary names and renames the Markdown first
and the sidecar last, so a reader never trusts a file it did not finish writing.
"""

import hashlib
import json
import os
import re
from pathlib import Path

FOLDER = "cache"
FORMAT = 1
KINDS = ("text", "transcribed")
_MARKER = re.compile(r"<!-- lnp-page (\d+) (text|transcribed) -->\n## Page \1\n\n")


def versions() -> dict:
    from . import codex_client, converters
    return {"extractor": f"pypdf-v{converters.CONVERTER_VERSION}-{converters.OPTIONS}",
            "transcription": f"{codex_client.READER_MODEL}-v{codex_client.TRANSCRIPTION_VERSION}"}


def entry_path(root, source_id: str) -> Path:
    return Path(root) / FOLDER / Path(source_id).with_suffix(".md")


def _sidecar(md: Path) -> Path:
    return md.with_name(md.name + ".meta.json")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def render(source_id: str, pages: dict) -> str:
    out = [f"# {source_id}\n\n"]
    for n in sorted(pages):
        out.append(f"<!-- lnp-page {n} {pages[n]['kind']} -->\n## Page {n}\n\n{pages[n]['text']}\n\n")
    return "".join(out)


def lookup(root, source_id: str, fingerprint: str, page_count: int) -> dict:
    md = entry_path(root, source_id)
    try:
        meta = json.loads(_sidecar(md).read_text(encoding="utf-8"))
        with open(md, encoding="utf-8", newline="") as f:
            text = f.read()
    except (OSError, ValueError):
        return {}
    v = versions()
    if not isinstance(meta, dict) or meta.get("format") != FORMAT or meta.get("fingerprint") != fingerprint \
            or meta.get("page_count") != page_count or meta.get("extractor") != v["extractor"] \
            or meta.get("markdown_sha256") != _sha(text):
        return {}
    pages, pos = {}, text.find("\n\n") + 2  # after the "# source" heading
    for key, info in sorted(((int(k), i) for k, i in (meta.get("pages") or {}).items()), key=lambda x: x[0]):
        m = _MARKER.match(text, pos)
        if not m or int(m.group(1)) != key or m.group(2) != info.get("kind") or info.get("kind") not in KINDS \
                or not 1 <= key <= page_count:
            return {}
        if info["kind"] == "transcribed" and meta.get("transcription") != v["transcription"]:
            return {}
        end = m.end() + int(info.get("chars", -1))
        if end < m.end() or text[end:end + 2] != "\n\n":
            return {}
        pages[key] = {"text": text[m.end():end], "kind": info["kind"]}
        pos = end + 2
    return pages if pos == len(text) else {}


def publish(root, source_id: str, fingerprint: str, page_count: int, pages: dict) -> Path:
    """Write the entry: these pages plus the still-valid pages already cached for the same file contents."""
    merged = {**lookup(root, source_id, fingerprint, page_count), **pages}
    md = entry_path(root, source_id)
    md.parent.mkdir(parents=True, exist_ok=True)
    text = render(source_id, merged)
    meta = {"format": FORMAT, "source": source_id, "fingerprint": fingerprint, "page_count": page_count,
            **versions(), "markdown_sha256": _sha(text),
            "pages": {str(n): {"kind": merged[n]["kind"], "chars": len(merged[n]["text"])} for n in sorted(merged)}}
    tmp_md, tmp_meta = md.with_name(md.name + ".tmp"), _sidecar(md).with_name(_sidecar(md).name + ".tmp")
    with open(tmp_md, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    tmp_meta.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_md, md)
    os.replace(tmp_meta, _sidecar(md))
    return md
