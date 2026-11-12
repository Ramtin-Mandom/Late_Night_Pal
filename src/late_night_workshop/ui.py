"""Late Night Pal desktop UI: workshop start screen, browser + selection, task panel.

The UI owns clicks, highlights and dialogs; `workshops` owns path/selection truth and
`generation.generate()` (run on a worker thread) owns the job.
"""

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import (downloads, generation, history, inputs, name_tags, organizing, pdf_pages, resource_path, search,
               study_progress, tasks, workshops)

from .theme import COLORS

SELECTED_BG = COLORS["selected"]
SELECTED_FG = COLORS["text"]
ORGANIZE_ACTIONS = [("delete", "Delete"), ("rip", "Rip"), ("wrap", "Wrap"), ("copy", "Copy"), ("paste", "Paste"),
                    ("super_wrap", "Super Wrap")]
RIP_HELP = "Move each selected folder's contents up one level."
TAG_MIME = "application/x-late-night-pal-tag"
MOVE_MIME = "application/x-late-night-pal-move"  # browser rows; internal only (no file URLs, so Explorer can't take them)
COPY_MIME = "application/x-late-night-pal-downloads"  # Recent downloads rows
DROP_MIME = {"move": MOVE_MIME, "copy": COPY_MIME}
BIN_ICON = "assets/recent-downloads-bin.svg"


def find_chrome() -> str | None:
    """chrome.exe from the usual per-machine/per-user install folders or PATH, else None."""
    for base in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        root = os.environ.get(base)
        if root:
            exe = Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe"
            if exe.is_file():
                return str(exe)
    return shutil.which("chrome") or shutil.which("chrome.exe")


def open_pdf(path) -> bool:
    """Opens a PDF in Chrome's viewer. False when Chrome isn't installed (the caller falls back)."""
    chrome = find_chrome()
    if not chrome:
        return False
    subprocess.Popen([chrome, Path(path).resolve().as_uri()], close_fds=True)
    return True


SEARCH_DEBOUNCE_MS = 250


def record_history(workshop_root, result: dict) -> dict:
    """Save a successful result's history record (worker thread or retry). Never raises:
    {"saved": True, "note"} or {"saved": False, "message", "record"} (record kept for a retry)."""
    record = result.get("history_record")
    if record is None:
        return {"saved": False, "record": None,
                "message": result.get("history_error") or "No history entry was prepared."}
    try:
        info = history.save_record(workshop_root, record)
    except history.HistoryError as e:
        return {"saved": False, "record": record, "message": e.message}
    note = (f" The unreadable history file was kept as {info['moved_aside']}." if info.get("moved_aside") else "")
    return {"saved": True, "note": note}


def reconcile_history(workshop_root, outcomes) -> dict:
    """After an organizer run (worker thread): apply its confirmed moves to stored History.
    {"needed": False} | {"needed", "ok": True, "changed", "warning"} |
    {"needed", "ok": False, "message", "moves", "at"} (kept for a metadata-only retry)."""
    moves = history.confirmed_moves(outcomes)
    if not moves:
        return {"needed": False}
    at = history.now_stamp()
    try:
        r = history.reconcile(workshop_root, moves, before=at)
    except history.HistoryError as e:
        return {"needed": True, "ok": False, "message": e.message, "moves": moves, "at": at}
    return {"needed": True, "ok": True, "changed": r["changed"], "warning": r["warning"]}


def retry_metadata(reconciles: list, records: dict) -> dict:
    """Metadata only (no Gemini call, no file operation): first the History path updates that
    failed after organizer runs, then the records whose save failed, each in its own workshop."""
    done_reconciles, still = [], []
    for root, moves, at in reconciles:
        try:
            history.reconcile(root, moves, before=at)
            done_reconciles.append(root)
        except history.HistoryError as e:
            still.append(e.message)
    saved = {gid: record_history(root, {"history_record": rec}) for gid, (root, rec) in records.items()}
    return {"reconciled": len(done_reconciles), "failed_reconciles": still, "records": saved}


def apply_reuse(state: dict, check: dict) -> None:
    """Restore a checked History entry into the workshop state: selection (missing entries too,
    so nothing is dropped silently), Pages text, and the saved destination when it is available."""
    entries = [e for e in check["inputs"] if e["path"] and not e.get("dropped") and e["status"] != "unsafe"]
    state["selected"] = {Path(e["path"]) for e in entries}
    state["pages"] = {Path(e["path"]): pdf_pages.format_pages(e["pages"]) for e in entries if e.get("pages")}
    dest = check["destination"]
    if not dest["problem"]:
        state["current"] = Path(dest["path"])


def reuse_blockers(reuse: dict | None, state: dict) -> dict:
    """Problems of a restored History entry that need an explicit choice before Generate:
    {key: message}. Missing/unusable inputs and page problems are left to make_me_status."""
    if not reuse or not state or reuse["root"] != str(state["root"]):
        return {}
    out = {}
    if reuse["task_problem"] and not reuse.get("task_resolved"):
        out["task"] = reuse["task_problem"]
    if reuse["destination"]["problem"] and not reuse["destination"].get("resolved"):
        out["destination"] = reuse["destination"]["problem"]
    for e in reuse["inputs"]:
        if e["status"] == "unsafe" and not e.get("dropped"):
            out["input:" + e["rel"]] = e["message"]
        elif e["status"] == "changed" and not e.get("accepted") and e["path"] and Path(e["path"]) in state["selected"]:
            out["input:" + e["rel"]] = e["message"]
    return out


def describe_saved(result: dict) -> str:
    """Status after a successful Generate: saved paths, then whether History was updated."""
    if len(result["paths"]) == 1:
        text = "Saved: " + result["paths"][0]
    else:
        root = Path(result["output_root"])
        text = f"Saved {len(result['paths'])} PDFs in {root}:\n" + "\n".join(
            Path(p).relative_to(root).as_posix() for p in result["paths"])
    h = result.get("history") or {}
    if h.get("saved"):
        text += "\nAdded to History." + h.get("note", "")
    elif h:
        text += (f"\nThe PDFs above were saved, but History was not updated: {h['message']}"
                 + ("\nUse Retry saving history; generation will not run again." if h.get("record") else ""))
    if result.get("warnings"):
        text += "\n" + "\n".join(w["message"] for w in result["warnings"])
    return text


def describe_history_record(r: dict) -> str:
    """One History row: task and time, inputs with page choices, settings, outputs."""
    when = r["completed_at"].replace("T", " ")[:16]
    inputs = ", ".join(i["path"] + (f" (pages {pdf_pages.format_pages(i['pages'])})" if i.get("pages") else "")
                       for i in r["inputs"])
    params = r["parameters"]
    settings = [f"{params['language_style']} style"] if params.get("language_style") else []
    if params.get("days"):
        settings.append(f"{params['days']} day{'s' * (params['days'] != 1)}")
    settings.append("Efficient on" if r["efficient"] else "Efficient off")
    settings.append("Save to: " + ("Workshop root" if r["destination"] == "." else r["destination"]))
    missing = sum(1 for o in r["outputs"] if o.get("_status", "available") != "available")
    n = len(r["outputs"])
    where = "Workshop root" if r["output_root"] == "." else r["output_root"]
    outputs = f"{n} PDF{'s' * (n != 1)} in {where}" + (f" ({missing} unavailable)" if missing else "")
    return f"{r['task_label']} · {when}\nInputs: {inputs}\n{' · '.join(settings)}\nOutputs: {outputs}"


def describe_history_output(o: dict) -> str:
    day = f", day {o['day']}" if o.get("day") else ""
    state = "" if o.get("_status", "available") == "available" else "  (unavailable: moved or deleted)"
    return f"{o['path']}  ·  {o['role']}{day}{state}"


def search_is_current(request: dict, state: dict | None, query: str, seq: int) -> bool:
    """A finished search may be shown only if it is the newest request, for the workshop that is
    open now and the query in the box now (a late or previous-workshop response is dropped)."""
    return (state is not None and request["seq"] == seq and request["root"] == state["root"]
            and request["query"] == query.strip())


def describe_search(result: dict) -> str:
    n = len(result["matches"])
    return f"Search: {n} match{'es' * (n != 1)} for \u201c{result['query']}\u201d"


def describe_download(record: dict) -> str:
    """Tray row: filename, where it was saved, and Chrome's completion time (local clock)."""
    p = Path(record["path"])
    return f"{p.name}   ·   {p.parent}   ·   {time.strftime('%H:%M', time.localtime(record['downloaded_at']))}"
ACTION_VERB = {"move": "Move", "rename": "Name tag", "wrap": "Wrap", "super_wrap": "Super Wrap", "rip": "Rip", "delete": "Delete", "paste": "Paste", "copy": "Copy"}
EFFICIENT_NOTE = ("Converts files to text before sending them to Gemini. This can be much cheaper for some files, "
                  "but diagrams, equations, tables, and formatting may be lost.")


STAGE_LABELS = {"preparing": "Preparing", "awaiting_input": "Waiting for you", "generating": "Generating",
                "validating": "Checking", "rendering": "Rendering", "publishing": "Saving"}
FAILED_STAGE = {"preparing": "Preparing inputs", "validating": "Checking the request or response",
                "generating": "Generation request", "rendering": "Local PDF compilation", "publishing": "Saving"}
NEXT_STEP = {
    "compile_failed": "Click Generate to try again; a fresh response usually compiles. The LaTeX log is listed below.",
    "invalid_response": "Click Generate to try again. If it keeps failing, try fewer files or a different task.",
    "page_limit_exceeded": "Select less material, or use Notes/Summary instead of a one-page cheat sheet.",
    "api_quota": "Wait a minute, then click Generate again.",
    "api_network": "Check your internet connection, then click Generate again.",
    "api_auth": "Fix GEMINI_API_KEY in .env or your environment, restart the app, then Generate.",
    "missing_key": "Add GEMINI_API_KEY to .env or your environment, restart the app, then Generate.",
    "api_model": "Set GEMINI_MODEL to an available model, restart the app, then Generate.",
    "api_limit": "Select fewer files or fewer days, then Generate.",
    "missing_latex": "Install MiKTeX (lualatex), restart the app, then Generate.",
    "invalid_parameter": "Fix the highlighted setting, then Generate.",
    "publish_failed": "Check the output folder is writable, then Generate again.",
}


def describe_progress(event: dict) -> str:
    return f"{STAGE_LABELS.get(event.get('stage'), 'Working')}: {event['message']}"


def describe_error(error: dict) -> str:
    """Stage + what happened + what to do next. Nothing was published when this runs."""
    stage = FAILED_STAGE.get(error.get("stage"), "Generation")
    nxt = NEXT_STEP.get(error.get("code"), "Your selection and settings are unchanged; click Generate to retry.")
    lines = [f"{stage} failed: {error.get('message', 'Unknown error.')}",
             "Nothing was saved to the workshop; your selection and settings are unchanged.", nxt]
    log = (error.get("details") or {}).get("log", "")
    for line in log.splitlines():
        if line.startswith("LaTeX log:"):
            lines.append(line)
    return "\n".join(lines)


def build_request(state: dict, task_id: str = "summary", parameters: dict | None = None,
                  efficient: bool = False, provider: str = "codex") -> dict:
    """Snapshot taken at Generate time; later browsing cannot change it."""
    return {
        "workshop_root": str(state["root"]),
        "destination": str(state["current"]),
        "selected_paths": [str(p) for p in workshops.selected_sorted(state)],
        "provider": provider,
        "task_id": task_id,
        "parameters": dict(parameters or {}),
        "efficient": bool(efficient),
        "page_selections": page_selections(state),
    }


def page_selections(state: dict) -> dict:
    """{pdf path: [pages]} for selected PDFs with a Pages setting (new lists: a snapshot). Text that
    doesn't parse is passed as is, so generation rejects it with its filename before any API call."""
    out = {}
    for p in workshops.selected_sorted(state):
        spec = state.get("pages", {}).get(p)
        if spec:
            try:
                out[str(p)] = pdf_pages.parse_spec(spec, p.name)
            except pdf_pages.PageError:
                out[str(p)] = spec
    return out


def count_pages(paths) -> dict:
    """{path: {"mtime", "count"} | {"mtime", "error"}}; runs on a worker thread, never raises."""
    out = {}
    for p in map(Path, paths):
        mtime = None
        try:
            mtime = p.stat().st_mtime
            out[p] = {"mtime": mtime, "count": pdf_pages.inspect(p)}
        except pdf_pages.PageError as e:
            out[p] = {"mtime": mtime, "error": e.message}
        except Exception as e:
            out[p] = {"mtime": mtime, "error": f"{p.name} could not be read ({type(e).__name__})."}
    return out


def page_problem(state: dict, path, info: dict | None = None) -> str | None:
    """Why a selected PDF's Pages setting (or the PDF itself) can't be used, else None.
    info is count_pages()'s entry; without it only the syntax is checked."""
    rel = workshops.relative(state, path)
    if info and info.get("error"):
        return info["error"]
    try:
        pages = pdf_pages.parse_spec(state.get("pages", {}).get(Path(path)), rel)
        if pages and info and info.get("count"):
            pdf_pages.validate(pages, info["count"], rel)
    except pdf_pages.PageError as e:
        return e.message
    return None


def describe_pages(state: dict, path, info: dict | None = None) -> str:
    """Pages note under a selected PDF: count and the normalized selection, or the problem."""
    problem = page_problem(state, path, info)
    if problem:
        return problem
    pages = pdf_pages.parse_spec(state.get("pages", {}).get(Path(path)), Path(path).name)
    count = (info or {}).get("count")
    if count and pages and len(pages) == count:
        pages = None
    return pdf_pages.describe(pages, count) + ("" if info else " (counting pages...)")


