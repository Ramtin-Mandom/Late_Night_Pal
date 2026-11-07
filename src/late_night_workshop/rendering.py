"""Render validated document content to PDF with a local LaTeX compiler.

Model output supplies plain values only; every string is escaped before it
is placed into the packaged template, and compilation runs without shell escape.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

from . import resource_path

COMPILERS = ("lualatex",)  # template uses fontspec + luaotfload fallback fonts for Unicode text
COMPILE_TIMEOUT_S = 180


class RenderError(Exception):
    def __init__(self, code: str, message: str, details: str = ""):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details


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


def blocks_to_latex(blocks: list[dict]) -> str:
    out = []
    for block in blocks:
        kind = block.get("kind")
        if kind == "heading":
            out.append(f"\\section*{{{escape(block.get('text', ''))}}}")
        elif kind == "paragraph":
            out.append(escape(block.get("text", "")) + "\n")
        elif kind == "list":
            items = [i for i in block.get("items", []) if str(i).strip()]
            if items:
                out.append("\\begin{itemize}\n" + "\n".join(f"\\item {escape(i)}" for i in items) + "\n\\end{itemize}")
        else:
            raise RenderError("invalid_block", f"Unsupported content block: {kind!r}")
    return "\n\n".join(out)


def render_document(document: dict, out_pdf: Path, subtitle: str = "") -> Path:
    """Compile {title, blocks} into out_pdf (which must not exist). Returns out_pdf."""
    compiler = check_runtime()["compiler"]
    template = resource_path("templates/document.tex").read_text(encoding="utf-8")
    tex = (template.replace("<<TITLE>>", escape(document.get("title") or "Summary"))
                   .replace("<<SUBTITLE>>", escape(subtitle))
                   .replace("<<BODY>>", blocks_to_latex(document.get("blocks", []))))
    with tempfile.TemporaryDirectory(prefix="lnw_render_") as work:
        work_dir = Path(work)
        (work_dir / "doc.tex").write_text(tex, encoding="utf-8")
        try:
            proc = subprocess.run(
                [compiler, "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", "doc.tex"],
                cwd=work_dir, capture_output=True, text=True, errors="replace", timeout=COMPILE_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            raise RenderError("compile_failed", "LaTeX compilation timed out.")
        built = work_dir / "doc.pdf"
        if proc.returncode != 0 or not built.exists():
            errors = [l for l in proc.stdout.splitlines() if l.startswith("!")][:5]
            raise RenderError("compile_failed", "Could not compile the summary PDF.", "\n".join(errors))
        out_pdf.parent.mkdir(parents=True, exist_ok=True)
        with open(out_pdf, "xb") as f:  # exclusive create: never overwrite
            f.write(built.read_bytes())
    return out_pdf


def unique_path(path: Path) -> Path:
    """Return path, or 'name (2).pdf', 'name (3).pdf', ... for the first free name."""
    candidate, n = path, 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        n += 1
    return candidate
