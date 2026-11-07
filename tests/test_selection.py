"""P2-M2 shared selection + Make me eligibility (no Qt, no Gemini). Run: python -m unittest tests.test_selection -v"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from late_night_workshop import AppError, generation, organizing, ui, workshops  # noqa: E402


class Selection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name).resolve() / "Workshop"
        for rel in ("Lectures/a.txt", "Labs/b.pdf", "Labs/diagram.png"):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text("Late Night Pal selection fixture\n", encoding="utf-8")
        (root / "Revision").mkdir()
        self.root = root
        self.state = {"root": root, "current": root, "selected": set()}
        self.params = {"days": 3, "folder_name": "Week 5"}

    def tearDown(self):
        self.tmp.cleanup()

    def select(self, rel):
        self.assertTrue(workshops.toggle_selection(self.state, self.root / rel))

    def test_files_and_folders_persist_across_navigation(self):
        workshops.browse(self.state, self.root / "Lectures")
        self.select("Lectures/a.txt")
        workshops.browse(self.state, self.root)
        self.select("Labs")                      # folder selected without navigating into it
        self.assertEqual(self.state["current"], self.root)
        workshops.browse(self.state, self.root / "Revision")
        self.assertEqual([workshops.relative(self.state, p) for p in workshops.selected_sorted(self.state)],
                         ["Labs", "Lectures/a.txt"])
        with self.assertRaises(workshops.WorkshopError):
            workshops.toggle_selection(self.state, self.root)  # the workshop root is not selectable

    def test_remove_offscreen_and_missing_entries(self):
        self.select("Lectures/a.txt")
        self.select("Labs/b.pdf")
        workshops.browse(self.state, self.root / "Revision")
        (self.root / "Labs/b.pdf").unlink()
        self.assertTrue(workshops.deselect(self.state, self.root / "Labs/b.pdf"))  # missing and off-screen
        self.assertEqual(workshops.selected_sorted(self.state), [self.root / "Lectures/a.txt"])
        workshops.browse(self.state)              # an ordinary redraw never prunes
        (self.root / "Lectures/a.txt").unlink()
        self.assertEqual(len(self.state["selected"]), 1)
        self.assertEqual(workshops.prune(self.state), [self.root / "Lectures/a.txt"])  # explicit Refresh does
        self.assertFalse(self.state["selected"])

    def test_make_me_blocks_until_incompatible_entries_removed(self):
        for rel in ("Lectures/a.txt", "Labs", "Labs/diagram.png"):
            self.select(rel)
        params_before = dict(self.params)
        status = ui.make_me_status(self.state)
        self.assertFalse(status["ok"])
        self.assertEqual({workshops.relative(self.state, p) for p in status["blockers"]}, {"Labs", "Labs/diagram.png"})
        self.assertIn("folder", status["message"])
        workshops.deselect(self.state, self.root / "Labs")
        workshops.deselect(self.state, self.root / "Labs/diagram.png")
        self.assertTrue(ui.make_me_status(self.state)["ok"])
        self.assertEqual(workshops.selected_sorted(self.state), [self.root / "Lectures/a.txt"])
        self.assertEqual(self.params, params_before)

    def test_capture_request_keeps_folders_and_is_a_snapshot(self):
        self.select("Labs")
        self.select("Lectures/a.txt")
        workshops.browse(self.state, self.root / "Revision")
        request = organizing.capture_request(self.state, "wrap", {"folder_name": "Batch"})
        workshops.deselect(self.state, self.root / "Labs")
        workshops.browse(self.state, self.root)
        self.assertEqual(request["sources"], [str(self.root / "Labs"), str(self.root / "Lectures/a.txt")])
        self.assertEqual(request["destination"], str(self.root / "Revision"))
        self.assertEqual(organizing.preview(organizing.plan_action(request)),
                         ["Labs -> Revision/Batch/Labs", "Lectures/a.txt -> Revision/Batch/a.txt"])
        self.assertFalse((self.root / "Revision/Batch").exists())

    def test_generate_boundary_still_files_only(self):
        calls = []

        def stop(task, sources, purpose="initial"):
            calls.append([s["source_id"] for s in sources])
            raise AppError("stub_stop", "stub reached")
        deps = {"check_runtime": lambda: None, "generate_content": stop}
        self.select("Labs")
        self.select("Lectures/a.txt")
        bad = generation.generate(ui.build_request(self.state, "summary", {"language_style": "Standard"}), deps=deps)
        self.assertEqual(bad["status"], "error")
        self.assertEqual(bad["error"]["code"], "unreadable_input")  # folder refused at the boundary
        self.assertEqual(calls, [])
        workshops.deselect(self.state, self.root / "Labs")
        ok = generation.generate(ui.build_request(self.state, "summary", {"language_style": "Standard"}), deps=deps)
        self.assertEqual(ok["error"]["code"], "stub_stop")
        self.assertEqual(calls, [["Lectures/a.txt"]])


if __name__ == "__main__":
    unittest.main()
