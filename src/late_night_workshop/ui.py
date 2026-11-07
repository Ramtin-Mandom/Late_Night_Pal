"""Late Night Pal desktop UI: workshop start screen, browser + selection, task panel.

The UI owns clicks, highlights and dialogs; `workshops` owns path/selection truth and
`generation.generate()` (run on a worker thread) owns the job.
"""

import threading
from pathlib import Path

from . import generation, inputs, name_tags, organizing, tasks, workshops

SELECTED_BG = "#2563eb"  # blue highlight for selected entries
SELECTED_FG = "#ffffff"
ORGANIZE_ACTIONS = [("delete", "Delete"), ("rip", "Rip"), ("wrap", "Wrap"), ("copy", "Copy"), ("paste", "Paste"),
                    ("super_wrap", "Super Wrap")]
RIP_HELP = "Move each selected folder's contents up one level."
TAG_MIME = "application/x-late-night-pal-tag"
ACTION_VERB = {"rename": "Name tag", "wrap": "Wrap", "super_wrap": "Super Wrap", "rip": "Rip", "delete": "Delete", "paste": "Paste", "copy": "Copy"}
EFFICIENT_NOTE = ("Converts files to text before sending them to Gemini. This can be much cheaper for some files, "
                  "but diagrams, equations, tables, and formatting may be lost.")


STAGE_LABELS = {"preparing": "Preparing", "awaiting_input": "Waiting for you", "generating": "Gemini",
                "validating": "Checking", "rendering": "Rendering", "publishing": "Saving"}
FAILED_STAGE = {"preparing": "Preparing inputs", "validating": "Checking the request or Gemini's response",
                "generating": "Gemini request", "rendering": "Local PDF compilation", "publishing": "Saving"}
NEXT_STEP = {
    "compile_failed": "Click Generate to try again; a fresh Gemini response usually compiles. The LaTeX log is listed below.",
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
                  efficient: bool = False) -> dict:
    """Snapshot taken at Generate time; later browsing cannot change it."""
    return {
        "workshop_root": str(state["root"]),
        "destination": str(state["current"]),
        "selected_paths": [str(p) for p in workshops.selected_sorted(state)],
        "task_id": task_id,
        "parameters": dict(parameters or {}),
        "efficient": bool(efficient),
    }


def make_me_status(state: dict) -> dict:
    """Generate eligibility from the shared selection: {ok, blockers: {path: reason}, message}.
    Feedback only; generate() still runs workshops.validate_paths() at the boundary."""
    selected = workshops.selected_sorted(state)
    blockers = inputs.generation_blockers(selected)
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


