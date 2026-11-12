"""Compile Gemini's LaTeX document bodies to PDF in a restricted lualatex process.

Gemini supplies each document's body (`latex_code`); Python supplies the preamble (fixed
fonts and page setup plus ALLOWED_PACKAGES), the escaped title and subtitle, and the read
guard. Generated LaTeX is treated as untrusted code:
  - validation.latex_problems() rejects preamble, file, Lua and catcode commands first;
  - it is compiled in a separate lualatex process, never in the app process, with
    -no-shell-escape, in the job's empty temp folder, with an allowlisted environment
    (no GEMINI_API_KEY or other secrets), a timeout, and on Windows a job object (one
    process, no child programs, 2 GB memory, no clipboard or desktop access, killed with
    the job);
  - templates/guard.lua runs before the body and refuses reads of non-TeX files outside
    the job folder (user documents, .env), file changes outside it and program launches.
PDFs stay in the caller's work_dir; the publisher picks final names.
"""

import os
import shutil
import subprocess
import time
from datetime import date, datetime
from pathlib import Path

from . import AppError, resource_path

COMPILERS = ("lualatex",)  # templates use fontspec + luaotfload fallback fonts for Unicode text
COMPILE_TIMEOUT_S = 180  # per pass
COMPILE_PASSES = 2  # at most; the second pass runs only when LaTeX asks for a rerun (references)
SANDBOX_MEMORY_BYTES = 2 * 1024 ** 3

# The one package allowlist. The preamble loads exactly these (after the fixed fontspec,
# geometry and parskip setup), and tasks.assemble_prompt tells Gemini this list. Generated
# code cannot load anything else. All verified to load together under MiKTeX lualatex.
ALLOWED_PACKAGES = (
    ("amsmath", ""), ("amssymb", ""), ("mathtools", ""), ("siunitx", ""), ("mhchem", "version=4"),
    ("booktabs", ""), ("array", ""), ("multicol", ""), ("enumitem", ""), ("xcolor", ""), ("tikz", ""),
)

# Environment the compiler may see: enough for MiKTeX to find its install and caches.
ENV_KEEP = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "TEMP", "TMP", "USERPROFILE", "HOMEDRIVE",
            "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "ALLUSERSPROFILE", "PROGRAMFILES",
            "PROGRAMFILES(X86)", "COMMONPROGRAMFILES", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS",
            "HOME", "LANG", "TEXMFHOME", "TEXMFVAR", "TEXMFCONFIG", "TEXINPUTS"}
ENV_PREFIXES = ("MIKTEX_",)


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
    """Python-owned strings (title, subtitle) are escaped; Gemini's latex_code is not."""
    return "".join(_ESCAPES.get(ch, ch) for ch in str(text))


def one_line(text) -> str:
    """Titles sit inside command arguments, where a blank line is a LaTeX error."""
    return " ".join(str(text).split())


def preamble_packages() -> str:
    return "\n".join(f"\\usepackage[{o}]{{{n}}}" if o else f"\\usepackage{{{n}}}" for n, o in ALLOWED_PACKAGES)


def page_count(pdf: Path) -> int:
    from pypdf import PdfReader
    return len(PdfReader(str(pdf)).pages)


def sandbox_env() -> dict:
    return {k: v for k, v in os.environ.items()
            if k.upper() in ENV_KEEP or k.upper().startswith(ENV_PREFIXES)}


