"""Render validated document content to PDF with a local LaTeX compiler.

Model output supplies plain values only; every string is escaped before it
is placed into a packaged template, and compilation runs without shell escape.
PDFs stay in the caller's work_dir; the publisher picks final names.
"""

import shutil
import subprocess
import time
from pathlib import Path

from . import AppError, resource_path

COMPILERS = ("lualatex",)  # templates use fontspec + luaotfload fallback fonts for Unicode text
COMPILE_TIMEOUT_S = 180
# Cheat-sheet sizes (pt, leading) tried in order; 7.5pt is the readable minimum.
CHEAT_SHEET_SIZES = ((8.5, 10), (7.5, 8.8))


class RenderError(AppError):
    stage = "rendering"


def check_runtime() -> dict:
    """Return the resolved LaTeX compiler, or raise missing_latex before any paid API call."""
    for name in COMPILERS:
        path = shutil.which(name)
        if path:
            return {"compiler": path, "ready": True}
    raise RenderError(
        "missing_latex",
        "No LaTeX compiler found (need lualatex on PATH). "
        "Install MiKTeX from https://miktex.org/download, then restart the app.",
    )


_ESCAPES = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
    "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}


def escape(text: str) -> str:
    return "".join(_ESCAPES.get(ch, ch) for ch in str(text))


def blocks_to_latex(blocks: list[dict], compact: bool = False) -> str:
    section = r"\textbf" if compact else r"\section*"
    out = []
    for block in blocks:
        kind = block.get("kind")
        if kind == "heading":
            out.append(f"{section}{{{escape(block.get('text', ''))}}}" + (r"\par" if compact else ""))
        elif kind == "paragraph":
            out.append(escape(block.get("text", "")) + "\n")
        elif kind == "list":
            items = [i for i in block.get("items", []) if str(i).strip()]
            if items:
                out.append("\\begin{itemize}\n" + "\n".join(f"\\item {escape(i)}" for i in items) + "\n\\end{itemize}")
        elif kind == "question":
            out.append(f"\\noindent\\textbf{{{escape(block.get('label', ''))}}}\\quad {escape(block.get('text', ''))}\\par")
        else:
            raise RenderError("invalid_block", f"Unsupported content block: {kind!r}")
    return "\n\n".join(out)


def page_count(pdf: Path) -> int:
    from pypdf import PdfReader
    return len(PdfReader(str(pdf)).pages)


def compile_document(document: dict, work_dir: Path, name: str, subtitle: str = "",
                     template: str = "document", font=None) -> Path:
    """Compile {title, blocks} to work_dir/<name>.pdf and return that temporary path."""
    compiler = check_runtime()["compiler"]
    tex = resource_path(f"templates/{template}.tex").read_text(encoding="utf-8")
    size, leading = font or CHEAT_SHEET_SIZES[0]
    tex = (tex.replace("<<FONTSIZE>>", str(size)).replace("<<LEADING>>", str(leading))
              .replace("<<TITLE>>", escape(document.get("title") or "Document"))
              .replace("<<SUBTITLE>>", escape(subtitle))
              .replace("<<BODY>>", blocks_to_latex(document.get("blocks", []), compact=template == "cheat-sheet")))
    work_dir = Path(work_dir)
    (work_dir / f"{name}.tex").write_text(tex, encoding="utf-8")
    try:
        proc = subprocess.run(
            [compiler, "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", f"{name}.tex"],
            cwd=work_dir, capture_output=True, text=True, errors="replace", timeout=COMPILE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        raise RenderError("compile_failed", f"LaTeX compilation of {name} timed out.", retryable=True)
    built = work_dir / f"{name}.pdf"
    if proc.returncode != 0 or not built.exists():
        errors = [l for l in proc.stdout.splitlines() if l.startswith("!")][:5]
        raise RenderError("compile_failed", f"Could not compile the {name} PDF.", "\n".join(errors))
    return built


def render_bundle(bundle: dict, task: dict, work_dir, subtitle: str = "") -> list[dict]:
    """Compile every document. With task max_pages, try compact font sizes, then raise
    page_limit_exceeded (generation decides whether to ask Gemini to condense)."""
    records = []
    for d in bundle["documents"]:
        sub = f"Day {d['day']:02d} · {subtitle}" if d.get("day") else subtitle
        start = time.perf_counter()
        if task.get("max_pages"):
            for font in CHEAT_SHEET_SIZES:
                pdf = compile_document(d, work_dir, d["document_id"], sub, task["template"], font)
                pages = page_count(pdf)
                if pages <= task["max_pages"]:
                    break
            else:
                raise RenderError("page_limit_exceeded",
                                  f"The {d['document_id']} is {pages} pages at the smallest readable size; "
                                  f"it must be {task['max_pages']}.", details=str(pages))
        else:
            pdf = compile_document(d, work_dir, d["document_id"], sub, task["template"])
            pages = page_count(pdf)
        records.append({"document_id": d["document_id"], "role": d["role"], "day": d["day"],
                        "temp_path": str(pdf), "page_count": pages,
                        "seconds": round(time.perf_counter() - start, 1)})
    return records