def run_app() -> int:
    from PySide6.QtCore import QMimeData, QObject, Qt, QThread, QTimer, QUrl, Signal
    from PySide6.QtGui import QBrush, QColor, QDesktopServices, QDrag
    from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
                                   QInputDialog, QLabel, QLineEdit,
                                   QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
                                   QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

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
            except Exception as e:  # last-resort guard so the UI never hangs in "running"
                result = {"status": "error", "error": {"message": f"Unexpected error ({type(e).__name__})."}}
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
            self.finished.emit(result)

    class TagBrowser(QListWidget):
        """Folder browser that accepts a name-tag chip dropped on a row."""
        tag_dropped = Signal(str, str)  # tag, path of the row ("" for empty space)

        def __init__(self):
            super().__init__()
            self.setAcceptDrops(True)
            self.viewport().setAcceptDrops(True)

        def dragEnterEvent(self, e):
            e.acceptProposedAction() if e.mimeData().hasFormat(TAG_MIME) else e.ignore()

        def dragMoveEvent(self, e):
            e.acceptProposedAction() if e.mimeData().hasFormat(TAG_MIME) else e.ignore()

        def dropEvent(self, e):
            if not e.mimeData().hasFormat(TAG_MIME):
                return e.ignore()
            item = self.itemAt(e.position().toPoint())
            e.acceptProposedAction()
            self.tag_dropped.emit(bytes(e.mimeData().data(TAG_MIME)).decode("utf-8"),
                                  item.data(PATH_ROLE) if item else "")

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
            self.last_paths = []
            self.last_output_root = None
            self.stack = QStackedWidget()
            self.stack.addWidget(self._start_page())
            self.stack.addWidget(self._workshop_page())
            self.setCentralWidget(self.stack)
            self.resize(900, 600)
            self.show_start()

        # ---------- start screen ----------
        def _start_page(self):
            page = QWidget()
            lay = QVBoxLayout(page)
            title = QLabel("Welcome to Late Night Pal")
            title.setStyleSheet("font-size: 20px; font-weight: 600;")
            lay.addWidget(title)
            lay.addWidget(QLabel("Recent Workshops"))
            self.recent_list = QListWidget()
            self.recent_list.itemClicked.connect(self.open_recent)
            lay.addWidget(self.recent_list)
            row = QHBoxLayout()
            self.open_btn = QPushButton("Open Workshop")
            self.create_btn = QPushButton("Create Workshop")
            self.open_btn.clicked.connect(self.open_workshop_dialog)
            self.create_btn.clicked.connect(self.create_workshop_dialog)
            row.addWidget(self.open_btn)
            row.addWidget(self.create_btn)
            lay.addLayout(row)
            return page

        def show_start(self):
            self.recent_list.clear()
            recents = workshops.load_recents()
            for r in recents:
                item = QListWidgetItem(r["path"] if r["exists"] else f"{r['path']}  (missing)")
                item.setData(PATH_ROLE, r["path"])
                if not r["exists"]:
                    item.setForeground(QBrush(QColor("#888888")))
                self.recent_list.addItem(item)
            if not recents:
                self.recent_list.addItem(QListWidgetItem("No recent workshops yet."))
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
            top = QHBoxLayout()
            self.back_btn = QPushButton("< Workshops")
            self.back_btn.clicked.connect(self.show_start)
            self.root_lbl = QLabel()
            top.addWidget(self.back_btn)
            top.addWidget(self.root_lbl, 1)
            lay.addLayout(top)

            body = QHBoxLayout()
            left = QVBoxLayout()
            nav = QHBoxLayout()
            self.up_btn = QPushButton("Up")
            self.up_btn.clicked.connect(self.go_up)
            self.refresh_btn = QPushButton("Refresh")
            self.refresh_btn.setToolTip("Rescan this folder and drop selected entries that no longer exist.")
            self.refresh_btn.clicked.connect(self.refresh_clicked)
            self.folder_lbl = QLabel()
            nav.addWidget(self.up_btn)
            nav.addWidget(self.refresh_btn)
            nav.addWidget(self.folder_lbl, 1)
            left.addLayout(nav)
            self.browser = TagBrowser()
            self.browser.tag_dropped.connect(lambda tag, path: self.later(self.apply_tag, tag, path))
            left.addWidget(self.browser)
            hint = QLabel("Tick the box to select a file or folder. Click a folder's name to open it; "
                          "clicking a file's name also selects it.")
            hint.setWordWrap(True)
            left.addWidget(hint)
            left.addWidget(QLabel("Name tags (this folder)"))
            tag_row = QHBoxLayout()
            self.tag_edit = QLineEdit()
            self.tag_edit.setPlaceholderText("New tag, e.g. assignment")
            self.tag_edit.setAccessibleName("New tag name")
            self.tag_edit.returnPressed.connect(self.add_tag)
            self.tag_add_btn = QPushButton("+")
            self.tag_add_btn.setAccessibleName("Add tag")
            self.tag_add_btn.clicked.connect(self.add_tag)
            tag_row.addWidget(self.tag_edit, 1)
            tag_row.addWidget(self.tag_add_btn)
            left.addLayout(tag_row)
            self.chip_box = QWidget()
            self.chip_row = QHBoxLayout(self.chip_box)
            self.chip_row.setContentsMargins(0, 0, 0, 0)
            left.addWidget(self.chip_box)
            self.tag_note = QLabel("")
            self.tag_note.setWordWrap(True)
            self.tag_note.setStyleSheet("color: #666666; font-size: 11px;")
            left.addWidget(self.tag_note)
            body.addLayout(left, 3)

            right = QVBoxLayout()
            self.selected_lbl = QLabel("Selected Inputs (0)")
            right.addWidget(self.selected_lbl)
            self.selected_list = QListWidget()
            right.addWidget(self.selected_list)
            modes = QHBoxLayout()
            self.mode_group = QButtonGroup(page)
            self.mode_stack = QStackedWidget()
            for i, label in enumerate(("Organize", "Make me")):
                b = QPushButton(label)
                b.setCheckable(True)
                self.mode_group.addButton(b, i)
                modes.addWidget(b)
            right.addLayout(modes)
            right.addWidget(self.mode_stack)
            org_page = QWidget()
            org = QVBoxLayout(org_page)
            self.action_btns = {}
            grid = QHBoxLayout()
            for action, label in ORGANIZE_ACTIONS:
                b = QPushButton(label)
                if action == "super_wrap":
                    b.setToolTip("Wrap into a new folder, grouping files by shared name parts such as Cal_1_...")
                b.clicked.connect(lambda _=False, a=action: self.organize(a))
                self.action_btns[action] = b
                grid.addWidget(b)
            org.addLayout(grid)
            rip_help = QLabel(f"Rip: {RIP_HELP}")
            rip_help.setWordWrap(True)
            org.addWidget(rip_help)
            org.addStretch(1)
            make_page = QWidget()
            right_outer, right = right, QVBoxLayout(make_page)
            right.setContentsMargins(0, 0, 0, 0)
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
            self.efficient_note.setStyleSheet("color: #666666; font-size: 11px;")
            right.addWidget(self.efficient_box)
            right.addWidget(self.efficient_note)
            self.output_type.currentTextChanged.connect(self.output_type_changed)
            self.task_box.currentIndexChanged.connect(self.task_changed)
            self.output_type.setCurrentText(tasks.SINGLE_FILE)
            self.output_type_changed(tasks.SINGLE_FILE)
            self.eligibility_lbl = QLabel("")
            self.eligibility_lbl.setWordWrap(True)
            self.eligibility_lbl.setStyleSheet("color: #b91c1c;")
            right.addWidget(self.eligibility_lbl)
            self.generate_btn = QPushButton("Generate")
            self.generate_btn.clicked.connect(self.generate)
            right.addWidget(self.generate_btn)
            row = QHBoxLayout()
            self.open_doc_btn = QPushButton("Open document")
            self.open_folder_btn = QPushButton("Open output folder")
            self.open_doc_btn.clicked.connect(self.open_document)
            self.open_folder_btn.clicked.connect(self.open_output_folder)
            row.addWidget(self.open_doc_btn)
            row.addWidget(self.open_folder_btn)
            right.addLayout(row)
            right.addStretch(1)
            self.mode_stack.addWidget(org_page)
            self.mode_stack.addWidget(make_page)
            self.mode_group.idClicked.connect(self.mode_changed)
            self.mode_group.button(1).setChecked(True)  # Make me by default, for continuity
            self.mode_stack.setCurrentIndex(1)
            self.status = QLabel("")
            self.status.setWordWrap(True)
            self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
            right_outer.addWidget(self.status)
            body.addLayout(right_outer, 2)
            lay.addLayout(body)
            return page

        def output_type_changed(self, output_type):
            self.task_box.blockSignals(True)
            self.task_box.clear()
            for task_id, label in tasks.tasks_for(output_type):
                self.task_box.addItem(label, task_id)
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
            self.root_lbl.setText(f"Workshop: {state['root']}")
            self.load_tags()
            self.refresh()
            self.stack.setCurrentIndex(1)

        def mode_changed(self, index):
            """Switch Organize / Make me; selection and every Make me setting are untouched."""
            self.mode_stack.setCurrentIndex(index)
            self.refresh_selected()

        def later(self, fn, *args):
            QTimer.singleShot(0, lambda: fn(*args))  # rebuild rows after the clicked widget's signal returns

        def refresh(self, folder=None):
            """Redraw the current folder. Never changes the selection (only Refresh prunes)."""
            entries = workshops.browse(self.state, folder)
            rel = workshops.relative(self.state, self.state["current"])
            self.folder_lbl.setText(f"Current folder: {'/' if rel == '.' else rel}")
            self.up_btn.setEnabled(self.state["current"] != self.state["root"])
            self.browser.clear()
            for e in entries:
                path = str(e["path"])
                supported = e["is_dir"] or e["path"].suffix.lower() in inputs.SELECTABLE
                item = QListWidgetItem()
                item.setData(PATH_ROLE, path)
                item.setData(PATH_ROLE + 1, "dir" if e["is_dir"] else "file")
                row = QWidget()
                hl = QHBoxLayout(row)
                hl.setContentsMargins(4, 0, 4, 0)
                box = QCheckBox()
                box.setChecked(e["selected"])
                box.setAccessibleName(f"Select {e['name']}")
                box.setToolTip("Select or deselect")
                box.clicked.connect(lambda _=False, p=path: self.later(self.toggle, p))
                name = QPushButton(f"[folder] {e['name']}" if e["is_dir"] else e["name"])
                name.setFlat(True)
                name.setStyleSheet("text-align: left;")
                if e["is_dir"]:
                    name.setAccessibleName(f"Open folder {e['name']}")
                    name.clicked.connect(lambda _=False, p=path: self.later(self.open_folder, p))
                else:
                    name.setAccessibleName(f"Select {e['name']}")
                    name.clicked.connect(lambda _=False, p=path: self.later(self.toggle, p))
                if not supported:
                    name.setToolTip("Organize can use this file; Make me can't (PDF, PPTX, DOCX, TXT, MD only).")
                if e["selected"]:
                    row.setStyleSheet(f"background: {SELECTED_BG}; color: {SELECTED_FG};")
                elif not supported:
                    name.setStyleSheet("text-align: left; color: #888888;")
                hl.addWidget(box)
                hl.addWidget(name, 1)
                item.setSizeHint(row.sizeHint())
                self.browser.addItem(item)
                self.browser.setItemWidget(item, row)
            self.render_tags()  # chips belong to the folder now shown
            self.refresh_selected()

        def refresh_selected(self):
            """Selected Inputs from the one workshop selection; Generate eligibility from make_me_status()."""
            selected = workshops.selected_sorted(self.state)
            status = make_me_status(self.state)
            self.selected_list.clear()
            folders = 0
            for p in selected:
                rel = workshops.relative(self.state, p)
                exists = p.exists()
                folders += p.is_dir()
                kind = "[folder] " if p.is_dir() else ("[missing] " if not exists else "")
                item = QListWidgetItem()
                row = QWidget()
                hl = QHBoxLayout(row)
                hl.setContentsMargins(4, 0, 4, 0)
                lbl = QLabel(kind + rel)
                lbl.setToolTip(str(p))
                if p in status["blockers"] and self.mode_stack.currentIndex() == 1:
                    lbl.setStyleSheet("color: #b91c1c;")  # reason is in the eligibility note and tooltip
                    lbl.setToolTip(f"{p}\nMake me can't use this: {status['blockers'][p]}")
                remove = QPushButton("Remove")
                remove.setAccessibleName(f"Remove {rel} from selection")
                remove.setToolTip("Deselect only; the file or folder is not deleted.")
                remove.clicked.connect(lambda _=False, q=str(p): self.later(self.remove_selected, q))
                hl.addWidget(lbl, 1)
                hl.addWidget(remove)
                item.setSizeHint(row.sizeHint())
                self.selected_list.addItem(item)
                self.selected_list.setItemWidget(item, row)
            files = len(selected) - folders
            self.selected_lbl.setText(f"Selected Inputs ({len(selected)}: {files} file{'s' * (files != 1)}, "
                                      f"{folders} folder{'s' * (folders != 1)})")
            self.eligibility_lbl.setText(status["message"] if status["blockers"] else "")
            busy = self.thread is not None or self.org_thread is not None
            self.generate_btn.setEnabled(status["ok"] and not busy)
            for action, b in self.action_btns.items():
                b.setEnabled(not busy)
            self.open_doc_btn.setEnabled(bool(self.last_paths))
            self.open_folder_btn.setEnabled(bool(self.last_paths))

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
                rm.setFixedWidth(22)
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
            if self.tags is None or self.thread is not None or self.org_thread is not None:
                return
            if not path or Path(path).is_dir():
                self.status.setText("Drop a tag on a file; nothing was renamed.")
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

        def refresh_clicked(self):
            gone = workshops.prune(self.state)
            self.load_tags()
            self.refresh()
            if gone:
                self.status.setText("Refresh removed from the selection (no longer on disk): " + ", ".join(
                    workshops.relative(self.state, p) for p in gone))

        def go_up(self):
            if self.state["current"] != self.state["root"]:
                self.refresh(self.state["current"].parent)

        # ---------- organizer: click -> capture -> plan -> (confirm) -> execute off-thread -> reconcile ----------
        def organize(self, action):
            if self.org_thread is not None or self.thread is not None:
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
            try:
                organizing.clipboard_after(result)
            except Exception:
                pass  # clipboard trouble must not hide the file report
            self.refresh()
            self.status.setText(describe_outcomes(result) + tag_note)

        # ---------- generation ----------
        def generate(self):
            if self.thread is not None or self.org_thread is not None or not make_me_status(self.state)["ok"]:
                return  # duplicate click while running, or the selection has entries Make me can't use
            request = build_request(self.state, self.task_box.currentData(), self.current_parameters(),
                                    self.efficient_box.isChecked())
            try:  # Days / Folder name / style checked before any work
                tasks.validate_parameters(request["task_id"], request["parameters"])
            except tasks.TaskError as e:
                self.status.setText(f"Error: {e.message}")
                return
            self.generate_btn.setEnabled(False)
            self.last_paths = []
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
                self.status.setText("Cancelled. Nothing was sent to Gemini or saved.")
            elif result["status"] == "ok":
                self.last_paths = result["paths"]
                self.last_output_root = result["output_root"]
                if len(result["paths"]) == 1:
                    self.status.setText("Saved: " + result["paths"][0])
                else:
                    root = Path(result["output_root"])
                    self.status.setText(f"Saved {len(result['paths'])} PDFs in {root}:\n" + "\n".join(
                        Path(p).relative_to(root).as_posix() for p in result["paths"]))
                if result.get("warnings"):
                    self.status.setText(self.status.text() + "\n" + "\n".join(w["message"] for w in result["warnings"]))
                self.open_document()
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
    app.setApplicationName("Late Night Pal")
    win = Window()
    win.show()
    return app.exec()
