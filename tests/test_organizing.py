"""P2-M1 Wrap planning fixture (no mutation). Run: python -m unittest tests.test_organizing -v
M3 can reuse make_workshop() for executor checks."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from late_night_workshop import organizing  # noqa: E402


def make_workshop(base: Path) -> dict:
    root = (base / "Workshop").resolve()
    for rel in ("Lectures/a.pdf", "Labs/b.pdf"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(b"%PDF-1.4 test\n")
    (root / "Revision").mkdir()
    return {"root": root, "current": root / "Revision", "selected": {root / "Lectures/a.pdf", root / "Labs/b.pdf"}}


class WrapPlan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = make_workshop(Path(self.tmp.name))
        self.root = self.state["root"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_preview_maps_sources_without_mutation(self):
        request = organizing.capture_request(self.state, "wrap", {"folder_name": "Batch"})
        self.state["current"] = self.root  # navigating after the click must not redirect the job
        plan = organizing.plan_action(request)
        print("\n" + "\n".join(organizing.preview(plan)))
        self.assertEqual(organizing.preview(plan), ["Labs/b.pdf -> Revision/Batch/b.pdf",
                                                    "Lectures/a.pdf -> Revision/Batch/a.pdf"])
        self.assertTrue((self.root / "Lectures/a.pdf").is_file() and (self.root / "Labs/b.pdf").is_file())
        self.assertFalse((self.root / "Revision/Batch").exists())

    def test_existing_destination_rejected_before_mutation(self):
        (self.root / "Revision/batch").mkdir()  # case-insensitive clash
        request = organizing.capture_request(self.state, "wrap", {"folder_name": "Batch"})
        with self.assertRaises(organizing.OrganizeError) as cm:
            organizing.plan_action(request)
        print(f"\n{cm.exception.code}: {cm.exception.message}")
        self.assertEqual(cm.exception.code, "destination_exists")
        self.assertTrue((self.root / "Lectures/a.pdf").is_file() and (self.root / "Labs/b.pdf").is_file())
        self.assertEqual([p.name for p in (self.root / "Revision").iterdir()], ["batch"])

    def test_raw_name_checked_before_helper_trims(self):
        for raw, code in ((None, "cancelled"), ("   ", "invalid_name"), ("Batch ", "invalid_name"), ("CON", "invalid_name")):
            request = organizing.capture_request(self.state, "wrap", {"folder_name": raw})
            with self.assertRaises(organizing.OrganizeError) as cm:
                organizing.plan_action(request)
            self.assertEqual(cm.exception.code, code, raw)


if __name__ == "__main__":
    unittest.main()
