"""Entry point: `python -m late_night_workshop` starts the Late Night Pal desktop app.

  --check            headless preflight: packaged resources + LaTeX compiler (no API call)
  --summarize FILE   headless Summary of one PDF through the shared pipeline (one API call);
                     the PDF's folder is the workshop and destination, output is summary.pdf
"""

import argparse
import sys
from pathlib import Path

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
        from . import generation
        pdf = Path(args.summarize).resolve()
        result = generation.generate(
            {"workshop_root": str(pdf.parent), "destination": str(pdf.parent), "selected_paths": [str(pdf)],
             "task_id": "summary", "parameters": {}, "efficient": False},
            lambda ev: print(ev["message"]),
        )
        if result["status"] == "ok":
            print(result["paths"][0])
            return 0
        err = result["error"]
        print(f"error [{err['code']}]: {err['message']}", file=sys.stderr)
        if err["details"].get("log"):
            print(err["details"]["log"], file=sys.stderr)
        return 1

    from . import ui
    return ui.run_app()


if __name__ == "__main__":
    sys.exit(main())
