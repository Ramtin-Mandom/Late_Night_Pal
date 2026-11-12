# PyInstaller spec: Windows one-folder build "dist/Late Night Pal/Late Night Pal.exe".
# Build (and zip with the demo) from the repository root:
#     .venv\Scripts\python packaging\build_release.py
# or just the folder:
#     .venv\Scripts\python -m PyInstaller packaging\late-night-workshop.spec --noconfirm
# The API key is NOT bundled; it is read at runtime from GEMINI_API_KEY or a .env file
# in the working directory or next to the executable.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH).parent
pkg = root / "src" / "late_night_workshop"

a = Analysis(
    [str(root / "packaging" / "launcher.py")],
    pathex=[str(root / "src")],
    datas=[(str(pkg / "prompts"), "late_night_workshop/prompts"),        # 8 task prompts, format.md, styles/
           (str(pkg / "templates"), "late_night_workshop/templates"),   # document.tex, cheat-sheet.tex, guard.lua
           (str(pkg / "assets"), "late_night_workshop/assets")]         # recent-downloads-bin.svg (Qt loads it via qsvg)
          + collect_data_files("pptx") + collect_data_files("docx"),    # converter package data (XML templates)
    hiddenimports=collect_submodules("late_night_workshop") + collect_submodules("pptx") + collect_submodules("docx")
                  + ["pypdf", "dotenv"],
    excludes=["tkinter"],
)
# Qt uses Windows' system ICU exports. An unrelated ICU on the build PATH
# (for example Poppler's version) can otherwise shadow the system DLL.
a.binaries = [entry for entry in a.binaries if Path(entry[0]).name.lower() != "icuuc.dll"]
pyz = PYZ(a.pure)
# Windowed: no console behind the app. --check/--extract/--summarize attach to the parent console.
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Late Night Pal", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="Late Night Pal")
