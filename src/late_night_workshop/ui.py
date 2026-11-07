"""M1 desktop UI: pick a PDF, summarize it with Gemini, compile locally, open the result.

`summarize_file()` is the plain (Qt-free) M1 pipeline, temporary until M2's
generation.py replaces it; the window runs it on a worker thread.
"""

from datetime import date
from pathlib import Path

from . import gemini_client, rendering


def summarize_file(pdf_path: str | Path, on_progress=lambda msg: None) -> Path:
    """PDF -> Gemini summary -> local LaTeX PDF next to the source. Returns the new PDF path."""
    pdf_path = Path(pdf_path).resolve()
    on_progress("Checking LaTeX compiler...")
    rendering.check_runtime()  # before the paid call
    out = rendering.unique_path(pdf_path.with_name(f"{pdf_path.stem} summary.pdf"))
    on_progress(f"Sending {pdf_path.name} to Gemini ({gemini_client.model_name()})...")
    doc = gemini_client.summarize_pdf(pdf_path)
    on_progress("Compiling PDF locally...")
    return rendering.render_document(doc, out, subtitle=f"Summary of {pdf_path.name} · {date.today():%Y-%m-%d}")


def run_app() -> int:
    from PySide6.QtCore import QObject, QThread, QUrl, Signal
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import (QApplication, QFileDialog, QLabel, QMainWindow, QPushButton,
                                   QVBoxLayout, QWidget)

    class Worker(QObject):
        progress = Signal(str)
        done = Signal(str)
        failed = Signal(str)

        def __init__(self, path):
            super().__init__()
            self.path = path

        def run(self):
            try:
                self.done.emit(str(summarize_file(self.path, self.progress.emit)))
            except (gemini_client.GeminiError, rendering.RenderError) as e:
                self.failed.emit(e.message + (f"\n{e.details}" if getattr(e, "details", "") else ""))
            except OSError as e:
                self.failed.emit(f"File error: {e.strerror or e}")
            except Exception as e:
                self.failed.emit(f"Unexpected error ({type(e).__name__}).")

    class Window(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Late Night Workshop")
            self.pdf = None
            self.result = None
            self.thread = None
            self.pick_btn = QPushButton("Choose PDF...")
            self.file_lbl = QLabel("No file selected")
            self.go_btn = QPushButton("Generate summary")
            self.status = QLabel("")
            self.status.setWordWrap(True)
            self.open_btn = QPushButton("Open summary PDF")
            self.go_btn.setEnabled(False)
            self.open_btn.setEnabled(False)
            layout = QVBoxLayout()
            for w in (self.pick_btn, self.file_lbl, self.go_btn, self.status, self.open_btn):
                layout.addWidget(w)
            box = QWidget()
            box.setLayout(layout)
            self.setCentralWidget(box)
            self.resize(480, 220)
            self.pick_btn.clicked.connect(self.pick)
            self.go_btn.clicked.connect(self.generate)
            self.open_btn.clicked.connect(self.open_result)

        def pick(self):
            path, _ = QFileDialog.getOpenFileName(self, "Choose a PDF", "", "PDF files (*.pdf)")
            if path:
                self.pdf = path
                self.file_lbl.setText(path)
                self.go_btn.setEnabled(True)

        def generate(self):
            self.go_btn.setEnabled(False)
            self.pick_btn.setEnabled(False)
            self.open_btn.setEnabled(False)
            self.thread = QThread()
            self.worker = Worker(self.pdf)
            self.worker.moveToThread(self.thread)
            self.thread.started.connect(self.worker.run)
            self.worker.progress.connect(self.status.setText)
            self.worker.done.connect(self.succeeded)
            self.worker.failed.connect(self.errored)
            for sig in (self.worker.done, self.worker.failed):
                sig.connect(self.thread.quit)
            self.thread.start()

        def _finish(self):
            self.go_btn.setEnabled(True)
            self.pick_btn.setEnabled(True)

        def succeeded(self, path):
            self._finish()
            self.result = path
            self.status.setText(f"Saved: {path}")
            self.open_btn.setEnabled(True)
            self.open_result()

        def errored(self, message):
            self._finish()
            self.status.setText(f"Error: {message}")

        def open_result(self):
            if self.result:
                QDesktopServices.openUrl(QUrl.fromLocalFile(self.result))

    app = QApplication.instance() or QApplication([])
    win = Window()
    win.show()
    return app.exec()
