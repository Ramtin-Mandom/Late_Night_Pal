"""Render validated document content to PDF with a local LaTeX compiler.

Model output supplies plain values only; every string is escaped before it
is placed into the packaged template, and compilation runs without shell escape.
Output stays in the caller's work_dir; the publisher picks final names.
"""

import shutil
import subprocess
from pathlib import Path

from . import AppError, resource_path

COMPILERS = ("lualatex",)  # template uses fontspec + luaotfload fallback fonts for Unicode text
COMPILE_TIMEOUT_S = 180


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


def compile_document(document: dict, work_dir: Path, name: str, subtitle: str = "") -> Path:
    """Compile {title, blocks} to work_dir/<name>.pdf and return that temporary path."""
    compiler = check_runtime()["compiler"]
    template = resource_path(f"templates/document.tex").read_text(encoding="utf-8")
    tex = (template.replace("<<TITLE>>", escape(document.get("title") or "Summary"))
                   .replace("<<SUBTITLE>>", escape(subtitle))
                   .replace("<<BODY>>", blocks_to_latex(document.get("blocks", []))))
    work_dir = Path(work_dir)
    (work_dir / f"{name}.tex").write_text(tex, encoding="utf-8")
    try:
        proc = subprocess.run(
            [compiler, "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", f"{name}.tex"],
            cwd=work_dir, capture_output=True, text=True, errors="replace", timeout=COMPILE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        raise RenderError("compile_failed", "LaTeX compilation timed out.", retryable=True)
    built = work_dir / f"{name}.pdf"
    if proc.returncode != 0 or not built.exists():
        errors = [l for l in proc.stdout.splitlines() if l.startswith("!")][:5]
        raise RenderError("compile_failed", f"Could not compile the {name} PDF.", "\n".join(errors))
    return built


def render_bundle(bundle: dict, task: dict, work_dir, subtitle: str = "") -> list[dict]:
    return [{"document_id": d["document_id"], "role": d["role"], "day": d["day"],
             "temp_path": str(compile_document(d, work_dir, d["document_id"], subtitle))}
            for d in bundle["documents"]]
