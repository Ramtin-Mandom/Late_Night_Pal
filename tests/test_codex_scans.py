"""Scanned PDFs with Codex: page JPEGs -> Luna Markdown -> Terra text (python -m unittest tests.test_codex_scans -v).

Uses the real demo scan; the Codex process is stubbed, so no allowance is used."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


from late_night_workshop import codex_client, inputs  # noqa: E402

SCAN = ROOT / "demo" / "Biology Demo Workshop" / "Labs" / "osmosis-lab-scan.pdf"


class CodexScans(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name, "Workshop")
        self.jobs = Path(self.tmp.name, "job")
        (self.root / "Lec").mkdir(parents=True)
        self.jobs.mkdir()
        self.scan = self.root / "Lec" / "lec18.pdf"
        shutil.copy(SCAN, self.scan)
        self.addCleanup(self.tmp.cleanup)

    def prepare(self, paths):
        return inputs.prepare_inputs(self.root, paths, True, codex_client.CAPABILITIES, payload_dir=self.jobs)

    def test_scan_is_read_by_luna_then_terra_gets_text(self):
        prep = self.prepare([self.scan])
        self.assertEqual(prep["decisions"], [])
        src = prep["sources"][0]
        self.assertEqual([im["page"] for im in src["image_parts"]], [1])
        self.assertEqual(Path(src["image_parts"][0]["path"]).read_bytes()[:2], b"\xff\xd8")  # JPEG

        calls = []
        transcript = "Osmosis: $x^2$ mass drops 14 percent"

        def fake_run(command, input, **kwargs):
            model = command[command.index("-m") + 1]
            calls.append({"command": command, "model": model, "prompt": input.decode("utf-8")})
            answer = ('{"markdown": "%s"}' % transcript
                      if model == codex_client.READER_MODEL else '{"documents": []}')
            Path(command[command.index("-o") + 1]).write_text(answer, encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, b"", b"")

        task = {"prompt": "TASK", "response_schema": {"type": "object", "properties": {}}}
        appdata = Path(self.tmp.name, "appdata")
        with mock.patch.object(codex_client, "find_cli", return_value="codex"), \
                mock.patch.object(codex_client.subprocess, "run", fake_run), \
                mock.patch.dict("os.environ", {"LOCALAPPDATA": str(appdata)}):
            codex_client.generate_content(task, prep["sources"])
            reader, writer = calls
            self.assertEqual(reader["model"], "gpt-6-luna")
            self.assertEqual(reader["command"][reader["command"].index("--image") + 1], src["image_parts"][0]["path"])
            self.assertEqual(reader["command"][-1], "-")
            self.assertIn("page 1 of Lec/lec18.pdf", reader["prompt"])
            self.assertEqual(reader["command"].count("--image"), 1)  # one page per Luna call
            self.assertEqual(writer["model"], "gpt-6.1-terra")
            self.assertNotIn("--image", writer["command"])  # Terra gets text only
            self.assertIn("[Lec/lec18.pdf - page 1]", writer["prompt"])
            self.assertIn("(transcribed from the page image)\n" + transcript, writer["prompt"])

            calls.clear()  # the same lecture again: the saved transcription is reused, Luna is not called
            codex_client.generate_content(task, prep["sources"])
            self.assertEqual([c["model"] for c in calls], ["gpt-6.1-terra"])

    def test_bad_luna_answer_is_asked_again_and_never_cached(self):
        src = self.prepare([self.scan])["sources"]
        answers = ['{"markdown": "  "}', '{"markdown": "Page one text"}']
        models = []

        def fake_run(command, input, **kwargs):
            model = command[command.index("-m") + 1]
            models.append(model)
            answer = answers.pop(0) if model == codex_client.READER_MODEL else '{"documents": []}'
            Path(command[command.index("-o") + 1]).write_text(answer, encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, b"", b"")

        appdata = Path(self.tmp.name, "appdata")
        with mock.patch.object(codex_client.subprocess, "run", fake_run), \
                mock.patch.dict("os.environ", {"LOCALAPPDATA": str(appdata)}):
            done = codex_client.read_scans("codex", src)
            self.assertEqual(models, ["gpt-6-luna", "gpt-6-luna"])  # the empty answer was asked once more
            self.assertIn("Page one text", done[0]["text_parts"][0]["text"])
            self.assertEqual(codex_client._cached(src[0], 1), "Page one text")

            answers[:] = ['not json', 'still not json']  # a fresh page that never gets a usable answer
            other = dict(src[0], fingerprint="sha256:" + "0" * 64)
            with self.assertRaises(codex_client.CodexError):
                codex_client.read_scans("codex", [other])
            self.assertIsNone(codex_client._cached(other, 1))  # nothing wrong is saved for the next Generate

    def test_text_pdf_goes_straight_to_terra(self):
        """Only scanned pages are read by Luna; a PDF with real text makes one Terra call and no images."""
        lecture = self.root / "Lec" / "lecture.pdf"
        shutil.copy(ROOT / "demo" / "Biology Demo Workshop" / "Lectures" / "photosynthesis-lecture.pdf", lecture)
        prep = self.prepare([lecture])
        self.assertEqual(prep["sources"][0]["image_parts"], [])
        models = []

        def fake_run(command, input, **kwargs):
            models.append(command[command.index("-m") + 1])
            self.assertNotIn("--image", command)
            Path(command[command.index("-o") + 1]).write_text('{"documents": []}', encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, b"", b"")

        task = {"prompt": "TASK", "response_schema": {"type": "object", "properties": {}}}
        with mock.patch.object(codex_client, "find_cli", return_value="codex"), \
                mock.patch.object(codex_client.subprocess, "run", fake_run):
            codex_client.generate_content(task, prep["sources"])
        self.assertEqual(models, ["gpt-6.1-terra"])

    def test_handwriting_strokes_are_rendered(self):
        """Tablet notes: no text and no stored image, only vector pen strokes (like Lec/lec18.pdf)."""
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, NameObject
        from PySide6.QtGui import QImage
        writer = PdfWriter()
        page = writer.add_blank_page(612, 792)
        stroke = DecodedStreamObject()
        stroke.set_data(b"q 0.25 0.32 0.71 RG 6 w 100 700 m 500 300 l S Q")
        page[NameObject("/Contents")] = writer._add_object(stroke)
        notes = self.root / "Lec" / "notes.pdf"
        with open(notes, "wb") as f:
            writer.write(f)
        src = self.prepare([notes])["sources"][0]
        self.assertEqual([im["page"] for im in src["image_parts"]], [1])
        img = QImage(src["image_parts"][0]["path"])
        self.assertEqual(max(img.width(), img.height()), 2000)
        self.assertEqual(img.pixelColor(10, 10).name(), "#ffffff")  # paper is white, not black
        scale = 2000 / 792
        mid = img.pixelColor(round(300 * scale), round((792 - 500) * scale))  # PDF point (300, 500), on the stroke
        self.assertLess(mid.red(), 160)


if __name__ == "__main__":
    unittest.main()
