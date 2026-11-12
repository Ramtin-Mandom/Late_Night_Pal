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
sys.path.insert(0, str(ROOT / "tests"))

from late_night_workshop import codex_client, inputs  # noqa: E402
from test_pdf_pages import make_pdf  # noqa: E402

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

    def test_page_without_text_or_image_is_named(self):
        blank = self.root / "Lec" / "blank.pdf"
        make_pdf(blank, [None])
        with self.assertRaises(inputs.InputError) as caught:
            self.prepare([blank])
        self.assertEqual(caught.exception.code, "scan_no_image")
        self.assertIn("Lec/blank.pdf: page 1", caught.exception.message)


if __name__ == "__main__":
    unittest.main()