def make_me_status(state: dict, page_info: dict | None = None, reuse: dict | None = None) -> dict:
    """Generate eligibility from the shared selection: {ok, blockers: {path: reason}, message}.
    Feedback only; generate() still runs workshops.validate_paths() at the boundary.
    page_info ({path: count_pages() entry}) adds Pages problems and unreadable PDFs."""
    selected = workshops.selected_sorted(state)
    blockers = inputs.generation_blockers(selected)
    for p in selected:
        if p not in blockers and p.suffix.lower() == ".pdf":
            problem = page_problem(state, p, (page_info or {}).get(p))
            if problem:
                blockers[p] = problem
    pending = reuse_blockers(reuse, state)
    if selected and pending and not blockers:
        return {"ok": False, "blockers": {}, "reuse": pending,
                "message": "Generate is off until you resolve the reused settings: " + " ".join(pending.values())}
    if not selected:
        return {"ok": False, "blockers": {}, "message": "Select at least one file to Generate."}
    if blockers:
        names = "; ".join(f"{workshops.relative(state, p)} ({why})" for p, why in blockers.items())
        return {"ok": False, "blockers": blockers,
                "message": f"Generate is off until you remove what Make me can't use: {names}."}
    return {"ok": True, "blockers": {}, "message": ""}


def describe_outcomes(result: dict) -> str:
    """Organizer status text naming every path; never generation's 'nothing was saved' wording."""
    plan_root = result.get("root", "")
    lab = lambda p: organizing.label(plan_root, p) if p else ""
    verb = ACTION_VERB.get(result["action"], result["action"])
    out = result["outcomes"]
    done = [o for o in out if o["status"] == "completed"]
    if result.get("error"):
        return f"{verb} stopped before changing anything: {result['error']['message']}"
    head = (f"{verb} finished: {len(done)} item(s) done." if result["status"] == "ok" else
            f"{verb} stopped: {len(done)} done, {sum(o['status'] == 'failed' for o in out)} failed, "
            f"{sum(o['status'] == 'unattempted' for o in out)} not attempted.")
    lines = [head]
    if result.get("skipped"):
        lines.append(f"Already moved earlier (skipped): {len(result['skipped'])}.")
    for o in out:
        where = f"{lab(o['source'])} -> {lab(o['destination'])}" if o["destination"] else lab(o["source"])
        if o["status"] == "completed":
            lines.append(f"done ({o['change']}): {where}")
        elif o["status"] == "failed":
            lines.append(f"FAILED: {where}: {o['error']['message']}")
        else:
            lines.append(f"not attempted: {lab(o['source'])} (unchanged)")
    if result["status"] != "ok":
        lines.append("Completed items stay where they are now; failed and unattempted items were left in place."
                     + (" Paste the same cut again to retry the rest." if result.get("batch_id") else ""))
    return "\n".join(lines)


def drag_label(effect: str, paths) -> str:
    """Text on the drag pixmap: the filename for one entry, 'N files' (or items) for several."""
    verb = "Move" if effect == "move" else "Copy"
    if len(paths) == 1:
        return f"{verb}: {Path(paths[0]).name}"
    noun = "downloads" if effect == "copy" else ("files" if all(not Path(p).is_dir() for p in paths) else "items")
    return f"{verb} {len(paths)} {noun}"


def describe_drop(result: dict, effect: str) -> str:
    """One-line success status for a drop ('Moved 3 files to Lectures'); anything else gets the full report."""
    out = result.get("outcomes") or []
    if result.get("status") != "ok" or not out:
        return describe_outcomes(result)
    n = len(out)
    folders = sum(o["kind"] == "dir" for o in out)
    if effect == "copy":
        noun = f"download{'s' * (n != 1)}"
    else:
        noun = (f"file{'s' * (n != 1)}" if not folders else f"folder{'s' * (n != 1)}" if folders == n else "items")
    dest = Path(out[0]["destination"]).parent
    where = dest.name or str(dest)
    renamed = sum(Path(o["destination"]).name != Path(o["source"]).name for o in out)
    tail = f" ({renamed} renamed to avoid a name clash)" if renamed else ""
    return f"{'Moved' if effect == 'move' else 'Copied'} {n} {noun} to {where}{tail}."


