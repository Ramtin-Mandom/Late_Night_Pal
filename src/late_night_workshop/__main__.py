"""Entry point: `python -m late_night_workshop` starts the Late Night Pal desktop app.

  --check            headless preflight: packaged resources, LaTeX compiler, key presence (no API call)
  --extract FILE     print the local text extraction of one PDF/PPTX/DOCX/TXT/MD file (no API call)
  --summarize FILE   headless Summary of one PDF through the shared pipeline (one API call);
                     the PDF's folder is the workshop and destination, output is summary.pdf
"""

import argparse
import sys
from pathlib import Path

from . import resource_path


def _console_streams():
    """The packaged exe is windowed (no console of its own). For command-line modes, write to the
    parent console if there is one; redirected output (pipes/files) is used as-is."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        import ctypes
        if ctypes.windll.kernel32.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
            sys.stdout = sys.stdout or open("CONOUT$", "w", encoding="utf-8", errors="replace")
            sys.stderr = sys.stderr or open("CONOUT$", "w", encoding="utf-8", errors="replace")
            return
    except (AttributeError, OSError):
        pass
    import io
    sys.stdout = sys.stdout or io.StringIO()
    sys.stderr = sys.stderr or io.StringIO()


def main() -> int:
    parser = argparse.ArgumentParser(prog="late-night-workshop")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--summarize", metavar="FILE")
    parser.add_argument("--extract", metavar="FILE")
    if len(sys.argv) > 1:
        _console_streams()
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    if args.check:
        from . import rendering, tasks
        ok = True
        rels = [t["prompt_file"] for t in tasks.TASKS.values()] + ["prompts/" + s for s in tasks.STYLES.values()]
        from .ui import BIN_ICON
        for rel in rels + ["prompts/format.md", "templates/document.tex", "templates/cheat-sheet.tex", "templates/style.tex", "templates/guard.lua", BIN_ICON]:
            found = resource_path(rel).is_file()
            ok &= found
            print(f"resource {rel}: {'ok' if found else 'MISSING'}")
        from PySide6.QtGui import QImageReader  # the bin icon is SVG: Qt's qsvg plugin must be bundled
        svg = b"svg" in [bytes(f) for f in QImageReader.supportedImageFormats()]
        ok &= svg
        print(f"svg icons: {'ok' if svg else 'MISSING (qsvg plugin)'}")
        try:
            print(f"latex: {rendering.check_runtime()['compiler']}")
        except rendering.RenderError as e:
            ok = False
            print(f"latex: {e.message}")
        from .codex_client import find_cli
        from .settings import generation_method
        print(f"generation method: {generation_method()}")
        print(f"codex CLI: {find_cli() or 'not found'}")
        from . import gemini_client
        try:
            gemini_client._client()  # loads .env files; never prints the key
            print(f"gemini key: found (model {gemini_client.model_name()})")
        except gemini_client.GeminiError as e:
            print(f"gemini key: {e.message}")
        print(f"frozen build: {bool(getattr(sys, 'frozen', False))}")
        return 0 if ok else 1

    if args.extract:
        from . import converters
        path = Path(args.extract)
        if not converters.supported(path):
            print(f"unsupported file type: {path.suffix}", file=sys.stderr)
            return 1
        try:
            result = converters.convert(path, path.read_bytes())
        except converters.ConversionError as e:
            print(f"error [{e.code}]: {e.message}", file=sys.stderr)
            return 1
        print(f"converter: {result['converter']} (cache {result['cache']})")
        for u in result["units"]:
            print(f"[{u['unit']} {u['number'] or ''}] {u['text']}")
        return 0

    if args.summarize:
        from . import generation
        from .settings import generation_method
        pdf = Path(args.summarize).resolve()
        result = generation.generate(
            {"workshop_root": str(pdf.parent), "destination": str(pdf.parent), "selected_paths": [str(pdf)],
             "provider": generation_method(), "task_id": "summary", "parameters": {"language_style": "Standard"}, "efficient": False},
            lambda ev: print(ev["message"]),
        )
        if result["status"] == "ok":
            print(result["paths"][0])
            return 0
        if result["status"] == "cancelled":
            print("Cancelled during input preparation.", file=sys.stderr)
            return 1
        err = result["error"]
        print(f"error [{err['code']}]: {err['message']}", file=sys.stderr)
        if err["details"].get("log"):
            print(err["details"]["log"], file=sys.stderr)
        return 1

    from . import ui
    return ui.run_app()


if __name__ == "__main__":
    sys.exit(main())
