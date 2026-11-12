"""Scanned PDFs with Codex: pages go as attached JPEGs (python -m unittest tests.test_codex_scans -v).

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

    def test_scan_becomes_attached_page_image(self):
        prep = self.prepare([self.scan])
        self.assertEqual(prep["decisions"], [])
        src = prep["sources"][0]
        self.assertEqual([im["page"] for im in src["image_parts"]], [1])
        self.assertEqual(Path(src["image_parts"][0]["path"]).read_bytes()[:2], b"\xff\xd8")  # JPEG

        seen = {}

        def fake_run(command, input, **kwargs):
            seen.update(command=command, prompt=input.decode("utf-8"))
            Path(command[command.index("-o") + 1]).write_text('{"documents": []}', encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, b"", b"")

        task = {"prompt": "TASK", "response_schema": {"type": "object", "properties": {}}}
        with mock.patch.object(codex_client, "find_cli", return_value="codex"), \
                mock.patch.object(codex_client.subprocess, "run", fake_run):
            codex_client.generate_content(task, prep["sources"])
        command = seen["command"]
        self.assertEqual(command[command.index("--image") + 1], src["image_parts"][0]["path"])
        self.assertEqual(command[-1], "-")
        self.assertIn("image 1 = page 1", seen["prompt"])

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