def run_app() -> int:
    from . import settings
    from PySide6.QtCore import QEvent, QMimeData, QObject, QPoint, QSize, Qt, QThread, QTimer, QUrl, Signal
    from PySide6.QtGui import QActionGroup, QBrush, QColor, QDesktopServices, QDrag, QFontMetrics, QIcon, QPainter, QPixmap
    from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
                                   QGridLayout, QInputDialog, QLabel, QLineEdit, QProgressBar, QScrollArea, QSplitter, QSizePolicy,
                                   QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
                                   QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

    from .theme import apply_theme

    def icon(name):
        return QIcon(str(resource_path(f"assets/icons/ui/{name.replace('_', '-')}.svg")))

    def decorate(button, name, primary=False):
        button.setIcon(icon(name))
        button.setIconSize(QSize(20, 20))
        if primary:
            button.setProperty("primary", True)
        return button

    def heading(text):
        label = QLabel(text)
        label.setProperty("role", "heading")
        return label

    class PathLabel(QLabel):
        """Keep complete paths available without forcing the columns wider."""
        def __init__(self, text=""):
            super().__init__()
            self.setTextFormat(Qt.PlainText)
            self.full_text = ""
            self.setMinimumWidth(0)
            self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            self.setText(text)

        def setText(self, text):
            self.full_text = text
            self.setToolTip(text)
            self.setAccessibleName(text)
            super().setText(self.fontMetrics().elidedText(text, Qt.ElideMiddle, max(40, self.width())))

        def resizeEvent(self, event):
            super().resizeEvent(event)
            self.setText(self.full_text)

    class StatusLabel(QLabel):
        """Plain-text notices; existing setText callbacks stay intact."""
        def setText(self, text):
            super().setText(text)
            self.setVisible(bool(text))
            if hasattr(self, "progress"):
                active = text.startswith(("Starting", "Preparing:", "Generating:", "Checking:", "Rendering:", "Saving:"))
                self.progress.setVisible(active)
            if hasattr(self, "details"):
                self.details.setVisible(bool(text))
            tone = "error" if ("failed" in text.lower() or text.startswith("Error:")) else (
                "success" if text.startswith(("Saved", "Moved", "Copied")) else "info")
            self.setStyleSheet(f"background: {COLORS[tone + '_bg']}; color: {COLORS['text']}; "
                              f"border: 1px solid {COLORS[tone]}; border-radius: 8px; padding: 12px;")

    PATH_ROLE = Qt.UserRole

    class Worker(QObject):
        progress = Signal(str)
        finished = Signal(dict)
        decision_needed = Signal(list)

        def __init__(self, request):
            super().__init__()
            self.request = request
            self.answered = threading.Event()
            self.answer = {}

        def decide(self, decisions):
            """Runs on the worker: ask the UI thread, block until it answers."""
            self.answered.clear()
            self.decision_needed.emit(decisions)
            self.answered.wait()
            return self.answer

        def run(self):
            try:
                result = generation.generate(self.request, lambda ev: self.progress.emit(describe_progress(ev)),
                                             decide_inputs=self.decide)
                if result["status"] == "ok":  # history only after publication, still off the UI thread
                    self.progress.emit("Saving: Adding the result to History...")
                    result["history"] = record_history(self.request["workshop_root"], result)
            except Exception as e:  # last-resort guard so the UI never hangs in "running"
                result = {"status": "error", "error": {"message": f"Unexpected error ({type(e).__name__})."}}
            self.finished.emit(result)

    class CallWorker(QObject):
        """Runs one read-only call off the UI thread (Chrome download discovery)."""
        finished = Signal(object)

        def __init__(self, fn):
            super().__init__()
            self.fn = fn

        def run(self):
            try:
                result = self.fn()
            except Exception as e:  # the provider never raises; this only keeps the UI alive
                result = {"records": [], "errors": [f"Unexpected error ({type(e).__name__})."]}
            self.finished.emit(result)

    class SearchWorker(QObject):
        """One name search (search.search) off the UI thread; the request rides along in the result."""
        finished = Signal(dict)

        def __init__(self, request):
            super().__init__()
            self.request = request
            self.cancel = threading.Event()

        def run(self):
            r = self.request
            try:
                result = search.search(r["root"], r["query"], self.cancel.is_set)
            except Exception as e:  # last-resort guard: report, never hang
                result = {"query": r["query"], "matches": [], "cancelled": False,
                          "warnings": [f"Search failed ({type(e).__name__})."]}
            result["request"] = r
            self.finished.emit(result)

    class OrganizeWorker(QObject):
        finished = Signal(dict)

        def __init__(self, plan):
            super().__init__()
            self.plan = plan

        def run(self):
            try:
                result = organizing.execute_plan(self.plan)
            except Exception as e:  # last-resort guard: report, never hang
                result = {"action": self.plan["action"], "status": "failed", "outcomes": [], "created": [],
                          "removed": [], "error": {"message": f"Unexpected error ({type(e).__name__}: {e})."}}
            result["root"] = self.plan["root"]
            try:  # after the file operations, still off the UI thread
                result["history"] = reconcile_history(self.plan["root"], result.get("outcomes"))
            except Exception as e:
                result["history"] = {"needed": True, "ok": False, "moves": history.confirmed_moves(result.get("outcomes")),
                                     "at": history.now_stamp(), "message": f"Unexpected error ({type(e).__name__})."}
            self.finished.emit(result)

    HOT_STYLE = f"background: {COLORS['warning_bg']}; color: {COLORS['text']}; border: 2px solid {COLORS['amber']};"

    def drop_payload(md):
        """(effect, paths) for one of our file drags, else None."""
        for effect, fmt in DROP_MIME.items():
            if md.hasFormat(fmt):
                try:
                    return effect, json.loads(bytes(md.data(fmt)).decode("utf-8"))
                except ValueError:
                    return None
        return None

    def drag_pixmap(effect, paths):
        text = ("-> " if effect == "move" else "+ ") + drag_label(effect, paths)
        fm = QFontMetrics(QApplication.font())
        pm = QPixmap(fm.horizontalAdvance(text) + 20, fm.height() + 12)
        pm.fill(QColor(COLORS["primary"] if effect == "move" else COLORS["success_bg"]))
        painter = QPainter(pm)
        painter.setPen(QColor(COLORS["text"]))
        painter.drawText(pm.rect(), Qt.AlignCenter, text)
        painter.end()
        return pm

    def set_hot(widget, hot):
        """Highlight a drop target; the widget's own style is kept in a property and restored."""
        if widget is None:
            return
        if widget.property("lnpBaseStyle") is None:
            widget.setProperty("lnpBaseStyle", widget.styleSheet())
        widget.setStyleSheet(HOT_STYLE if hot else widget.property("lnpBaseStyle"))

    class DropTargets:
        """Mixin for the Up button and the current-folder zone. target() -> folder path or None;
        check(md, folder) -> bool decides the cursor; dropped(md, folder) records the drop."""
        target = check = dropped = None

        def _init_drop(self):
            self.setAcceptDrops(True)

        def _ok(self, e):
            dest = self.target() if self.target else None
            return dest if dest and drop_payload(e.mimeData()) is not None and self.check(e.mimeData(), dest) else None

        def _hover(self, e):
            ok = self._ok(e) is not None
            e.acceptProposedAction() if ok else e.ignore()  # ignore = forbidden cursor
            set_hot(self, ok)

        def dragEnterEvent(self, e):
            self._hover(e)

        def dragMoveEvent(self, e):
            self._hover(e)

        def dragLeaveEvent(self, e):
            set_hot(self, False)

        def dropEvent(self, e):
            set_hot(self, False)
            dest = self._ok(e)
            if dest is None:
                return e.ignore()
            e.acceptProposedAction()
            self.dropped(e.mimeData(), dest)

    class DropButton(DropTargets, QPushButton):
        def __init__(self, text):
            QPushButton.__init__(self, text)
            self._init_drop()

    class DropZone(DropTargets, QLabel):
        def __init__(self, text):
            QLabel.__init__(self, text)
            self._init_drop()

    class RowDragFilter(QObject):
        """Starts a browser drag only after the platform drag distance, so clicks and double-clicks on a
        row keep their select/open behaviour. Rows carry their path in the lnpPath property."""

        def __init__(self, start, open_row):
            super().__init__()
            self.start = start
            self.open_row = open_row  # double-click
            self.origin = None

        def eventFilter(self, obj, e):
            t = e.type()
            if t == QEvent.MouseButtonPress and e.button() == Qt.LeftButton:
                self.origin = e.globalPosition().toPoint()
            elif t == QEvent.MouseMove and self.origin is not None and e.buttons() & Qt.LeftButton:
                if (e.globalPosition().toPoint() - self.origin).manhattanLength() >= QApplication.startDragDistance():
                    self.origin = None
                    if isinstance(obj, QPushButton):
                        obj.setDown(False)  # the release goes to the drag, so the press must not become a click
                    self.start(obj.property("lnpPath"), obj)
                    return True
            elif t == QEvent.MouseButtonDblClick and e.button() == Qt.LeftButton:
                self.origin = None
                if isinstance(obj, QPushButton):
                    obj.setDown(False)  # no second click
                self.open_row(obj.property("lnpPath"))
                return True
            elif t == QEvent.MouseButtonRelease:
                self.origin = None
            return False

    class TagBrowser(QListWidget):
        """Folder browser: accepts a name-tag chip on a file row, and file drags (move from this list,
        copy from Recent downloads) on folder rows; empty space and file rows mean the current folder."""
        tag_dropped = Signal(str, str)  # tag, path of the row ("" for empty space)
        current_folder = check = dropped = None  # set by Window

        def __init__(self):
            super().__init__()
            self.setAcceptDrops(True)
            self.viewport().setAcceptDrops(True)
            self.hot = None

        def target_at(self, pos):
            """(folder path, row widget or None) under the pointer."""
            item = self.itemAt(pos)
            if item is not None and item.data(PATH_ROLE + 1) == "dir":
                return item.data(PATH_ROLE), self.itemWidget(item)
            return str(self.current_folder()), None

        def set_hot_row(self, row):
            if row is not self.hot:
                set_hot(self.hot, False)
                self.hot = row
                set_hot(row, True)

        def autoscroll(self, pos):
            sb, h = self.verticalScrollBar(), self.viewport().height()
            if pos.y() < 24:
                sb.setValue(sb.value() - 1)
            elif pos.y() > h - 24:
                sb.setValue(sb.value() + 1)

        def dragEnterEvent(self, e):
            self.dragMoveEvent(e)

        def dragMoveEvent(self, e):
            md = e.mimeData()
            if md.hasFormat(TAG_MIME):
                return e.acceptProposedAction()
            if drop_payload(md) is None:
                return e.ignore()
            pos = e.position().toPoint()
            self.autoscroll(pos)
            dest, row = self.target_at(pos)
            if self.check(md, dest):
                e.acceptProposedAction()
                self.set_hot_row(row)
            else:
                e.ignore()  # forbidden cursor
                self.set_hot_row(None)

        def dragLeaveEvent(self, e):
            self.set_hot_row(None)

        def dropEvent(self, e):
            self.set_hot_row(None)
            md = e.mimeData()
            if md.hasFormat(TAG_MIME):
                item = self.itemAt(e.position().toPoint())
                e.acceptProposedAction()
                return self.tag_dropped.emit(bytes(md.data(TAG_MIME)).decode("utf-8"),
                                             item.data(PATH_ROLE) if item else "")
            dest, _ = self.target_at(e.position().toPoint())
            if drop_payload(md) is not None and self.check(md, dest):
                e.acceptProposedAction()
                self.dropped(md, dest)
            else:
                e.ignore()

    class BinList(QListWidget):
        """Recent downloads rows; dragging past the drag distance starts a copy drag (start(path)),
        a click still ticks the checkbox."""
        start = None

        def __init__(self):
            super().__init__()
            self.origin = None

        def mousePressEvent(self, e):
            self.origin = e.position().toPoint() if e.button() == Qt.LeftButton else None
            super().mousePressEvent(e)

        def mouseMoveEvent(self, e):
            if self.origin is not None and e.buttons() & Qt.LeftButton and \
                    (e.position().toPoint() - self.origin).manhattanLength() >= QApplication.startDragDistance():
                item = self.itemAt(self.origin)
                self.origin = None
                if item is not None and self.start:
                    return self.start(item.data(PATH_ROLE))
            super().mouseMoveEvent(e)

        def mouseReleaseEvent(self, e):
            self.origin = None
            super().mouseReleaseEvent(e)

    class TagChip(QPushButton):
        """A draggable chip; dragging copies the tag name, the chip itself stays."""

        def __init__(self, tag):
            super().__init__(tag)
            self.tag = tag
            self.setAccessibleName(f"Tag {tag}; drag onto a file to rename it {tag}_N")
            self.setToolTip(f"Drag onto a file to rename it {tag}_1, {tag}_2, ...")

        def mouseMoveEvent(self, e):
            if e.buttons() & Qt.LeftButton:
                md = QMimeData()
                md.setData(TAG_MIME, self.tag.encode("utf-8"))
                drag = QDrag(self)
                drag.setMimeData(md)
                drag.exec(Qt.CopyAction)

    class Window(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Late Night Pal")
            self.state = None
            self.thread = None
            self.worker = None
            self.org_thread = None
            self.org_worker = None
            self.tags = None
            self.tag_error = ""
            self.pending_tag = None
            self.bin_thread = None
            self.bin_worker = None
            self.bin_records = []
            self.anchor = None  # Shift+click range start (a row of the folder shown)
            self.row_paths = []
            self.dropped = None  # (effect, paths, folder) recorded by a drop target during drag.exec
            self.pending_drop = None
            self.row_filter = RowDragFilter(self.start_browser_drag, lambda p: self.later(self.open_row, p))
            self.last_dir_click = None  # row toggled by the first click of a double-click
            self.search_seq = 0  # newest search request; older results are dropped
            self.search_jobs = {}  # seq -> (QThread, SearchWorker), kept alive until each finishes
            self.search_result = None  # accepted result being shown; None = folder view
            self.page_info = {}  # selected PDF -> count_pages() entry (page count or error)
            self.pages_thread = None
            self.pages_worker = None
            self.page_notes = {}  # path -> (QLineEdit, QLabel) of the visible Selected Inputs rows
            self.pending_history = {}  # generation_id -> (workshop root, record) whose save failed (this session)
            self.history_records = []  # records shown in the History view (open workshop only)
            self.hist_thread = self.hist_worker = None
            self.hist_reload = False
            self.retry_thread = self.retry_worker = None
            self.pending_reconcile = []  # [(workshop root, confirmed moves, at)] whose History update failed
            self.reuse = None  # checked History entry being restored (P3-M4)
            self.reuse_seq = 0
            self.call_seq = 0
            self.call_jobs = {}  # job -> (QThread, CallWorker) for reuse checks and study progress
            self.prog_seq = 0  # newest Study progress load; older ones are dropped
            self.prog_plans = []  # daily-plan History records of the open workshop
            self.prog_done = {}  # generation_id -> {document_id: bool} as last persisted
            self.prog_pending = set()  # (generation_id, document_id) being saved: disabled until answered
            self.prog_building = False
            self.last_paths = []
            self.last_output_root = None
            self.stack = QStackedWidget()
            self.stack.addWidget(self._start_page())
            self.stack.addWidget(self._workshop_page())
            self.setCentralWidget(self.stack)
            self.setMinimumSize(800, 560)
            area = QApplication.primaryScreen().availableGeometry()
            self.resize(min(1200, area.width()), min(780, area.height()))
            self.provider = settings.generation_method()
            menu = self.menuBar().addMenu("Settings").addMenu("Generation method")
            group = QActionGroup(self)
            for value, label in settings.METHODS.items():
                action = menu.addAction(label)
                action.setCheckable(True)
                action.setData(value)
                group.addAction(action)
                action.setChecked(value == self.provider)
            group.triggered.connect(self.choose_provider)
            self.update_provider_controls()
            self.show_start()

        def choose_provider(self, action):
            self.provider = action.data()
            settings.preferences().setValue("generation/method", self.provider)
            self.update_provider_controls()

        def update_provider_controls(self):
            codex = self.provider == "codex"
            self.efficient_box.setVisible(not codex)
            self.efficient_note.setText("Codex uses extracted text. For scans or diagrams, choose Gemini API "
                                        "in Settings." if codex else EFFICIENT_NOTE)

        # ---------- start screen ----------
        def _start_page(self):
            page = QWidget()
            outer = QVBoxLayout(page)
            outer.setContentsMargins(32, 24, 32, 24)
            content = QWidget()
            content.setMaximumWidth(1040)
            lay = QVBoxLayout(content)
            lay.setSpacing(24)
            welcome = QHBoxLayout()
            words = QVBoxLayout()
            words.setSpacing(12)
            words.addStretch()
            title = QLabel("Welcome to Late Night Pal")
            title.setProperty("role", "title")
            words.addWidget(title)
            intro = QLabel("A calm workspace for your next study session.")
            intro.setProperty("role", "support")
            words.addWidget(intro)
            row = QHBoxLayout()
            self.open_btn = decorate(QPushButton("Open Workshop"), "folder", True)
            self.create_btn = QPushButton("Create Workshop")
            self.open_btn.clicked.connect(self.open_workshop_dialog)
            self.create_btn.clicked.connect(self.create_workshop_dialog)
            row.addWidget(self.open_btn)
            row.addWidget(self.create_btn)
            row.addStretch()
            words.addLayout(row)
            words.addStretch()
            welcome.addLayout(words, 1)
            self.welcome_art = QLabel()
            self.welcome_art.setPixmap(QIcon(str(resource_path("assets/icons/illustrations/welcome-desk.svg"))).pixmap(300, 200))
            self.welcome_art.setFixedSize(300, 200)
            welcome.addWidget(self.welcome_art)
            lay.addLayout(welcome)
            lay.addWidget(heading("Recent Workshops"))
            self.recent_list = QListWidget()
            self.recent_list.itemClicked.connect(self.open_recent)
            lay.addWidget(self.recent_list, 1)
            outer.addWidget(content, 1)
            outer.setAlignment(content, Qt.AlignHCenter)
            content.setMinimumWidth(700)
            return page

        def resizeEvent(self, event):
            super().resizeEvent(event)
            if hasattr(self, "welcome_art"):
                self.welcome_art.setVisible(self.width() >= 1040)

        def show_start(self):
            self.clear_search_box()
            self.recent_list.clear()
            recents = workshops.load_recents()
            for r in recents:
                path = Path(r["path"])
                item = QListWidgetItem(icon("folder" if r["exists"] else "warning"),
                                       f"{path.name}  {'— Folder unavailable' if not r['exists'] else ''}\n{path.parent}")
                item.setSizeHint(QSize(0, 64))
                item.setToolTip(str(path))
                item.setData(PATH_ROLE, r["path"])
                if not r["exists"]:
                    item.setForeground(QBrush(QColor(COLORS["muted"])))
                self.recent_list.addItem(item)
            if not recents:
                item = QListWidgetItem("Open a folder to start a workshop.")
                item.setFlags(Qt.NoItemFlags)
                self.recent_list.addItem(item)
            self.stack.setCurrentIndex(0)

        def ask_folder(self, caption):
            return QFileDialog.getExistingDirectory(self, caption)

        def ask_name(self):
            name, ok = QInputDialog.getText(self, "Create Workshop", "Workshop folder name:")
            return name.strip() if ok else ""

        def open_recent(self, item):
            path = item.data(PATH_ROLE)
            if not path:
                return
            if Path(path).is_dir():
                return self.enter_workshop(workshops.open_workshop(path))
            box = QMessageBox(QMessageBox.Warning, "Workshop not found",
                              f"This workshop folder no longer exists:\n{path}", parent=self)
            locate = box.addButton("Open another folder...", QMessageBox.AcceptRole)
            remove = box.addButton("Remove from list", QMessageBox.DestructiveRole)
            box.addButton(QMessageBox.Cancel)
            box.exec()
            if box.clickedButton() is remove:
                workshops.remove_recent(path)
                self.show_start()
            elif box.clickedButton() is locate:
                self.open_workshop_dialog()

        def open_workshop_dialog(self):
            folder = self.ask_folder("Open Workshop")
            if folder:
                self.enter_workshop(workshops.open_workshop(folder))

        def create_workshop_dialog(self):
            parent = self.ask_folder("Choose where to create the workshop")
            if not parent:
                return
            name = self.ask_name()
            if not name:
                return
            try:
                self.enter_workshop(workshops.create_workshop(Path(parent) / name))
            except (workshops.WorkshopError, OSError) as e:
                QMessageBox.warning(self, "Create Workshop", getattr(e, "message", str(e)))

        # ---------- workshop screen ----------
        def _workshop_page(self):
            page = QWidget()
            lay = QVBoxLayout(page)
            lay.setContentsMargins(24, 16, 24, 24)
            lay.setSpacing(16)
            top = QHBoxLayout()
            top.setSpacing(16)
            self.back_btn = QPushButton("‹ Workshops")
            self.back_btn.clicked.connect(self.show_start)
            self.root_lbl = PathLabel()
            self.root_lbl.setProperty("role", "heading")
            top.addWidget(self.back_btn)
            top.addWidget(self.root_lbl, 1)
            lay.addLayout(top)

            body = QSplitter(Qt.Horizontal)
            body.setHandleWidth(8)
            left_panel = QWidget()
            left_panel.setMinimumWidth(320)
            left = QVBoxLayout(left_panel)
            left.setContentsMargins(0, 0, 8, 0)
            left.setSpacing(12)
            nav = QHBoxLayout()
            self.up_btn = DropButton("Up")
            self.up_btn.setToolTip("Open the parent folder. Drop files here to move them to the parent folder.")
            self.up_btn.target = lambda: (str(self.state["current"].parent)
                                          if self.state and self.state["current"] != self.state["root"] else None)
            self.up_btn.check, self.up_btn.dropped = self.drop_allowed, self.record_drop
            self.up_btn.clicked.connect(self.go_up)
            self.refresh_btn = QPushButton("Refresh")
            self.refresh_btn.setToolTip("Rescan this folder and drop selected entries that no longer exist.")
            self.refresh_btn.clicked.connect(self.refresh_clicked)
            self.folder_lbl = PathLabel()
            nav.addWidget(self.up_btn)
            nav.addWidget(self.folder_lbl, 1)
            nav.addWidget(self.refresh_btn)
            left.addLayout(nav)
            self.search_edit = QLineEdit()
            self.search_edit.setPlaceholderText("Search file and folder names in this workshop")
            self.search_edit.setAccessibleName("Search workshop names")
            self.search_edit.setClearButtonEnabled(True)
            self.search_edit.textChanged.connect(self.search_text_changed)
            self.search_edit.returnPressed.connect(self.start_search)
            self.search_timer = QTimer(self)
            self.search_timer.setSingleShot(True)
            self.search_timer.setInterval(SEARCH_DEBOUNCE_MS)
            self.search_timer.timeout.connect(self.start_search)
            left.addWidget(self.search_edit)
            self.search_note = QLabel("")
            self.search_note.setWordWrap(True)
            self.search_note.setProperty("role", "support")
            self.search_note.setVisible(False)
            left.addWidget(self.search_note)
            self.browser = TagBrowser()
            self.browser.tag_dropped.connect(lambda tag, path: self.later(self.apply_tag, tag, path))
            self.browser.current_folder = lambda: self.state["current"]
            self.browser.check, self.browser.dropped = self.drop_allowed, self.record_drop
            left.addWidget(self.browser)
            self.drop_zone = DropZone("Drop here to put files in the current folder")
            self.drop_zone.setAlignment(Qt.AlignCenter)
            self.drop_zone.setAccessibleName("Current folder drop target")
            self.drop_zone.setStyleSheet(f"border: 1px dashed {COLORS['control']}; border-radius: 8px; padding: 12px; color: {COLORS['secondary']};")
            self.drop_zone.target = lambda: str(self.state["current"]) if self.state else None
            self.drop_zone.check, self.drop_zone.dropped = self.drop_allowed, self.record_drop
            left.addWidget(self.drop_zone)
            hint = QLabel("Click a file or folder (or tick its box) to select it; double-click a folder to open it or a PDF to view it in Chrome. "
                          "Ctrl+click toggles without opening, "
                          "Shift+click adds a range. Drag rows onto a folder or Up to move them; drag "
                          "Recent downloads onto a folder to copy them.")
            hint.setWordWrap(True)
            hint.setProperty("role", "support")
            left.addWidget(hint)
            self.bin_btn = QPushButton("Recent downloads")
            decorate(self.bin_btn, "recent-downloads")
            self.bin_btn.setAccessibleName("Recent downloads bin")
            self.bin_btn.setToolTip("Files Chrome finished downloading in the last hour. Opening this never "
                                    "changes or deletes them.")
            self.bin_btn.clicked.connect(self.toggle_bin)
            left.addWidget(self.bin_btn)
            self.bin_panel = QWidget()
            bin_lay = QVBoxLayout(self.bin_panel)
            bin_lay.setContentsMargins(0, 0, 0, 0)
            self.bin_note = QLabel("")
            self.bin_note.setWordWrap(True)
            bin_lay.addWidget(self.bin_note)
            self.bin_list = BinList()
            self.bin_list.start = self.start_download_drag
            self.bin_list.setAccessibleName("Recent downloads; tick the ones to copy")
            self.bin_list.setMaximumHeight(140)
            self.bin_list.itemChanged.connect(lambda *_: self.update_bin_buttons())
            bin_lay.addWidget(self.bin_list)
            bin_row = QHBoxLayout()
            self.bin_copy_btn = QPushButton("Copy to current folder")
            self.bin_copy_btn.setToolTip("Copies the ticked files here with Paste's naming rules; the originals stay.")
            self.bin_copy_btn.clicked.connect(self.copy_downloads)
            bin_close = QPushButton("Close")
            bin_close.clicked.connect(self.toggle_bin)
            bin_row.addWidget(self.bin_copy_btn)
            bin_row.addWidget(bin_close)
            bin_lay.addLayout(bin_row)
            self.bin_panel.setVisible(False)
            left.addWidget(self.bin_panel)
            left.addWidget(heading("Name tags · this folder"))
            tag_row = QHBoxLayout()
            self.tag_edit = QLineEdit()
            self.tag_edit.setPlaceholderText("New tag, e.g. assignment")
            self.tag_edit.setAccessibleName("New tag name")
            self.tag_edit.returnPressed.connect(self.add_tag)
            self.tag_add_btn = decorate(QPushButton(""), "add")
            self.tag_add_btn.setFixedWidth(40)
            self.tag_add_btn.setAccessibleName("Add tag")
            self.tag_add_btn.clicked.connect(self.add_tag)
            tag_row.addWidget(self.tag_edit, 1)
            tag_row.addWidget(self.tag_add_btn)
            left.addLayout(tag_row)
            self.chip_box = QWidget()
            self.chip_row = QHBoxLayout(self.chip_box)
            self.chip_row.setContentsMargins(0, 0, 0, 0)
            self.chip_row.setAlignment(Qt.AlignLeft)
            chip_scroll = QScrollArea()
            chip_scroll.setWidgetResizable(True)
            chip_scroll.setFixedHeight(60)
            chip_scroll.setWidget(self.chip_box)
            left.addWidget(chip_scroll)
            self.tag_note = QLabel("")
            self.tag_note.setWordWrap(True)
            self.tag_note.setProperty("role", "support")
            left.addWidget(self.tag_note)
            body.addWidget(left_panel)

            right_panel = QWidget()
            right_panel.setProperty("panel", True)
            right_panel.setMinimumWidth(336)
            right_panel.setMaximumWidth(440)
            right = QVBoxLayout(right_panel)
            right.setContentsMargins(16, 16, 16, 16)
            right.setSpacing(12)
            self.selected_lbl = heading("Selected Inputs (0)")
            self.selected_lbl.setWordWrap(True)
            right.addWidget(self.selected_lbl)
            self.selected_list = QListWidget()
            self.selected_list.setFixedHeight(168)
            right.addWidget(self.selected_list)
            modes = QGridLayout()  # 2 x 2: four labels don't fit one row of the narrow right panel
            self.mode_group = QButtonGroup(page)
            self.mode_stack = QStackedWidget()
            for i, label in enumerate(("Organize", "Make me", "History", "Progress")):
                b = decorate(QPushButton(label), ("organize", "make-me", "schedule", "checklist")[i])
                b.setCheckable(True)
                self.mode_group.addButton(b, i)
                modes.addWidget(b, i // 2, i % 2)
            right.addLayout(modes)
            right.addWidget(self.mode_stack)
            org_page = QWidget()
            org = QVBoxLayout(org_page)
            self.action_btns = {}
            grid = QGridLayout()
            grid.setSpacing(12)
            order = ["wrap", "rip", "super_wrap", "copy", "paste", "delete"]
            for action, label in ORGANIZE_ACTIONS:
                b = decorate(QPushButton(label), action)
                b.setProperty("destructive", action == "delete")
                if action == "super_wrap":
                    b.setToolTip("Wrap into a new folder, grouping files by shared name parts such as Cal_1_...")
                b.clicked.connect(lambda _=False, a=action: self.organize(a))
                self.action_btns[action] = b
                pos = order.index(action)
                grid.addWidget(b, pos // 2, pos % 2)
            org.addLayout(grid)
            rip_help = QLabel(f"Rip: {RIP_HELP}")
            rip_help.setWordWrap(True)
            org.addWidget(rip_help)
            org.addStretch(1)
            make_page = QWidget()
            right_outer, right = right, QVBoxLayout(make_page)
            right.setContentsMargins(0, 0, 0, 0)
            right.setSpacing(8)
            self.reuse_box = QWidget()
            self.reuse_box.setProperty("panel", True)
            reuse_lay = QVBoxLayout(self.reuse_box)
            reuse_lay.setContentsMargins(8, 8, 8, 8)
            self.reuse_title = QLabel("")
            self.reuse_title.setWordWrap(True)
            reuse_lay.addWidget(self.reuse_title)
            self.reuse_rows = QVBoxLayout()
            reuse_lay.addLayout(self.reuse_rows)
            self.reuse_done_btn = QPushButton("Done")
            self.reuse_done_btn.setToolTip("Hide this note; the restored settings stay.")
            self.reuse_done_btn.clicked.connect(self.close_reuse)
            reuse_lay.addWidget(self.reuse_done_btn)
            self.reuse_box.setVisible(False)
            right.addWidget(self.reuse_box)
            right.addWidget(QLabel("Output type"))
            self.output_type = QComboBox()
            self.output_type.addItems([tasks.STUDY_PLAN, tasks.SINGLE_FILE])
            right.addWidget(self.output_type)
            right.addWidget(QLabel("Task"))
            self.task_box = QComboBox()
            right.addWidget(self.task_box)
            # Single file parameter
            self.style_lbl = QLabel("Language style")
            self.style_box = QComboBox()
            self.style_box.addItems(list(tasks.STYLES))
            self.style_box.setCurrentText(tasks.DEFAULT_STYLE)
            # Study plan parameters
            self.days_lbl = QLabel("Days")
            self.days_box = QSpinBox()
            self.days_box.setRange(1, 2**31 - 1)  # no product cap; Qt's int limit only
            self.days_box.setValue(2)
            self.folder_lbl_param = QLabel("Folder name (optional)")
            self.folder_edit = QLineEdit()
            for w in (self.style_lbl, self.style_box, self.days_lbl, self.days_box, self.folder_lbl_param,
                      self.folder_edit):
                right.addWidget(w)
            self.efficient_box = QCheckBox("Efficient")
            self.efficient_box.setChecked(False)
            self.efficient_note = QLabel(EFFICIENT_NOTE)
            self.efficient_note.setWordWrap(True)
            self.efficient_note.setProperty("role", "support")
            right.addWidget(self.efficient_box)
            right.addWidget(self.efficient_note)
            self.output_type.currentTextChanged.connect(self.output_type_changed)
            self.task_box.currentIndexChanged.connect(self.task_changed)
            self.output_type.setCurrentText(tasks.SINGLE_FILE)
            self.output_type_changed(tasks.SINGLE_FILE)
            self.eligibility_lbl = QLabel("")
            self.eligibility_lbl.setWordWrap(True)
            self.eligibility_lbl.setStyleSheet(f"color: {COLORS['error']}; font-size: 13px;")
            right.addWidget(self.eligibility_lbl)
            form_scroll = QScrollArea()
            form_scroll.setWidgetResizable(True)
            form_scroll.setWidget(make_page)
            self.save_lbl = PathLabel("Save to: Workshop root")
            self.save_lbl.setProperty("role", "support")
            self.generate_btn = decorate(QPushButton("Generate"), "generate", True)
            self.generate_btn.clicked.connect(self.generate)

            row = QHBoxLayout()
            self.open_doc_btn = QPushButton("Open document")
            self.open_folder_btn = QPushButton("Open output folder")
            self.open_doc_btn.clicked.connect(self.open_document)
            self.open_folder_btn.clicked.connect(self.open_output_folder)
            decorate(self.open_doc_btn, "notes")
            decorate(self.open_folder_btn, "folder")
            row.addWidget(self.open_doc_btn)
            row.addWidget(self.open_folder_btn)
            self.retry_history_btn = QPushButton("Retry saving history")
            self.retry_history_btn.setToolTip("Save the History entry again. The PDFs are already saved; "
                                              "generation will not run.")
            self.retry_history_btn.clicked.connect(self.retry_history)
            self.retry_history_btn.setVisible(False)
            row.addWidget(self.retry_history_btn)
            right.addStretch(1)
            self.mode_stack.addWidget(org_page)
            self.mode_stack.addWidget(form_scroll)
            self.mode_stack.addWidget(self._history_page())
            self.mode_stack.addWidget(self._progress_page())
            right_outer.addWidget(self.save_lbl)
            right_outer.addWidget(self.generate_btn)
            right_outer.addLayout(row)
            self.mode_group.idClicked.connect(self.mode_changed)
            self.mode_group.button(1).setChecked(True)  # Make me by default, for continuity
            self.mode_stack.setCurrentIndex(1)
            self.status = StatusLabel("")
            self.status.setTextFormat(Qt.PlainText)
            self.status.setWordWrap(True)
            self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
            progress = QProgressBar()
            progress.setRange(0, 0)
            progress.setTextVisible(False)
            progress.setAccessibleName("Operation in progress")
            progress.setVisible(False)
            self.status.progress = progress
            right_outer.addWidget(progress)
            details = QScrollArea()
            details.setWidgetResizable(True)
            details.setMaximumHeight(160)
            details.setWidget(self.status)
            self.status.details = details
            details.setVisible(False)
            right_outer.addWidget(details)
            body.addWidget(right_panel)
            body.setStretchFactor(0, 1)
            body.setStretchFactor(1, 0)
            body.setSizes([720, 400])
            lay.addWidget(body, 1)
            for button, name in ((self.up_btn, "up-one-level"), (self.refresh_btn, "refresh"),
                                 (self.bin_copy_btn, "copy-to-folder")):
                decorate(button, name)
            return page

        def output_type_changed(self, output_type):
            self.task_box.blockSignals(True)
            self.task_box.clear()
            for task_id, label in tasks.tasks_for(output_type):
                self.task_box.addItem(icon(task_id), label, task_id)
            self.task_box.blockSignals(False)
            if output_type == tasks.SINGLE_FILE:
                self.task_box.setCurrentIndex(self.task_box.findData("summary"))
            self.task_changed()

        def task_changed(self, *_):
            """Show the current task's parameters; selection is untouched (it lives in workshop state)."""
            task_id = self.task_box.currentData()
            plan = tasks.TASKS.get(task_id, {}).get("output_type") == tasks.STUDY_PLAN
            for w in (self.style_lbl, self.style_box):
                w.setVisible(not plan)
            for w in (self.days_lbl, self.days_box, self.folder_lbl_param, self.folder_edit):
                w.setVisible(plan)
            if plan:
                self.folder_edit.setPlaceholderText(tasks.TASKS[task_id]["default_folder"])

        def current_parameters(self) -> dict:
            task_id = self.task_box.currentData()
            if tasks.TASKS[task_id]["output_type"] == tasks.STUDY_PLAN:
                return {"days": self.days_box.value(), "folder_name": self.folder_edit.text()}
            return {"language_style": self.style_box.currentText()}

        def enter_workshop(self, state):
            self.state = state
            self.last_paths = []
            self.status.setText("")
            self.clear_search_box()  # results and in-flight searches belong to the previous workshop
            self.clear_history_view()  # entries of the previous workshop must not show here
            self.reuse = None
            self.reuse_seq += 1  # a reuse check still running belongs to the previous workshop
            self.clear_progress_view()
            self.root_lbl.setText(f"{state['root'].name}   ·   {state['root']}")
            self.load_tags()
            self.refresh()
            self.reload_bin()  # startup reconciliation; the tray itself stays closed
            self.stack.setCurrentIndex(1)
            if self.mode_stack.currentIndex() == 2:
                self.load_history()
            if self.mode_stack.currentIndex() == 3:
                self.load_progress()

        def mode_changed(self, index):
            """Switch Organize / Make me / History / Progress; selection and every Make me setting are untouched.
            History and Progress don't use Selected Inputs or Save to, so those are hidden to give their lists room."""
            self.mode_stack.setCurrentIndex(index)
            for w in (self.selected_lbl, self.selected_list, self.save_lbl):
                w.setVisible(index in (0, 1))
            self.refresh_selected()
            if index == 2:
                self.load_history()
            if index == 3:
                self.load_progress()

        # ---------- Study progress (P3-M5): per (generation_id, document_id), saved one checkbox at a time ----------
        def _progress_page(self):
            page = QWidget()
            lay = QVBoxLayout(page)
            lay.setContentsMargins(0, 0, 0, 0)
            top = QHBoxLayout()
            top.addWidget(heading("Study progress · daily plans"), 1)
            reload_btn = decorate(QPushButton("Reload"), "refresh")
            reload_btn.clicked.connect(self.load_progress)
            top.addWidget(reload_btn)
            lay.addLayout(top)
            self.prog_note = QLabel("")
            self.prog_note.setWordWrap(True)
            self.prog_note.setProperty("role", "support")
            lay.addWidget(self.prog_note)
            self.prog_plan = QComboBox()
            self.prog_plan.setAccessibleName("Daily plan")
            self.prog_plan.currentIndexChanged.connect(lambda *_: self.show_plan())
            lay.addWidget(self.prog_plan)
            self.prog_total = QLabel("")
            self.prog_total.setProperty("role", "heading")
            lay.addWidget(self.prog_total)
            self.prog_list = QListWidget()
            self.prog_list.setMinimumHeight(200)  # two days of three items stay visible
            self.prog_list.setAccessibleName("Study items by day; tick when done")
            self.prog_list.itemChanged.connect(self.progress_toggled)
            self.prog_list.itemDoubleClicked.connect(lambda *_: self.open_progress_document())
            self.prog_list.currentRowChanged.connect(lambda *_: self.update_progress_buttons())
            lay.addWidget(self.prog_list, 1)
            self.prog_open_btn = decorate(QPushButton("Open document"), "notes")
            self.prog_open_btn.setToolTip("Open this PDF. Opening never changes its checkbox.")
            self.prog_open_btn.clicked.connect(self.open_progress_document)
            lay.addWidget(self.prog_open_btn)
            self.update_progress_buttons()
            return page

        def clear_progress_view(self):
            self.prog_seq += 1  # a load still running belongs to the previous workshop
            self.prog_plans, self.prog_done, self.prog_base_note = [], {}, ""
            self.prog_plan.blockSignals(True)
            self.prog_plan.clear()
            self.prog_plan.blockSignals(False)
            self.prog_list.clear()
            self.prog_total.setText("")
            self.prog_note.setText("")
            self.update_progress_buttons()

        def load_progress(self):
            if self.state is None:
                return
            self.prog_seq += 1
            seq, root = self.prog_seq, self.state["root"]
            self.prog_note.setText("Loading study progress...")
            self.run_call("progress_loaded", lambda: dict(study_progress.view(root), seq=seq))

        def on_progress_loaded(self, v):
            if self.state is None or v.get("seq") != self.prog_seq or v.get("root") != str(self.state["root"]):
                return  # an older load or another workshop: never shown
            if "error" in v:
                self.prog_note.setText("Study progress could not be loaded. " + v["error"])
                return
            keep = self.current_plan()
            keep_id = keep["generation_id"] if keep else None
            saved = self.prog_done
            self.prog_plans = v["plans"]
            self.prog_done = {gid: dict(m) for gid, m in v["done"].items()}
            for gid, doc in self.prog_pending:  # a save still on its way answers for these items
                if doc in saved.get(gid, {}):
                    self.prog_done.setdefault(gid, {})[doc] = saved[gid][doc]
            self.prog_plan.blockSignals(True)
            self.prog_plan.clear()
            for r in self.prog_plans:
                self.prog_plan.addItem(study_progress.describe_plan(r), r["generation_id"])
            ids = [r["generation_id"] for r in self.prog_plans]
            self.prog_plan.setCurrentIndex(ids.index(keep_id) if keep_id in ids else 0)
            self.prog_plan.blockSignals(False)
            notes = list(v["warnings"])
            if not self.prog_plans:
                notes.append("No daily study plans in this workshop's History yet. Make a daily study plan to track it here.")
            self.prog_base_note = "\n".join(notes)
            self.prog_note.setText(self.prog_base_note)
            self.prog_note.setStyleSheet(f"color: {COLORS['error']};" if v["warnings"] else "")
            self.show_plan()

        def current_plan(self):
            i = self.prog_plan.currentIndex()
            return self.prog_plans[i] if 0 <= i < len(self.prog_plans) else None

        def show_plan(self):
            """Rebuild the checklist of the chosen plan from its manifest and the persisted state."""
            row = self.prog_list.currentRow()
            self.prog_building = True
            self.prog_list.clear()
            r = self.current_plan()
            if r is None:
                self.prog_total.setText("")
                self.prog_building = False
                return self.update_progress_buttons()
            plan = study_progress.manifest(r)
            done = self.prog_done.get(r["generation_id"], {})
            t = study_progress.totals(plan, done)
            self.prog_total.setText(f"{t['done']}/{t['total']} items complete")
            for d in plan["days"]:
                n, total = t["days"][d["day"]]
                head = QListWidgetItem(f"Day {d['day']} · {n}/{total}")
                head.setFlags(Qt.ItemIsEnabled)
                head.setForeground(QBrush(QColor(COLORS["secondary"])))
                self.prog_list.addItem(head)
                for i in d["items"]:
                    gone = i["status"] != "available"
                    item = QListWidgetItem(f"    {i['label']}  ·  {i['path']}" + ("  (unavailable: moved or deleted)" if gone else ""))
                    item.setData(PATH_ROLE, [r["generation_id"], i["document_id"], i["path"]])
                    pending = (r["generation_id"], i["document_id"]) in self.prog_pending
                    item.setFlags((Qt.ItemIsSelectable | Qt.ItemIsUserCheckable) | (Qt.NoItemFlags if pending else Qt.ItemIsEnabled))
                    item.setCheckState(Qt.Checked if done.get(i["document_id"]) else Qt.Unchecked)
                    if gone:
                        item.setForeground(QBrush(QColor(COLORS["muted"])))
                    self.prog_list.addItem(item)
            self.prog_note.setText("\n".join(filter(None, [getattr(self, "prog_base_note", "")] + plan["warnings"])))
            self.prog_list.setCurrentRow(min(max(row, 0), self.prog_list.count() - 1))
            self.prog_building = False
            self.update_progress_buttons()

        def update_progress_buttons(self):
            item = self.prog_list.currentItem() if hasattr(self, "prog_list") else None
            data = item.data(PATH_ROLE) if item else None
            self.prog_open_btn.setEnabled(bool(data) and "unavailable" not in item.text())

        def progress_toggled(self, item):
            if self.prog_building or self.state is None:
                return
            data = item.data(PATH_ROLE)
            if not data:
                return
            gid, doc = data[0], data[1]
            if (gid, doc) in self.prog_pending:
                return self.show_plan()  # one save per item at a time
            want = item.checkState() == Qt.Checked
            self.prog_pending.add((gid, doc))
            self.prog_building = True
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled)  # disabled until this save answers
            self.prog_building = False
            root = self.state["root"]

            def save():
                try:
                    return dict(study_progress.set_done(root, gid, doc, want), ok=True, root=str(root))
                except study_progress.ProgressError as e:
                    return {"ok": False, "message": e.message, "root": str(root), "generation_id": gid, "document_id": doc}
            self.run_call("progress_saved", save)

        def on_progress_saved(self, r):
            if "root" not in r:
                return self.status.setText("Error: study progress could not be saved. " + r.get("error", ""))
            self.prog_pending.discard((r["generation_id"], r["document_id"]))
            if self.state is None or r["root"] != str(self.state["root"]):
                return  # saved for its own workshop; nothing on screen belongs to it
            if r["ok"]:
                self.prog_done.setdefault(r["generation_id"], {})[r["document_id"]] = r["done"]
                if r.get("moved_aside"):
                    self.status.setText(f"The unreadable study progress file was kept as {r['moved_aside']}.")
            else:
                self.status.setText("Error: " + r["message"])  # the view shows the last saved value again
            cur = self.current_plan()
            if cur and cur["generation_id"] == r["generation_id"]:
                self.show_plan()

        def open_progress_document(self):
            item = self.prog_list.currentItem()
            data = item.data(PATH_ROLE) if item else None
            if not data or self.state is None:
                return
            path, status = history.resolve(self.state["root"], data[2])
            if status != "available" or not path.is_file():
                self.status.setText(f"Error: {data[2]} is unavailable (moved, deleted or outside the workshop). "
                                    "Its checkbox is kept.")
                return self.load_progress()
            self.view_pdf(str(path))  # opening never changes completion

        # ---------- History (P3-M3): load off the UI thread, open actions recheck containment ----------
        def _history_page(self):
            page = QWidget()
            lay = QVBoxLayout(page)
            lay.setContentsMargins(0, 0, 0, 0)
            top = QHBoxLayout()
            top.addWidget(heading("History · this workshop"), 1)
            reload_btn = decorate(QPushButton("Reload"), "refresh")
            reload_btn.clicked.connect(self.load_history)
            top.addWidget(reload_btn)
            lay.addLayout(top)
            self.history_note = QLabel("")
            self.history_note.setWordWrap(True)
            self.history_note.setProperty("role", "support")
            lay.addWidget(self.history_note)
            self.history_list = QListWidget()
            self.history_list.setMinimumHeight(120)
            self.history_list.setAccessibleName("Generation history, newest first")
            self.history_list.setWordWrap(True)
            self.history_list.currentRowChanged.connect(self.show_history_record)
            lay.addWidget(self.history_list, 2)
            lay.addWidget(heading("Outputs"))
            self.history_outputs = QListWidget()
            self.history_outputs.setMinimumHeight(110)
            self.history_outputs.setAccessibleName("Outputs of the chosen generation")
            self.history_outputs.currentRowChanged.connect(lambda *_: self.update_history_buttons())
            self.history_outputs.itemDoubleClicked.connect(lambda *_: self.open_history_document())
            lay.addWidget(self.history_outputs, 1)
            row = QHBoxLayout()
            self.hist_doc_btn = decorate(QPushButton("Open document"), "notes")
            self.hist_doc_btn.clicked.connect(self.open_history_document)
            self.hist_folder_btn = decorate(QPushButton("Open output folder"), "folder")
            self.hist_folder_btn.clicked.connect(self.open_history_folder)
            row.addWidget(self.hist_doc_btn)
            row.addWidget(self.hist_folder_btn)
            lay.addLayout(row)
            self.hist_reuse_btn = decorate(QPushButton("Reuse settings"), "make-me")
            self.hist_reuse_btn.setToolTip("Restore this entry's inputs, pages, task, settings and Save to folder in "
                                           "Make me after checking them. Nothing is generated until you click Generate.")
            self.hist_reuse_btn.clicked.connect(self.reuse_settings)
            lay.addWidget(self.hist_reuse_btn)
            self.update_history_buttons()
            return page

        def clear_history_view(self, note=""):
            self.history_records = []
            self.history_list.clear()
            self.history_outputs.clear()
            self.history_note.setText(note)
            self.update_history_buttons()

        def load_history(self):
            if self.state is None:
                return
            if self.hist_thread is not None:
                self.hist_reload = True  # one load at a time; run again when this one returns
                return
            self.history_note.setText("Loading history...")
            root = self.state["root"]
            self.hist_thread = QThread()
            self.hist_worker = CallWorker(lambda r=root: history.view(r))
            self.hist_worker.moveToThread(self.hist_thread)
            self.hist_thread.started.connect(self.hist_worker.run)
            self.hist_worker.finished.connect(self.history_loaded)
            self.hist_thread.start()

        def history_loaded(self, result):
            self.hist_thread.quit()
            self.hist_thread.wait()
            self.hist_thread = None
            again, self.hist_reload = self.hist_reload, False
            if "root" not in result:  # CallWorker's last-resort fallback: report, don't loop
                return self.clear_history_view("History could not be loaded: " + " ".join(result.get("errors", [])))
            if self.state is None or result.get("root") != str(self.state["root"]):
                if again or self.state is not None:
                    self.load_history()  # result for another workshop: never shown here
                return
            if again:
                return self.load_history()
            current = self.current_history()
            keep_id = current["generation_id"] if current else None
            self.history_records = result["records"]
            self.history_list.clear()
            for r in self.history_records:
                item = QListWidgetItem(describe_history_record(r))
                item.setToolTip(f"Generation {r['generation_id']}")
                self.history_list.addItem(item)
            notes = list(result["warnings"])
            if not self.history_records:
                notes.append("No generations recorded for this workshop yet. Successful Make me results appear here.")
            self.history_note.setText("\n".join(notes))
            self.history_note.setStyleSheet(f"color: {COLORS['error']};" if result["warnings"] else "")
            if self.history_records:
                ids = [r["generation_id"] for r in self.history_records]
                self.history_list.setCurrentRow(ids.index(keep_id) if keep_id in ids else 0)
            else:
                self.show_history_record(-1)

        def current_history(self):
            row = self.history_list.currentRow()
            return self.history_records[row] if 0 <= row < len(self.history_records) else None

        def show_history_record(self, row):
            self.history_outputs.clear()
            r = self.history_records[row] if 0 <= row < len(self.history_records) else None
            for o in (r or {}).get("outputs", []):
                item = QListWidgetItem(describe_history_output(o))
                if o.get("_status") != "available":
                    item.setForeground(QBrush(QColor(COLORS["muted"])))
                self.history_outputs.addItem(item)
            if r and r["outputs"]:
                self.history_outputs.setCurrentRow(0)
            self.update_history_buttons()

        def update_history_buttons(self):
            r = self.current_history()
            o = self.current_history_output()
            self.hist_doc_btn.setEnabled(bool(o and o.get("_status") == "available"))
            self.hist_folder_btn.setEnabled(bool(r and r.get("_output_root_status") == "available"))
            if hasattr(self, "hist_reuse_btn"):
                self.hist_reuse_btn.setEnabled(r is not None and self.thread is None)

        def current_history_output(self):
            r = self.current_history()
            row = self.history_outputs.currentRow()
            return r["outputs"][row] if r and 0 <= row < len(r["outputs"]) else None

        def open_history_document(self):
            o = self.current_history_output()
            if o is None or self.state is None:
                return
            path, status = history.resolve(self.state["root"], o["path"])
            if status != "available" or not path.is_file():
                self.status.setText(f"Error: {o['path']} is unavailable (moved, deleted or outside the workshop). "
                                    "History now marks it unavailable.")
                return self.load_history()
            self.view_pdf(str(path))

        def open_history_folder(self):
            r = self.current_history()
            if r is None or self.state is None:
                return
            path, status = history.resolve(self.state["root"], r["output_root"])
            if status != "available" or not path.is_dir():
                self.status.setText(f"Error: the output folder {r['output_root']} is unavailable (moved or deleted).")
                return self.load_history()
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

        # ---------- Reuse settings (P3-M4): check off the UI thread, restore, explicit corrections ----------
        def run_call(self, kind, fn):
            """fn() on a CallWorker; on_<kind>(value) runs on the UI thread. Several may overlap."""
            self.call_seq += 1
            job = self.call_seq

            def wrapped():
                try:
                    value = fn()
                except Exception as e:  # keep the job id, so the thread is always collected
                    value = {"error": f"Unexpected error ({type(e).__name__})."}
                return {"_job": job, "_kind": kind, "value": value}
            thread, worker = QThread(), CallWorker(wrapped)
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.finished.connect(self.call_done)
            self.call_jobs[job] = (thread, worker)
            thread.start()

        def call_done(self, result):
            thread, _ = self.call_jobs.pop(result.get("_job"), (None, None))
            if thread is not None:
                thread.quit()
                thread.wait()
            if "_kind" in result:
                getattr(self, "on_" + result["_kind"])(result["value"])

        def reuse_settings(self):
            r = self.current_history()
            if r is None or self.state is None or self.thread is not None:
                return
            self.reuse_seq += 1
            seq, root, record = self.reuse_seq, self.state["root"], dict(r)
            self.status.setText(f"Checking the saved inputs of {r['task_label']} before reusing them...")
            self.run_call("reuse_checked", lambda: dict(history.check_reuse(root, record), seq=seq))

        def on_reuse_checked(self, check):
            if self.state is None or check.get("seq") != self.reuse_seq or check.get("root") != str(self.state["root"]):
                return  # an older request, or another workshop: never applied
            if "error" in check:
                self.status.setText("Error: the saved settings could not be checked. " + check["error"])
                return
            self.reuse = check
            self.clear_search_box()
            apply_reuse(self.state, check)
            self.anchor = None
            task = tasks.TASKS.get(check["task_id"])
            if task and not check["task_problem"]:
                params = check["parameters"]
                self.output_type.setCurrentText(task["output_type"])
                self.output_type_changed(task["output_type"])
                self.task_box.setCurrentIndex(self.task_box.findData(check["task_id"]))
                self.task_changed()
                if "language_style" in params and task["output_type"] == tasks.SINGLE_FILE:
                    self.style_box.setCurrentText(params["language_style"])
                if "days" in params:
                    self.days_box.setValue(params["days"])
                    self.folder_edit.setText(params.get("folder_name", ""))
            self.efficient_box.setChecked(bool(check["efficient"]))
            self.mode_group.button(1).setChecked(True)
            self.mode_changed(1)
            self.refresh()
            n = len(reuse_blockers(self.reuse, self.state))
            self.status.setText(f"Restored the settings of {check['task_label']} "
                                f"({check['completed_at'].replace('T', ' ')[:16]}). "
                                + (f"{n} item(s) need your attention before Generate." if n else
                                   "Review them, then click Generate."))

        def render_reuse(self):
            while self.reuse_rows.count():
                item = self.reuse_rows.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            reuse = self.reuse
            if not reuse or reuse["root"] != str(self.state["root"]):
                self.reuse_box.setVisible(False)
                return
            pending = reuse_blockers(reuse, self.state)
            self.reuse_box.setVisible(True)
            self.reuse_title.setText(f"Reusing {reuse['task_label']} · {reuse['completed_at'].replace('T', ' ')[:16]}"
                                     + ("" if pending else ". Everything checks out; nothing runs until Generate."))

            def add(text, button=None, fn=None):
                row = QWidget()
                hl = QHBoxLayout(row)
                hl.setContentsMargins(0, 0, 0, 0)
                lbl = QLabel(text)
                lbl.setWordWrap(True)
                lbl.setStyleSheet(f"color: {COLORS['error']};" if button else "")
                hl.addWidget(lbl, 1)
                if button:
                    b = QPushButton(button)
                    b.clicked.connect(lambda _=False: self.later(fn))
                    hl.addWidget(b)
                self.reuse_rows.addWidget(row)
            if "task" in pending:
                add(pending["task"], "Use settings shown", self.reuse_use_shown)
            if "destination" in pending:
                add(pending["destination"], "Save to current folder", self.reuse_use_current_folder)
            for e in reuse["inputs"]:
                key = "input:" + e["rel"]
                if key in pending and e["status"] == "unsafe":
                    add(pending[key], "Leave it out", lambda rel=e["rel"]: self.reuse_drop(rel))
                elif key in pending and e["status"] == "changed":
                    add(pending[key], "Accept current file", lambda rel=e["rel"]: self.reuse_accept(rel))
                elif e["status"] in ("missing", "unusable") and e["path"] and Path(e["path"]) in self.state["selected"]:
                    add(e["message"] + " (see Selected Inputs)")
                elif e.get("accepted") and e.get("page_problem"):
                    add(f"Accepted the current {e['rel']}, but its pages need fixing: {e['page_problem']}")
            self.reuse_done_btn.setVisible(not pending)

        def reuse_entry(self, rel):
            return next(e for e in self.reuse["inputs"] if e["rel"] == rel)

        def reuse_use_shown(self):
            if self.reuse:
                self.reuse["task_resolved"] = True
                self.refresh_selected()

        def reuse_use_current_folder(self):
            if self.reuse:
                self.reuse["destination"]["resolved"] = True
                self.refresh_selected()

        def reuse_drop(self, rel):
            if self.reuse:
                self.reuse_entry(rel)["dropped"] = True
                self.refresh_selected()

        def reuse_accept(self, rel):
            """Re-check the file now (hash + pages against its current page count), then accept it."""
            if not self.reuse:
                return
            seq, root, e = self.reuse_seq, self.state["root"], dict(self.reuse_entry(rel))
            saved = {"path": e["rel"], "pages": e["pages"], "fingerprint": e["fingerprint"]}
            self.status.setText(f"Checking the current {rel}...")
            self.run_call("reuse_accepted", lambda: dict(history.check_input(root, saved), seq=seq, root=str(root)))

        def on_reuse_accepted(self, fresh):
            if not self.reuse or fresh.get("seq") != self.reuse_seq or fresh.get("root") != self.reuse["root"]:
                return
            e = self.reuse_entry(fresh["rel"])
            e.update({k: v for k, v in fresh.items() if k not in ("seq", "root")})
            if e["status"] in ("ok", "changed"):
                e["accepted"] = True
                self.page_info.pop(Path(e["path"]), None)  # recount its pages for the Pages note
                self.status.setText(f"Using the current {e['rel']}." + (f" Its pages need fixing: {e['page_problem']}"
                                                                         if e["page_problem"] else ""))
            else:
                self.status.setText(f"Error: {e['message']}")
            self.refresh_selected()

        def close_reuse(self):
            if self.reuse and not reuse_blockers(self.reuse, self.state):
                self.reuse = None
                self.refresh_selected()

        def retry_history(self):
            """Metadata only: save the kept records again (idempotent by generation_id); no Gemini call."""
            if self.retry_thread is not None or not (self.pending_history or self.pending_reconcile):
                return
            if self.thread is not None or self.org_thread is not None:
                self.status.setText("Wait for the current operation to finish, then retry History.")
                return
            pending, reconciles = dict(self.pending_history), list(self.pending_reconcile)
            self.retry_history_btn.setEnabled(False)
            self.status.setText("Saving: Retrying History...")

            def save_all(items=pending, rec=reconciles):
                return dict(retry_metadata(rec, items), count=len(rec))
            self.retry_thread = QThread()
            self.retry_worker = CallWorker(save_all)
            self.retry_worker.moveToThread(self.retry_thread)
            self.retry_thread.started.connect(self.retry_worker.run)
            self.retry_worker.finished.connect(self.history_retried)
            self.retry_thread.start()

        def history_retried(self, result):
            self.retry_thread.quit()
            self.retry_thread.wait()
            self.retry_thread = None
            outcomes = result.get("records", {})
            failed = [o["message"] for o in outcomes.values() if not o["saved"]] + result.get("failed_reconciles", [])
            for gid, o in outcomes.items():
                if o["saved"]:
                    self.pending_history.pop(gid, None)
            if "records" not in result:
                failed = result.get("errors") or ["Unexpected error."]
            elif not result.get("failed_reconciles"):
                del self.pending_reconcile[:result.get("count", 0)]
            self.retry_history_btn.setVisible(bool(self.pending_history or self.pending_reconcile))
            self.retry_history_btn.setEnabled(True)
            done = (["History entries saved (the PDFs were already saved)"] if outcomes else []) + (
                ["History paths updated for the earlier file changes"] if result.get("count") else [])
            self.status.setText(("History still not saved: " + " ".join(failed)) if failed else
                                "; ".join(done) + ". No file was moved again and generation was not repeated.")
            if self.mode_stack.currentIndex() == 2:
                self.load_history()

        def later(self, fn, *args):
            QTimer.singleShot(0, lambda: fn(*args))  # rebuild rows after the clicked widget's signal returns

        def refresh(self, folder=None):
            """Redraw the current folder, or the accepted search results while a query is shown.
            Never changes the selection (only Refresh prunes). Navigating to a folder ends the search."""
            if folder is not None and self.search_edit.text():
                self.clear_search_box()
            before = self.state["current"]
            entries = workshops.browse(self.state, folder)  # also rechecks the destination folder
            if self.state["current"] != before:
                self.anchor = None  # a range never spans folders
            rel = workshops.relative(self.state, self.state["current"])
            searching = self.search_result is not None
            if searching:
                entries = [dict(m, selected=m["path"] in self.state["selected"]) for m in self.search_result["matches"]]
                self.folder_lbl.setText(describe_search(self.search_result))
            else:
                self.folder_lbl.setText('Workshop root' if rel == '.' else rel)
            self.row_paths = [str(e["path"]) for e in entries]
            self.save_lbl.setText(f"Save to: {'Workshop root' if rel == '.' else rel}")
            self.up_btn.setEnabled(self.state["current"] != self.state["root"])
            self.browser.hot = None  # its row widget is about to be deleted
            self.browser.clear()
            for e in entries:
                path = str(e["path"])
                supported = e["is_dir"] or e["path"].suffix.lower() in inputs.SELECTABLE
                item = QListWidgetItem()
                item.setData(PATH_ROLE, path)
                item.setData(PATH_ROLE + 1, "dir" if e["is_dir"] else "file")
                # Row widgets are invisible to screen readers/UI Automation; name the item itself.
                # Search results use the relative path, so same-name files stay distinguishable.
                shown = e["relative"] if searching else e["name"]
                item.setData(Qt.AccessibleTextRole, ("Folder " if e["is_dir"] else "File ") + shown
                             + (", selected" if e["selected"] else ""))
                row = QWidget()
                hl = QHBoxLayout(row)
                hl.setContentsMargins(8, 4, 8, 4)
                hl.setSpacing(8)
                box = QCheckBox()
                box.setChecked(e["selected"])
                box.setAccessibleName(f"Select {shown}")
                box.setToolTip("Select or deselect")
                box.clicked.connect(lambda _=False, p=path, d=e["is_dir"]:
                                    self.later(self.row_clicked, p, d, True, QApplication.keyboardModifiers()))
                name = QPushButton(e["relative"] if searching else e["name"])
                if e["is_dir"]:
                    decorate(name, "folder")
                name.setMinimumWidth(0)
                name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
                name.setToolTip(e["relative"] if searching else e["name"])
                name.setFlat(True)
                name.setStyleSheet("text-align: left;")
                name.setAccessibleName(f"Select folder {shown}; double-click to open" if e["is_dir"]
                                       else f"Select {shown}; double-click to open in Chrome"
                                       if e["path"].suffix.lower() == ".pdf" else f"Select {shown}")
                name.clicked.connect(lambda _=False, p=path, d=e["is_dir"]:
                                     self.later(self.row_clicked, p, d, False, QApplication.keyboardModifiers()))
                for w in (row, name):  # drag starts here; the checkbox stays a plain checkbox
                    w.setProperty("lnpPath", path)
                    w.installEventFilter(self.row_filter)
                if not supported:
                    name.setToolTip("Organize can use this file; Make me can't (PDF, PPTX, DOCX, TXT, MD only).")
                if e["selected"]:
                    row.setStyleSheet(f"background: {SELECTED_BG}; color: {SELECTED_FG}; border-radius: 8px;")
                elif not supported:
                    name.setStyleSheet(f"text-align: left; color: {COLORS['muted']};")
                hl.addWidget(box)
                hl.addWidget(name, 1)
                if searching and not e["is_dir"]:
                    locate = QPushButton("Show in folder")
                    locate.setAccessibleName(f"Show {e['relative']} in its folder")
                    locate.setToolTip("Open the folder that holds this file (it becomes the Save to folder).")
                    locate.clicked.connect(lambda _=False, p=path: self.later(self.show_in_folder, p))
                    hl.addWidget(locate)
                item.setSizeHint(row.sizeHint())
                self.browser.addItem(item)
                self.browser.setItemWidget(item, row)
            self.render_tags()  # chips belong to the folder now shown
            self.refresh_selected()

        def refresh_selected(self):
            """Selected Inputs from the one workshop selection; Generate eligibility from make_me_status()."""
            selected = workshops.selected_sorted(self.state)
            status = make_me_status(self.state, self.page_info, self.reuse)
            self.selected_list.clear()
            self.page_notes = {}
            folders = 0
            for p in selected:
                rel = workshops.relative(self.state, p)
                exists = p.exists()
                folders += p.is_dir()
                kind = "[folder] " if p.is_dir() else ("[missing] " if not exists else "")
                item = QListWidgetItem()
                item.setData(PATH_ROLE, str(p))
                item.setData(Qt.AccessibleTextRole, f"Selected {kind}{rel}")
                row = QWidget()
                vl = QVBoxLayout(row)
                vl.setContentsMargins(8, 4, 8, 4)
                vl.setSpacing(2)
                hl = QHBoxLayout()
                hl.setSpacing(8)
                vl.addLayout(hl)
                lbl = PathLabel(kind + rel)
                lbl.setTextFormat(Qt.PlainText)
                lbl.setToolTip(str(p))
                if p in status["blockers"] and self.mode_stack.currentIndex() == 1:
                    lbl.setStyleSheet(f"color: {COLORS['error']};")  # reason is in the eligibility note and tooltip
                    lbl.setToolTip(f"{p}\nMake me can't use this: {status['blockers'][p]}")
                remove = decorate(QPushButton(""), "remove-selection")
                remove.setFixedSize(32, 32)
                remove.setStyleSheet("padding: 4px; min-height: 0;")
                remove.setAccessibleName(f"Remove {rel} from selection")
                remove.setToolTip("Deselect only; the file or folder is not deleted.")
                remove.clicked.connect(lambda _=False, q=str(p): self.later(self.remove_selected, q))
                hl.addWidget(lbl, 1)
                if exists and p.suffix.lower() == ".pdf":
                    pages = QLineEdit(self.state.get("pages", {}).get(p, ""))
                    pages.setPlaceholderText("All pages")
                    pages.setFixedWidth(104)
                    pages.setAccessibleName(f"Pages of {rel}")
                    pages.setToolTip("Pages to use, e.g. 1, 3-5, 8 (empty = All pages). Numbers are the PDF's "
                                     "physical pages, starting at 1.")
                    pages.editingFinished.connect(lambda q=p, w=pages: self.later(self.pages_edited, q, w.text()))
                    hl.addWidget(pages)
                    note = QLabel(describe_pages(self.state, p, self.page_info.get(p)))
                    note.setWordWrap(True)
                    note.setProperty("role", "support")
                    vl.addWidget(note)
                    self.page_notes[p] = (pages, note)
                    self.style_page_note(p)
                hl.addWidget(remove)
                item.setSizeHint(row.sizeHint())
                self.selected_list.addItem(item)
                self.selected_list.setItemWidget(item, row)
            files = len(selected) - folders
            self.selected_lbl.setText(f"Selected Inputs ({len(selected)}: {files} file{'s' * (files != 1)}, "
                                      f"{folders} folder{'s' * (folders != 1)})")
            self.eligibility_lbl.setText(status["message"])
            busy = self.thread is not None or self.org_thread is not None
            self.generate_btn.setEnabled(status["ok"] and not busy)
            self.generate_btn.setVisible(self.mode_stack.currentIndex() == 1)
            for action, b in self.action_btns.items():
                b.setEnabled(not busy)
            self.update_bin_buttons()
            self.open_doc_btn.setEnabled(bool(self.last_paths))
            self.open_folder_btn.setEnabled(bool(self.last_paths))
            self.count_selected_pages()
            self.render_reuse()

        # ---------- PDF pages (P3-M2): page counts off the UI thread; text lives in state["pages"] ----------
        def style_page_note(self, path):
            _, note = self.page_notes[path]
            bad = page_problem(self.state, path, self.page_info.get(path)) is not None
            note.setStyleSheet(f"color: {COLORS['error']};" if bad else "")

        def pages_edited(self, path, text):
            if self.state is None or path not in self.state["selected"]:
                return
            if (self.state.get("pages", {}).get(path) or "") == text.strip():
                return
            workshops.set_pages(self.state, path, text)
            self.refresh_selected()

        def count_selected_pages(self):
            """Count pages of selected PDFs that are new or changed on disk; one worker at a time."""
            if self.pages_thread is not None or self.state is None:
                return
            todo = []
            for p in self.state["selected"]:
                if p.suffix.lower() != ".pdf" or not p.is_file():
                    continue
                known = self.page_info.get(p)
                try:
                    if known is None or known.get("mtime") != p.stat().st_mtime:
                        todo.append(p)
                except OSError:
                    continue
            if not todo:
                return
            self.pages_thread = QThread()
            self.pages_worker = CallWorker(lambda paths=tuple(todo): count_pages(paths))
            self.pages_worker.moveToThread(self.pages_thread)
            self.pages_thread.started.connect(self.pages_worker.run)
            self.pages_worker.finished.connect(self.pages_counted)
            self.pages_thread.start()

        def pages_counted(self, result):
            self.pages_thread.quit()
            self.pages_thread.wait()
            self.pages_thread = None
            if "records" in result:  # CallWorker's last-resort fallback
                return
            self.page_info.update(result)
            if any(edit.hasFocus() for edit, _ in self.page_notes.values()):
                for p, (_, note) in self.page_notes.items():  # never rebuild under the cursor
                    note.setText(describe_pages(self.state, p, self.page_info.get(p)))
                    self.style_page_note(p)
            else:
                self.refresh_selected()

        def row_clicked(self, path, is_dir, from_box, mods):
            """Click (box or name, file or folder) toggles; Ctrl+click too; Shift+click adds anchor..row.
            Opening a folder or PDF is a double-click (open_row)."""
            if mods & Qt.ShiftModifier and self.anchor is not None:
                workshops.select_range(self.state, self.row_paths, self.anchor, path)
                return self.refresh()
            self.anchor = path
            self.last_dir_click = path if not from_box else None
            self.toggle(path)

        def open_row(self, path):
            """Double-click: open a folder in the browser or a PDF in Chrome, undoing the toggle its first click made."""
            if not path:
                return
            p = Path(path)
            if not os.path.lexists(p):
                self.last_dir_click = None
                self.status.setText(f"Error: {p.name} no longer exists. Click Refresh to update the list.")
                return
            is_pdf = p.is_file() and p.suffix.lower() == ".pdf"
            if not (p.is_dir() or is_pdf):
                return
            if self.last_dir_click == path:
                try:
                    workshops.toggle_selection(self.state, path)
                except workshops.WorkshopError:
                    pass
            self.last_dir_click = None
            if is_pdf:
                return self.view_pdf(path)
            self.open_folder(path)

        def view_pdf(self, path):
            self.refresh()  # shows the undone toggle
            if not Path(path).is_file():
                self.status.setText(f"Error: {Path(path).name} no longer exists. Click Refresh to update the list.")
                return
            try:
                if open_pdf(path):
                    self.status.setText(f"Opened {Path(path).name} in Chrome.")
                elif QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
                    self.status.setText(f"Chrome was not found; opened {Path(path).name} in the default PDF viewer.")
                else:
                    self.status.setText(f"Error: {Path(path).name} could not be opened (Chrome was not found).")
            except OSError as e:
                self.status.setText(f"Error: Chrome could not open {Path(path).name} ({type(e).__name__}).")

        # ---------- search (P3-M1): debounce -> SearchWorker -> accept only the newest current result ----------
        def search_text_changed(self, text):
            if text.strip():
                self.search_note.setText("Searching...")
                self.search_note.setVisible(True)
                self.search_timer.start()  # restarts on every keystroke
            else:
                self.cancel_search()
                self.search_note.setVisible(False)
                if self.search_result is not None:
                    self.search_result = None
                    self.anchor = None
                    self.refresh()  # back to the current folder; the selection is untouched

        def cancel_search(self):
            """Make every in-flight search obsolete; their threads finish (quickly) and are discarded."""
            self.search_timer.stop()
            self.search_seq += 1
            for _, worker in self.search_jobs.values():
                worker.cancel.set()

        def clear_search_box(self):
            """Empty the box without a redraw (the caller redraws)."""
            self.cancel_search()
            self.search_edit.blockSignals(True)
            self.search_edit.clear()
            self.search_edit.blockSignals(False)
            self.search_result = None
            self.search_note.setVisible(False)

        def start_search(self):
            query = self.search_edit.text().strip()
            if not query or self.state is None:
                return
            self.cancel_search()
            request = {"root": self.state["root"], "query": query, "seq": self.search_seq}
            thread, worker = QThread(), SearchWorker(request)
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.finished.connect(self.search_finished)  # queued onto the UI thread (Window is a QObject)
            self.search_jobs[request["seq"]] = (thread, worker)
            self.search_note.setText("Searching...")
            self.search_note.setVisible(True)
            thread.start()

        def search_finished(self, result):
            request = result["request"]
            thread, _ = self.search_jobs.pop(request["seq"], (None, None))
            if thread is not None:
                thread.quit()
                thread.wait()
            if result["cancelled"] or not search_is_current(request, self.state, self.search_edit.text(), self.search_seq):
                return  # obsolete: a newer query, a cleared box or another workshop
            self.search_result = result
            self.anchor = None
            self.search_note.setText("\n".join(result["warnings"]) or (
                "No matching names." if not result["matches"] else
                "Click to select; double-click a folder or PDF to open it. Save to stays the current folder."))
            self.search_note.setVisible(True)
            self.refresh()

        def show_in_folder(self, path):
            p = Path(path)
            if not p.exists() or not p.parent.is_dir():
                self.status.setText(f"Error: {p.name} no longer exists. Click Refresh to update the results.")
                return
            try:
                self.refresh(p.parent)  # explicit navigation: ends the search, Save to follows
            except workshops.WorkshopError as e:
                self.status.setText(f"Error: {e.message}")
                return
            for i in range(self.browser.count()):
                item = self.browser.item(i)
                if item.data(PATH_ROLE) == str(p.resolve()):
                    self.browser.setCurrentItem(item)
                    self.browser.scrollToItem(item)
                    break
            self.status.setText(f"Showing {p.name} in {workshops.relative(self.state, p.parent)}.")

        def closeEvent(self, event):
            for t in [self.pages_thread, self.hist_thread, self.retry_thread] + [t for t, _ in self.call_jobs.values()]:
                if t is not None:
                    t.quit()
                    t.wait()
            self.cancel_search()
            for thread, _ in list(self.search_jobs.values()):
                thread.quit()
                thread.wait()
            super().closeEvent(event)

        def toggle(self, path):
            try:
                workshops.toggle_selection(self.state, path)
            except workshops.WorkshopError as e:
                self.status.setText(f"Error: {e.message}")
            self.refresh()

        def open_folder(self, path):
            try:
                self.refresh(path)
            except workshops.WorkshopError as e:
                self.status.setText(f"Error: {e.message}")

        def remove_selected(self, path):
            workshops.deselect(self.state, path)
            self.refresh()

        # ---------- name tags: metadata in name_tags, the rename itself through the organizer ----------
        def load_tags(self):
            try:
                self.tags, self.tag_error = name_tags.load(), ""
            except name_tags.TagError as e:
                self.tags, self.tag_error = None, e.message

        def render_tags(self):
            while self.chip_row.count():
                w = self.chip_row.takeAt(0).widget()
                if w:
                    w.deleteLater()
            if self.tags is None:
                for w in (self.tag_edit, self.tag_add_btn):
                    w.setEnabled(False)
                self.tag_note.setText(self.tag_error)
                return
            current = name_tags.chips(self.tags, self.state["current"])
            for tag in current:
                self.chip_row.addWidget(TagChip(tag))
                rm = QPushButton("x")
                rm.setFixedWidth(32)
                rm.setStyleSheet("padding: 4px; min-height: 22px;")
                rm.setAccessibleName(f"Remove tag {tag}")
                rm.setToolTip(f"Remove the {tag} tag (its numbering is remembered)")
                rm.clicked.connect(lambda _=False, t=tag: self.later(self.remove_tag, t))
                self.chip_row.addWidget(rm)
            self.chip_row.addStretch(1)
            full = len(current) >= name_tags.MAX_CHIPS
            self.tag_edit.setEnabled(not full)
            self.tag_add_btn.setEnabled(not full)
            self.tag_note.setText(f"{name_tags.MAX_CHIPS} tags is the limit for a folder; remove one to add another."
                                  if full else "Drag a tag onto a file to rename it tag_1, tag_2, ... (extension kept).")

        def add_tag(self):
            if self.tags is None:
                return
            try:
                name = name_tags.add_chip(self.tags, self.state["current"], self.tag_edit.text())
                self.tag_edit.clear()
                self.status.setText(f"Tag '{name}' saved for this folder.")
            except name_tags.TagError as e:
                self.status.setText(f"Tag not added: {e.message}")
            self.render_tags()

        def remove_tag(self, tag):
            try:
                name_tags.remove_chip(self.tags, self.state["current"], tag)
                self.status.setText(f"Tag '{tag}' removed; recreating it continues its numbering.")
            except name_tags.TagError as e:
                self.status.setText(e.message)
            self.render_tags()

        def apply_tag(self, tag, path):
            """A chip dropped on a browser row: reserve tag_N, then plan and run one rename."""
            if self.tags is None or self.busy():
                return
            if not path or Path(path).is_dir():
                self.status.setText("Drop a tag on a file; nothing was renamed.")
                return
            if self.search_result is not None:
                self.status.setText("Clear the search to tag files; tags belong to the folder shown. Nothing was renamed.")
                return
            folder = self.state["current"]
            try:
                res = name_tags.reserve(self.tags, folder, tag, path)
            except name_tags.TagError as e:
                self.status.setText(f"Name tag: {e.message}")
                return
            request = organizing.capture_request(self.state, "rename", {"new_name": res["new_name"]}, sources=[path])
            try:
                plan = organizing.plan_action(request)
            except organizing.OrganizeError as e:
                try:
                    name_tags.finish(self.tags, folder, res, succeeded=False)
                except name_tags.TagError:
                    pass
                self.status.setText(f"Name tag: {e.message}")
                return
            self.pending_tag = (folder, res)
            self.run_plan(plan)

        # ---------- recent downloads bin: discovery in downloads, import through the paste-copy planner ----------
        def toggle_bin(self):
            opening = not self.bin_panel.isVisible()
            self.bin_panel.setVisible(opening)
            if opening:
                self.reload_bin()

        def reload_bin(self):
            """On demand only (startup, opening, Refresh, after an import); no timer."""
            if self.bin_thread is not None:
                return
            self.bin_note.setText("Checking Chrome downloads...")
            self.bin_thread = QThread()
            self.bin_worker = CallWorker(downloads.recent_downloads)
            self.bin_worker.moveToThread(self.bin_thread)
            self.bin_thread.started.connect(self.bin_worker.run)
            self.bin_worker.finished.connect(self.bin_loaded)
            self.bin_thread.start()

        def bin_loaded(self, result):
            self.bin_thread.quit()
            self.bin_thread.wait()
            self.bin_thread = None
            ticked = {self.bin_list.item(i).data(PATH_ROLE) for i in range(self.bin_list.count())
                      if self.bin_list.item(i).checkState() == Qt.Checked}
            self.bin_records = result["records"]
            self.bin_list.blockSignals(True)
            self.bin_list.clear()
            for r in self.bin_records:
                item = QListWidgetItem(describe_download(r))
                item.setData(PATH_ROLE, r["path"])
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if r["path"] in ticked else Qt.Unchecked)
                item.setToolTip(f"{r['path']}\nCompleted {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r['downloaded_at']))}"
                                f" ({r['timestamp_source']})")
                self.bin_list.addItem(item)
            self.bin_list.blockSignals(False)
            n = len(self.bin_records)
            self.bin_btn.setText(f"Recent downloads ({n})" if n else "Recent downloads")
            note = (f"{n} file(s) Chrome finished downloading in the last hour." if n else
                    "No completed Chrome downloads from the last hour.")
            self.bin_note.setText("\n".join([note] + result.get("errors", [])))
            self.update_bin_buttons()

        def ticked_downloads(self) -> list[str]:
            return [self.bin_list.item(i).data(PATH_ROLE) for i in range(self.bin_list.count())
                    if self.bin_list.item(i).checkState() == Qt.Checked]

        def update_bin_buttons(self):
            busy = self.busy()
            self.bin_copy_btn.setEnabled(bool(self.ticked_downloads()) and not busy)

        def copy_downloads(self):
            """Ticked tray entries -> the existing paste-copy plan for the folder open right now."""
            paths = self.ticked_downloads()
            if not paths or self.thread is not None or self.org_thread is not None:
                return
            request = organizing.capture_request(self.state, "paste", {"clipboard": {"paths": paths, "effect": "copy"}})
            try:
                plan = organizing.plan_action(request)
            except organizing.OrganizeError as e:
                self.status.setText(f"Copy to current folder: {e.message}\n" +
                                    "\n".join(organizing.label(request["workshop_root"], p) for p in e.paths))
                self.reload_bin()
                return
            shown = "\n".join(organizing.preview(plan)[:15])
            if QMessageBox.question(self, "Copy to current folder",
                                    f"Copy {len(plan['items'])} download(s) here? The originals stay where they are."
                                    f"\n\n{shown}", QMessageBox.Ok | QMessageBox.Cancel) != QMessageBox.Ok:
                self.status.setText("Cancelled. Nothing was copied.")
                return
            self.run_plan(plan)

        # ---------- drag and drop: this UI starts drags and finds targets; organizing.plan_drop validates ----------
        def busy(self):
            return self.thread is not None or self.org_thread is not None or self.retry_thread is not None

        def drop_allowed(self, md, folder):
            """Hover check behind the cursor and highlight; plan_drop repeats it with full validation."""
            payload = drop_payload(md)
            if payload is None or self.busy() or not self.state or not workshops.is_inside(self.state["root"], Path(folder)):
                return False
            return organizing.drop_problem(payload[1], folder) is None

        def record_drop(self, md, folder):
            """Called inside drag.exec; the plan runs after the drag loop returns (rows may be rebuilt)."""
            effect, paths = drop_payload(md)
            self.dropped = (effect, paths, folder)

        def run_drag(self, source, effect, paths):
            if self.busy():
                self.status.setText("Wait for the current operation to finish before dragging.")
                return
            md = QMimeData()
            md.setData(DROP_MIME[effect], json.dumps(paths).encode("utf-8"))
            drag = QDrag(source)
            drag.setMimeData(md)
            drag.setPixmap(drag_pixmap(effect, paths))
            drag.setHotSpot(QPoint(-14, -8))  # label sits beside the cursor, not under it
            self.dropped = None
            drag.exec(Qt.MoveAction if effect == "move" else Qt.CopyAction)
            dropped, self.dropped = self.dropped, None
            if dropped is None:
                self.status.setText("Drag cancelled. Nothing was changed.")
                return
            self.later(self.handle_drop, *dropped)

        def start_browser_drag(self, path, source):
            paths = organizing.drop_sources(workshops.selected_sorted(self.state), path)
            self.run_drag(source, "move", paths)

        def start_download_drag(self, path):
            self.run_drag(self.bin_list, "copy", organizing.drop_sources(self.ticked_downloads(), path))

        def handle_drop(self, effect, paths, folder):
            """One drop -> plan_drop (all-or-nothing preflight) -> the organizer worker."""
            if self.busy():
                return
            verb = "Move" if effect == "move" else "Copy"
            try:
                plan = organizing.plan_drop(self.state, effect, paths, folder)
            except organizing.OrganizeError as e:
                shown = "\n".join(organizing.label(self.state["root"], p) for p in e.paths)
                self.status.setText(f"{verb} not done: {e.message}" + (f"\n{shown}" if shown else ""))
                if effect == "copy":
                    self.reload_bin()  # a vanished download leaves the tray
                return
            self.pending_drop = effect
            self.run_plan(plan)

        def refresh_clicked(self):
            gone = workshops.prune(self.state)
            self.reload_bin()
            self.load_tags()
            self.refresh()
            if self.search_edit.text().strip():
                self.start_search()  # rerun the active query over the current disk state
            if gone:
                self.status.setText("Refresh removed from the selection (no longer on disk): " + ", ".join(
                    workshops.relative(self.state, p) for p in gone))

        def go_up(self):
            if self.state["current"] != self.state["root"]:
                self.refresh(self.state["current"].parent)

        # ---------- organizer: click -> capture -> plan -> (confirm) -> execute off-thread -> reconcile ----------
        def organize(self, action):
            if self.busy():
                if self.retry_thread is not None:
                    self.status.setText("Wait for the History retry to finish, then try again.")
                return
            request = organizing.capture_request(self.state, action)  # snapshot before any dialog
            if action in ("wrap", "super_wrap"):
                name, ok = QInputDialog.getText(self, ACTION_VERB[action], "New folder name (created in the current folder):")
                request["parameters"]["folder_name"] = name if ok else None
            elif action == "paste":
                request["parameters"]["clipboard"] = organizing.clipboard_read()
            try:
                plan = organizing.plan_action(request)
            except organizing.OrganizeError as e:
                paths = "\n".join(organizing.label(request["workshop_root"], p) for p in e.paths)
                self.status.setText(f"{ACTION_VERB.get(action, action)}: {e.message}" + (f"\n{paths}" if paths else ""))
                return
            if action == "copy":
                organizing.clipboard_put([i["source"] for i in plan["items"]])
                self.status.setText(f"Copied {len(plan['items'])} item(s) to the clipboard. "
                                    "Paste here or in File Explorer; nothing was copied yet.")
                return
            lines = organizing.preview(plan)
            if action in ("delete", "super_wrap") or plan.get("batch_id"):
                title = {"delete": "Delete", "super_wrap": "Super Wrap"}.get(action, "Move (cut) into this folder")
                text = {"delete": f"Send {len(lines)} item(s) to the Recycle Bin?",
                        "super_wrap": f"Move {len(lines)} item(s) into this grouped layout?"}.get(
                    action, f"Move {len(lines)} item(s) here? Their originals will be removed.")
                if plan.get("skipped"):
                    text += f" ({len(plan['skipped'])} already moved earlier will be skipped.)"
                shown = "\n".join(lines[:15]) + (f"\n... and {len(lines) - 15} more" if len(lines) > 15 else "")
                if QMessageBox.question(self, title, f"{text}\n\n{shown}",
                                        QMessageBox.Ok | QMessageBox.Cancel) != QMessageBox.Ok:
                    self.status.setText("Cancelled. Nothing was changed.")
                    return
            self.run_plan(plan)

        def run_plan(self, plan):
            """Execute a validated plan off the UI thread (organizer buttons and name-tag renames)."""
            self.status.setText(f"{ACTION_VERB[plan['action']]}: working on {len(plan['items'])} item(s)...")
            self.org_thread = QThread()
            self.org_worker = OrganizeWorker(plan)
            self.org_worker.moveToThread(self.org_thread)
            self.org_thread.started.connect(self.org_worker.run)
            self.org_worker.finished.connect(self.organize_finished)
            self.refresh_selected()  # disables actions and Generate while paths are in use
            self.org_thread.start()

        def organize_finished(self, result):
            self.org_thread.quit()
            self.org_thread.wait()
            self.org_thread = None
            workshops.reconcile(self.state, result["outcomes"])
            tag_note = ""
            if self.tags is not None:  # tag metadata follows confirmed outcomes only
                try:
                    if self.pending_tag:
                        folder, res = self.pending_tag
                        name_tags.finish(self.tags, folder, res, succeeded=result["status"] == "ok")
                    name_tags.save_reconciled(self.tags, result["outcomes"])
                except name_tags.TagError as e:
                    tag_note = "\n" + e.message
            self.pending_tag = None
            drop, self.pending_drop = self.pending_drop, None
            if result["action"] == "paste":
                self.reload_bin()  # import reconciliation: drop expired or missing entries
            try:
                organizing.clipboard_after(result)
            except Exception:
                pass  # clipboard trouble must not hide the file report
            hist = result.get("history") or {}
            moves = history.confirmed_moves(result["outcomes"])
            for gid, (root, rec) in list(self.pending_history.items()):  # unsaved records follow the move too
                if moves and os.path.normcase(str(root)) == os.path.normcase(str(result["root"])):
                    self.pending_history[gid] = (root, history.remap_record(rec, root, moves)[0])
            hist_note = ""
            if hist.get("needed") and not hist.get("ok"):
                self.pending_reconcile.append((result["root"], hist["moves"], hist["at"]))
                hist_note = (f"\nThe file changes above are done, but History paths were not updated: {hist['message']} "
                             "Use Retry saving history (metadata only; no file is moved again).")
            elif hist.get("warning"):
                hist_note = "\n" + hist["warning"]
            self.retry_history_btn.setVisible(bool(self.pending_history or self.pending_reconcile))
            self.refresh()
            if self.search_edit.text().strip():
                self.start_search()  # moved/deleted entries change the matches
            self.status.setText((describe_drop(result, drop) if drop else describe_outcomes(result)) + tag_note + hist_note)
            if moves and self.mode_stack.currentIndex() == 2:
                self.load_history()
            if moves and self.mode_stack.currentIndex() == 3:
                self.load_progress()  # reconciled History paths, same ids and checkboxes

        # ---------- generation ----------
        def generate(self):
            if self.thread is not None or self.org_thread is not None or not make_me_status(self.state, self.page_info, self.reuse)["ok"]:
                return  # duplicate click while running, or the selection has entries Make me can't use
            request = build_request(self.state, self.task_box.currentData(), self.current_parameters(),
                                    self.provider == "codex" or self.efficient_box.isChecked(), self.provider)
            try:  # Days / Folder name / style checked before any work
                tasks.validate_parameters(request["task_id"], request["parameters"])
            except tasks.TaskError as e:
                self.status.setText(f"Error: {e.message}")
                return
            self.generate_btn.setEnabled(False)
            self.last_paths = []
            self.reuse = None  # resolved by now; the request is captured
            self.status.setText("Starting...")
            self.thread = QThread()
            self.worker = Worker(request)
            self.worker.moveToThread(self.thread)
            self.thread.started.connect(self.worker.run)
            self.worker.progress.connect(self.status.setText)
            self.worker.finished.connect(self.job_finished)
            self.worker.decision_needed.connect(self.answer_decisions)  # queued onto the UI thread
            self.thread.start()

        def choose_for(self, decision) -> str:
            """Dialog for one scan / no-text file; returns 'process_original' or 'cancel'."""
            kind = decision.get("unit_kind", "page")
            units = decision["units"]
            where = (f" ({kind}{'s' if len(units) > 1 else ''} {', '.join(map(str, units))})" if units else "")
            box = QMessageBox(QMessageBox.Question, "Little text found",
                              f"{decision['source_id']}{where} has little or no extractable text. It may be a scan.\n\n"
                              "Process original sends this file itself to Gemini (other files stay as text). "
                              "Cancel stops the job; nothing is sent.", parent=self)
            original = box.addButton("Process original", QMessageBox.AcceptRole)
            box.addButton(QMessageBox.Cancel)
            box.exec()
            return "process_original" if box.clickedButton() is original else "cancel"

        def answer_decisions(self, decisions):
            answer = {}
            for d in decisions:
                answer[d["source_id"]] = self.choose_for(d)
                if answer[d["source_id"]] == "cancel":
                    break
            self.worker.answer = answer
            self.worker.answered.set()

        def job_finished(self, result):
            # quit() before wait(): a queued quit would only run after this slot returns (deadlock)
            self.thread.quit()
            self.thread.wait()
            self.thread = None
            if result["status"] == "cancelled":
                self.status.setText("Cancelled. Nothing was sent or saved.")
            elif result["status"] == "ok":
                self.last_paths = result["paths"]
                self.last_output_root = result["output_root"]
                h = result.get("history") or {}
                if not h.get("saved") and h.get("record"):  # kept with its own workshop for a retry
                    self.pending_history[h["record"]["generation_id"]] = (self.worker.request["workshop_root"],
                                                                          h["record"])
                self.retry_history_btn.setVisible(bool(self.pending_history))
                self.status.setText(describe_saved(result))
                if self.mode_stack.currentIndex() == 2:
                    self.load_history()
                if self.mode_stack.currentIndex() == 3:
                    self.load_progress()
            else:
                self.status.setText(describe_error(result["error"]))
            if self.state:
                self.refresh()  # show the new file; selection is unchanged either way

        def open_document(self):
            if self.last_paths:
                QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_paths[0]))

        def open_output_folder(self):
            if self.last_paths:
                folder = self.last_output_root or str(Path(self.last_paths[0]).parent)
                QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    app.setApplicationName("Late Night Pal")
    win = Window()
    win.show()
    return app.exec()