def _windows_job():
    """Job object: one process, no children, memory cap, no clipboard/desktop, killed on close."""
    import ctypes
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [("Basic", Basic), ("IoInfo", ctypes.c_uint64 * 6), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    job = k32.CreateJobObjectW(None, None)
    if not job:
        raise OSError(ctypes.get_last_error(), "CreateJobObject failed")
    info = Extended()
    # ACTIVE_PROCESS | PROCESS_MEMORY | DIE_ON_UNHANDLED_EXCEPTION | KILL_ON_JOB_CLOSE
    info.Basic.LimitFlags = 0x8 | 0x100 | 0x400 | 0x2000
    info.Basic.ActiveProcessLimit = 1
    info.ProcessMemoryLimit = SANDBOX_MEMORY_BYTES
    ui = wintypes.DWORD(0xFF)  # handles, clipboard read/write, system parameters, display, atoms, desktop, exit
    if not (k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
            and k32.SetInformationJobObject(job, 4, ctypes.byref(ui), ctypes.sizeof(ui))):
        err = ctypes.get_last_error()
        k32.CloseHandle(job)
        raise OSError(err, "SetInformationJobObject failed")
    return k32, job


def run_sandboxed(args: list[str], cwd, timeout: float) -> tuple[int, str]:
    """Run the compiler outside the app process with the restrictions above; (returncode, stdout)."""
    kwargs = dict(cwd=cwd, env=sandbox_env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                  stderr=subprocess.STDOUT, text=True, errors="replace")
    if os.name != "nt":
        proc = subprocess.Popen(args, **kwargs)
        job = None
    else:
        import ctypes
        k32, job = _windows_job()
        # Start suspended so the process is inside the job before it runs any instruction.
        proc = subprocess.Popen(args, creationflags=0x4 | 0x08000000, **kwargs)  # SUSPENDED | NO_WINDOW
        if not k32.AssignProcessToJobObject(job, int(proc._handle)):
            proc.kill()
            k32.CloseHandle(job)
            raise RenderError("sandbox_failed", "Could not start the restricted LaTeX process.")
        ctypes.WinDLL("ntdll").NtResumeProcess(int(proc._handle))
    try:
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, out or ""
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise
    finally:
        if job:
            k32.CloseHandle(job)  # KILL_ON_JOB_CLOSE ends anything left


def _latex_errors(log: Path) -> str:
    """The first LaTeX errors with their context lines: what Gemini needs to fix the document."""
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    out = []
    for i, line in enumerate(lines):
        if line.startswith("!") and "Emergency stop" not in line and "==> Fatal error" not in line:
            out += lines[i:i + 3]
            out += [l for l in lines[i + 3:i + 12] if l.startswith("l.")][:1]
        if len(out) >= 16:
            break
    return "\n".join(out)[:2000]


def compile_document(document: dict, work_dir: Path, name: str, subtitle: str = "",
                     template: str = "document") -> Path:
    """Compile {title, latex_code} to work_dir/<name>.pdf and return that temporary path."""
    compiler = check_runtime()["compiler"]
    tex = resource_path(f"templates/{template}.tex").read_text(encoding="utf-8")
    tex = (tex.replace("<<PACKAGES>>", preamble_packages())
              .replace("<<STYLE>>", resource_path("templates/style.tex").read_text(encoding="utf-8"))
              .replace("<<TITLE>>", escape(one_line(document.get("title") or "Document")))
              .replace("<<SUBTITLE>>", escape(subtitle))
              .replace("<<BODY>>", document["latex_code"]))
    work_dir = Path(work_dir)
    shutil.copyfile(resource_path("templates/guard.lua"), work_dir / "lnp-guard.lua")
    (work_dir / f"{name}.tex").write_text(tex, encoding="utf-8")
    built, log = work_dir / f"{name}.pdf", work_dir / f"{name}.log"
    for _ in range(COMPILE_PASSES):
        try:
            code, out = run_sandboxed(
                [compiler, "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", f"{name}.tex"],
                work_dir, COMPILE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            raise RenderError("compile_failed", f"LaTeX compilation of {name} timed out.",
                              f"Compilation took longer than {COMPILE_TIMEOUT_S} s (possible endless loop).")
        if code != 0 or not built.exists():
            # leave the .log in place: render_bundle copies it to the diagnostics folder
            raise RenderError("compile_failed", f"Could not compile the {name} PDF.",
                              _latex_errors(log) or "\n".join(out.splitlines()[-8:]))
        if "Rerun to get" not in out and "may have changed" not in out:
            break
    for extra in work_dir.glob(f"{name}.*"):  # .tex, .aux, .log, .out, .toc, ...: only the PDF stays
        if extra != built:
            extra.unlink(missing_ok=True)
    return built


def _save_diagnostic(work_dir, name: str) -> str:
    """Copy the LaTeX log (document content only; never keys or API data) to local app data."""
    from .workshops import app_data_dir
    try:
        log_dir = app_data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        target = log_dir / f"{datetime.now():%Y%m%d-%H%M%S}-{name}.log"
        src = Path(work_dir) / f"{name}.log"
        target.write_text(src.read_text(encoding="utf-8", errors="replace") if src.exists() else "(no log)",
                          encoding="utf-8")
        return str(target)
    except OSError:
        return ""


def _day_subtitle(bundle: dict, day: int, subtitle: str) -> str:
    """Daily PDFs name only that day's sources when the validated allocation lists them."""
    ids = next((a["source_ids"] for a in bundle.get("allocation") or [] if a["day"] == day), None)
    if ids:
        return f"Day {day:02d} · From {', '.join(ids)} · {date.today():%Y-%m-%d}"
    return f"Day {day:02d} · {subtitle}"


def render_bundle(bundle: dict, task: dict, work_dir, subtitle: str = "", on_document=None,
                  names: dict | None = None) -> dict:
    """Compile every document of the bundle into work_dir; never stops at the first failure.

    Returns {"records": [{document_id, role, day, temp_path, page_count, seconds}],
             "failures": {document_id: {code, message, problem, log}}}
    code is compile_failed (problem = LaTeX error lines) or page_limit_exceeded (page count
    of the compiled PDF over task max_pages). generation decides on one repair per document.
    """
    records, failures = [], {}
    total = len(bundle["documents"])
    for i, d in enumerate(bundle["documents"], 1):
        if on_document:
            on_document(i, total, d["document_id"])
        label = (names or {}).get(d["document_id"], f"{d['document_id']}.pdf")
        sub = _day_subtitle(bundle, d["day"], subtitle) if d.get("day") else subtitle
        start = time.perf_counter()
        try:
            pdf = compile_document(d, work_dir, d["document_id"], sub, task["template"])
        except RenderError as e:
            if e.code != "compile_failed":
                raise
            failures[d["document_id"]] = {"code": "compile_failed", "message": f"Couldn't compile {label}",
                                          "problem": e.details or e.message,
                                          "log": _save_diagnostic(work_dir, d["document_id"])}
            continue
        pages = page_count(pdf)
        if task.get("max_pages") and pages > task["max_pages"]:
            failures[d["document_id"]] = {
                "code": "page_limit_exceeded", "log": "",
                "message": f"{label} is {pages} pages; it must be {task['max_pages']}",
                "problem": f"The compiled PDF has {pages} pages but must have at most {task['max_pages']}."}
            pdf.unlink(missing_ok=True)
            continue
        records.append({"document_id": d["document_id"], "role": d["role"], "day": d["day"],
                        "temp_path": str(pdf), "page_count": pages,
                        "seconds": round(time.perf_counter() - start, 1)})
    return {"records": records, "failures": failures}
