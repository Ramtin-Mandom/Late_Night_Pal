"""Entry point: `python -m late_night_workshop` starts the desktop app.

  --check            headless preflight: packaged resources + LaTeX compiler (no API call)
  --summarize FILE   headless run of the same PDF -> Gemini -> PDF path (makes one API call)
"""

import argparse
import sys

from . import resource_path


def main() -> int:
    parser = argparse.ArgumentParser(prog="late-night-workshop")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--summarize", metavar="FILE")
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    if args.check:
        from . import rendering
        ok = True
        for rel in ("prompts/summary.md", "templates/document.tex"):
            found = resource_path(rel).is_file()
            ok &= found
            print(f"resource {rel}: {'ok' if found else 'MISSING'}")
        try:
            print(f"latex: {rendering.check_runtime()['compiler']}")
        except rendering.RenderError as e:
            ok = False
            print(f"latex: {e.message}")
        return 0 if ok else 1

    if args.summarize:
        from . import gemini_client, rendering, ui
        try:
            print(ui.summarize_file(args.summarize, print))
            return 0
        except (gemini_client.GeminiError, rendering.RenderError) as e:
            print(f"error [{e.code}]: {e.message}", file=sys.stderr)
            if getattr(e, "details", ""):
                print(e.details, file=sys.stderr)
            return 1

    from . import ui
    return ui.run_app()


if __name__ == "__main__":
    sys.exit(main())
