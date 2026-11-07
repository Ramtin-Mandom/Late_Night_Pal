# PyInstaller spec (M1 feasibility probe; full packaging is M7).
# Build from the repository root:  .venv\Scripts\python -m PyInstaller packaging\late-night-workshop.spec
# The API key is NOT bundled; it is read at runtime from GEMINI_API_KEY or a .env in the working directory.
from pathlib import Path

root = Path(SPECPATH).parent
pkg = root / "src" / "late_night_workshop"

a = Analysis(
    [str(root / "packaging" / "launcher.py")],
    pathex=[str(root / "src")],
    datas=[(str(pkg / "prompts"), "late_night_workshop/prompts"),
           (str(pkg / "templates"), "late_night_workshop/templates")],
    hiddenimports=["late_night_workshop.ui", "late_night_workshop.gemini_client", "late_night_workshop.rendering"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Late Night Pal", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="Late Night Pal")
