"""P2-M4 Super Wrap: pure grouping + planning/execution on disposable workshops.
Run: python -m unittest tests.test_super_wrap -v"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from late_night_workshop import organizing as O, super_wrap, workshops  # noqa: E402


def flat(names):
    dests, folders = super_wrap.group(names)
    return ["/".join(d) for d in dests], ["/".join(f) for f in folders]


class Grouping(unittest.TestCase):
    def test_spec_examples(self):
        self.assertEqual(flat(["Cal_1_assignment_1.pdf", "Cal_1_Note_1.pdf", "Cal_1_assignment_2.pdf"]),
                         (["Cal_1/assignment/1.pdf", "Cal_1/Note_1.pdf", "Cal_1/assignment/2.pdf"],
                          ["Cal_1", "Cal_1/assignment"]))
        self.assertEqual(flat(["Cal_1_unit_2_exercise_1.pdf", "Cal_1_unit_2_exercise_2.pdf"])[0],
                         ["Cal_1/unit_2/exercise/1.pdf", "Cal_1/unit_2/exercise/2.pdf"])
        self.assertEqual(flat(["Week_1.md", "Week_2.md", "Cal_2_assignment_1.pdf", "notes.txt", "7.pdf"])[0],
                         ["Week/1.md", "Week/2.md", "Cal_2_assignment_1.pdf", "notes.txt", "7.pdf"])

    def test_exact_spelling_and_leading_zeros(self):
        self.assertEqual(flat(["Lab_01_a.pdf", "Lab_1_b.pdf", "lab_01_c.pdf"])[0],
                         ["Lab_01_a.pdf", "Lab_1_b.pdf", "lab_01_c.pdf"])  # three different keys, all singletons


class SuperWrapPlan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / "Workshop"
        for rel in ("Lectures/Cal_1_assignment_1.pdf", "Labs/Cal_1_Note_1.pdf", "Labs/Cal_1_assignment_2.pdf",
                    "Extras/keep.txt", "Revision/.keep"):
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(rel, encoding="utf-8")
        self.files = [self.root / r for r in ("Lectures/Cal_1_assignment_1.pdf", "Labs/Cal_1_Note_1.pdf",
                                              "Labs/Cal_1_assignment_2.pdf")]
        self.state = {"root": self.root, "current": self.root / "Revision", "selected": set(self.files)}

    def tearDown(self):
        self.tmp.cleanup()

    def tree(self):
        return sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*"))

    def plan(self, name="Coursework"):
        return O.plan_action(O.capture_request(self.state, "super_wrap", {"folder_name": name}))

    def test_execute_and_reconcile(self):
        self.state["selected"].add(self.root / "Extras")
        plan = self.plan()
        self.assertEqual(O.preview(plan), [
            "Labs/Cal_1_assignment_2.pdf -> Revision/Coursework/Cal_1/assignment/2.pdf",
            "Labs/Cal_1_Note_1.pdf -> Revision/Coursework/Cal_1/Note_1.pdf",
            "Lectures/Cal_1_assignment_1.pdf -> Revision/Coursework/Cal_1/assignment/1.pdf",
            "Extras -> Revision/Coursework/Extras"])
        result = O.execute_plan(plan)
        workshops.reconcile(self.state, result["outcomes"])
        self.assertEqual(result["status"], "ok")
        out = self.root / "Revision/Coursework"
        self.assertEqual((out / "Cal_1/assignment/1.pdf").read_text(), "Lectures/Cal_1_assignment_1.pdf")
        self.assertEqual((out / "Cal_1/Note_1.pdf").read_text(), "Labs/Cal_1_Note_1.pdf")
        self.assertEqual((out / "Extras/keep.txt").read_text(), "Extras/keep.txt")  # folder moved intact
        self.assertFalse(any(p.exists() for p in self.files))
        self.assertEqual(self.state["selected"], {out / "Cal_1/assignment/1.pdf", out / "Cal_1/assignment/2.pdf",
                                                  out / "Cal_1/Note_1.pdf", out / "Extras"})

    def test_conflicts_and_invalid_names_change_nothing(self):
        before = self.tree()
        cases = []
        (self.root / "Cal_1").mkdir()                              # selected folder named like a new group
        self.state["selected"].add(self.root / "Cal_1")
        cases.append(("Coursework", "name_conflict"))
        for name, code in cases:
            with self.assertRaises(O.OrganizeError) as cm:
                self.plan(name)
            self.assertEqual(cm.exception.code, code, name)
        self.state["selected"] = {self.root / "Lectures/Cal_1_assignment_1.pdf"}
        (self.root / "Revision/Coursework").mkdir()
        with self.assertRaises(O.OrganizeError) as cm:
            self.plan("coursework")                                 # case-only clash with an existing folder
        self.assertEqual(cm.exception.code, "destination_exists")
        for rel in ("Labs/CON_1.pdf", "Lectures/CON_2.pdf"):        # would create reserved folder CON
            (self.root / rel).write_text("x")
        self.state["selected"] = {self.root / "Labs/CON_1.pdf", self.root / "Lectures/CON_2.pdf"}
        with self.assertRaises(O.OrganizeError) as cm:
            self.plan("Batch")
        self.assertEqual(cm.exception.code, "invalid_name")
        (self.root / "Lectures/Cal_1_Note_1.pdf").write_text("twin")  # same stem in two folders -> same target
        self.state["selected"] = {self.root / "Labs/Cal_1_Note_1.pdf", self.root / "Lectures/Cal_1_Note_1.pdf",
                                  self.root / "Labs/Cal_1_assignment_2.pdf"}
        with self.assertRaises(O.OrganizeError) as cm:
            self.plan("Batch")
        self.assertEqual(cm.exception.code, "name_conflict")
        self.assertFalse((self.root / "Revision/Batch").exists())
        self.assertTrue(set(before) <= set(self.tree()))

    def test_partial_failure_keeps_sources_and_removes_only_empty_new_folders(self):
        real_move = O.DEFAULT_OPS["move"]

        def fail_note(s, d):
            if s.name == "Cal_1_Note_1.pdf":
                raise PermissionError(13, "locked by test")
            real_move(s, d)
        result = O.execute_plan(self.plan(), {"move": fail_note})
        workshops.reconcile(self.state, result["outcomes"])
        self.assertEqual([o["status"] for o in result["outcomes"]], ["completed", "failed", "unattempted"])
        out = self.root / "Revision/Coursework/Cal_1"
        self.assertTrue((out / "assignment/2.pdf").exists())
        self.assertTrue((self.root / "Labs/Cal_1_Note_1.pdf").exists())
        self.assertTrue((self.root / "Lectures/Cal_1_assignment_1.pdf").exists())
        self.assertEqual(sorted(os.listdir(out)), ["assignment"])     # nothing overwritten, no stray empties
        self.assertEqual(self.state["selected"], {out / "assignment/2.pdf", self.root / "Labs/Cal_1_Note_1.pdf",
                                                  self.root / "Lectures/Cal_1_assignment_1.pdf"})


if __name__ == "__main__":
    unittest.main()
