"""Late Night Pal desktop UI: workshop start screen, browser + selection, task panel.

The UI owns clicks, highlights and dialogs; `workshops` owns path/selection truth and
`generation.generate()` (run on a worker thread) owns the job.
"""

import threading
from pathlib import Path

from . import generation, inputs, tasks, workshops

SELECTED_BG = "#2563eb"  # blue highlight for selected files
SELECTED_FG = "#ffffff"
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


def run_app() -> int:
    from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
    from PySide6.QtGui import QBrush, QColor, QDesktopServices
    from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
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

    class Window(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Late Night Pal")
            self.state = None
            self.thread = None
            self.worker = None
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
            self.folder_lbl = QLabel()
            nav.addWidget(self.up_btn)
            nav.addWidget(self.folder_lbl, 1)
            left.addLayout(nav)
            self.browser = QListWidget()
            self.browser.itemClicked.connect(self.browser_clicked)
            left.addWidget(self.browser)
            left.addWidget(QLabel("Click a folder to open it; click a PDF, PPTX, DOCX, TXT or MD file to "
                                  "select or deselect it."))
            body.addLayout(left, 3)

            right = QVBoxLayout()
            self.selected_lbl = QLabel("Selected Inputs (0)")
            right.addWidget(self.selected_lbl)
            self.selected_list = QListWidget()
            right.addWidget(self.selected_list)
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
            self.generate_btn = QPushButton("Generate")
            self.generate_btn.clicked.connect(self.generate)
            right.addWidget(self.generate_btn)
            self.status = QLabel("")
            self.status.setWordWrap(True)
            self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
            right.addWidget(self.status)
            row = QHBoxLayout()
            self.open_doc_btn = QPushButton("Open document")
            self.open_folder_btn = QPushButton("Open output folder")
            self.open_doc_btn.clicked.connect(self.open_document)
            self.open_folder_btn.clicked.connect(self.open_output_folder)
            row.addWidget(self.open_doc_btn)
            row.addWidget(self.open_folder_btn)
            right.addLayout(row)
            body.addLayout(right, 2)
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
            self.refresh()
            self.stack.setCurrentIndex(1)

        def refresh(self, folder=None):
            entries = workshops.browse(self.state, folder)
            rel = workshops.relative(self.state, self.state["current"])
            self.folder_lbl.setText(f"Current folder: {'/' if rel == '.' else rel}")
            self.up_btn.setEnabled(self.state["current"] != self.state["root"])
            self.browser.clear()
            for e in entries:
                is_pdf = not e["is_dir"] and e["path"].suffix.lower() in inputs.SELECTABLE  # selectable file
                item = QListWidgetItem(f"[folder] {e['name']}" if e["is_dir"] else e["name"])
                item.setData(PATH_ROLE, str(e["path"]))
                item.setData(PATH_ROLE + 1, "dir" if e["is_dir"] else ("pdf" if is_pdf else "other"))
                if e["selected"]:
                    item.setBackground(QBrush(QColor(SELECTED_BG)))
                    item.setForeground(QBrush(QColor(SELECTED_FG)))
                elif not e["is_dir"] and not is_pdf:
                    item.setForeground(QBrush(QColor("#888888")))
                    item.setToolTip("Only PDF, PPTX, DOCX, TXT and MD files can be selected.")
                self.browser.addItem(item)
            self.browser.clearSelection()  # selection is shown by the blue background, not Qt's selection
            self.refresh_selected()

        def refresh_selected(self):
            rels = [workshops.relative(self.state, p) for p in workshops.selected_sorted(self.state)]
            self.selected_list.clear()
            self.selected_list.addItems(rels)
            self.selected_lbl.setText(f"Selected Inputs ({len(rels)})")
            self.generate_btn.setEnabled(bool(rels) and self.thread is None)
            self.open_doc_btn.setEnabled(bool(self.last_paths))
            self.open_folder_btn.setEnabled(bool(self.last_paths))

        def browser_clicked(self, item):
            kind, path = item.data(PATH_ROLE + 1), item.data(PATH_ROLE)
            try:
                if kind == "dir":
                    self.refresh(path)
                elif kind == "pdf":
                    workshops.toggle_selection(self.state, path)
                    self.refresh()
            except workshops.WorkshopError as e:
                self.status.setText(f"Error: {e.message}")

        def go_up(self):
            if self.state["current"] != self.state["root"]:
                self.refresh(self.state["current"].parent)

        # ---------- generation ----------
        def generate(self):
            if self.thread is not None or not self.state["selected"]:
                return  # duplicate click while running
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
