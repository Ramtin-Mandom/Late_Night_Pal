"""Build the Windows handoff ZIP: dist/LateNightPal-win64.zip

    .venv\\Scripts\\python packaging\\build_release.py

Runs PyInstaller (one-folder), then assembles:
    Late Night Pal/
        Late Night Pal.exe, _internal/      the app (no Python install needed)
        Demo/Biology Demo Workshop/          clean demo workshop (copy it before each run)
        Demo/Example output/                 M6 rehearsal output (pre answer-label fix)
        .env.example                         placeholder for GEMINI_API_KEY
        READ ME FIRST.txt
and refuses to ship .env files, logs, caches, recents, or the developer's key.
"""

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
APP = DIST / "Late Night Pal"
STAGE = DIST / "release" / "Late Night Pal"
ZIP = DIST / "LateNightPal-win64.zip"

README = """Late Night Pal - Windows build
==============================

Requirements on this PC
  - Windows 10/11 (64-bit)
  - MiKTeX with lualatex on PATH (https://miktex.org/download). Run one compile once so
    MiKTeX finishes installing packages/fonts before the demo.
  - A Gemini API key (https://aistudio.google.com/app/apikey)

Key setup (pick one; the key is never included in this download)
  - Copy .env.example to .env in this folder (next to "Late Night Pal.exe") and put your key in it, or
  - set the GEMINI_API_KEY environment variable before launching.

Launch
  Double-click "Late Night Pal.exe".
  Optional check from a terminal:  & ".\\Late Night Pal.exe" --check

Demo
  1. Copy "Demo\\Biology Demo Workshop" somewhere (e.g. your Desktop). Use a fresh copy for each run.
  2. In the app: Open Workshop -> that copy. Select Lectures\\photosynthesis-lecture.pdf and
     Labs\\osmosis-lab-scan.pdf, open the Revision folder.
  3. Study plan -> Make daily study plan, Days 2, Folder name empty, tick Efficient, Generate.
     Click "Process original" when asked about the scan.
  4. While Gemini works, show "Demo\\Example output\\M6 Daily Study Plan (pre-fix)\\Day 01\\notes.pdf"
     (built from the scan; note the 0.8 M sucrose -> -14% result). That example predates the
     answer-label fix, so its Answers sections are unlabelled; fresh runs label them Q1, Q2, ...
  Quick single-file demo: Single file -> Summary on Lectures\\photosynthesis-lecture.pdf.
"""

FORBIDDEN_NAMES = {".env", "recents.json"}
FORBIDDEN_SUFFIXES = {".log"}
FORBIDDEN_DIRS = {"conversions", "logs", "__pycache__"}


def developer_key() -> bytes:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines() if (ROOT / ".env").exists() else []:
        if line.strip().startswith("GEMINI_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').encode()
    return os.environ.get("GEMINI_API_KEY", "").encode()


def main() -> int:
    subprocess.run([sys.executable, "-m", "PyInstaller", str(ROOT / "packaging" / "late-night-workshop.spec"),
                    "--noconfirm", "--distpath", str(DIST), "--workpath", str(ROOT / "build")], check=True)
    shutil.rmtree(STAGE.parent, ignore_errors=True)
    shutil.copytree(APP, STAGE)
    shutil.copytree(ROOT / "demo", STAGE / "Demo")
    (STAGE / ".env.example").write_text("GEMINI_API_KEY=paste-your-key-here\n# GEMINI_MODEL=gemini-3.8-flash\n",
                                        encoding="utf-8")
    (STAGE / "READ ME FIRST.txt").write_text(README, encoding="utf-8")

    key = developer_key()
    problems = []
    for path in STAGE.rglob("*"):
        rel = path.relative_to(STAGE.parent).as_posix()
        if path.name in FORBIDDEN_NAMES or path.suffix in FORBIDDEN_SUFFIXES or \
                (path.is_dir() and path.name in FORBIDDEN_DIRS and "Demo" in rel):
            problems.append(rel)
        elif key and path.is_file() and key in path.read_bytes():
            problems.append(rel + " (contains the developer API key)")
    longest = max(len(p.relative_to(STAGE.parent).as_posix()) for p in STAGE.rglob("*"))
    print(f"longest path inside the ZIP: {longest} characters (Windows limit 260 includes the extraction folder)")
    if longest > 150:
        problems.append(f"a path of {longest} characters leaves too little room for the extraction folder")
    if problems:
        print("REFUSING TO ZIP; remove:", *problems, sep="\n  ")
        return 1

    ZIP.unlink(missing_ok=True)
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(STAGE.parent.rglob("*")):
            z.write(path, path.relative_to(STAGE.parent).as_posix())
    files = sum(1 for p in STAGE.rglob("*") if p.is_file())
    print(f"built {ZIP} ({ZIP.stat().st_size / 1e6:.1f} MB, {files} files); launch 'Late Night Pal/Late Night Pal.exe'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
