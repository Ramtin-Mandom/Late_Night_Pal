"""Drag-and-drop file management on disposable workshops: browser drags move, Recent downloads drags copy,
both through organizing.plan_drop -> execute_plan -> workshops.reconcile. No Qt needed.
Run: python -m unittest tests.test_drag_drop -v"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from late_night_workshop import organizing, ui, workshops  # noqa: E402

O = organizing


class DragDrop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self._appdata = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = str(base / "appdata")
        self.root = base / "Workshop"
        for rel in ("a.pdf", "b.pdf", "c.txt", "Lectures/old.pdf", "Labs/inner/x.md"):
            self.write(self.root / rel, rel)
        self.dl = base / "Downloads"
        for name in ("hw1.pdf", "hw2.pdf"):
            self.write(self.dl / name, name)
        self.state = {"root": self.root, "current": self.root, "selected": set()}

    def tearDown(self):
        if self._appdata is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self._appdata
        self.tmp.cleanup()

    def write(self, p, text):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def drop(self, effect, sources, dest):
        """What the UI does after a drop: plan, execute, reconcile, browse again."""
        result = O.execute_plan(O.plan_drop(self.state, effect, [str(s) for s in sources], str(dest)))
        workshops.reconcile(self.state, result["outcomes"])
        return result

    def snapshot(self):
        return sorted(p.relative_to(self.root.parent).as_posix() for p in self.root.parent.rglob("*")
                      if "appdata" not in p.parts)

    def test_single_move(self):
        r = self.drop("move", [self.root / "a.pdf"], self.root / "Lectures")
        self.assertEqual(r["status"], "ok")
        self.assertTrue((self.root / "Lectures/a.pdf").is_file())
        self.assertFalse((self.root / "a.pdf").exists())
        self.assertEqual(ui.describe_drop(r, "move"), "Moved 1 file to Lectures.")

    def test_multi_move_drags_whole_selection_and_reconciles(self):
        for n in ("a.pdf", "b.pdf", "c.txt"):
            workshops.toggle_selection(self.state, self.root / n)
        sources = O.drop_sources(workshops.selected_sorted(self.state), self.root / "b.pdf")
        self.assertEqual(len(sources), 3)
        r = self.drop("move", sources + [str(self.root / "a.pdf")], self.root / "Lectures")  # duplicate deduped
        self.assertEqual(len(r["outcomes"]), 3)
        self.assertEqual(ui.describe_drop(r, "move"), "Moved 3 files to Lectures.")
        self.assertEqual(self.state["selected"], {(self.root / "Lectures" / n).resolve() for n in ("a.pdf", "b.pdf", "c.txt")})
        # refresh after the operation: both folders list the new truth
        names = [e["name"] for e in workshops.browse(self.state, self.root / "Lectures")]
        self.assertEqual(names, ["a.pdf", "b.pdf", "c.txt", "old.pdf"])
        self.assertEqual([e["name"] for e in workshops.browse(self.state, self.root)], ["Labs", "Lectures"])

    def test_unselected_row_drags_only_itself(self):
        workshops.toggle_selection(self.state, self.root / "a.pdf")
        self.assertEqual(O.drop_sources(workshops.selected_sorted(self.state), self.root / "c.txt"),
                         [str(self.root / "c.txt")])

    def test_move_up_to_parent_and_collision_suffix(self):
        self.write(self.root / "Lectures/a.pdf", "other")
        r = self.drop("move", [self.root / "Lectures/a.pdf"], self.root)  # Up = the parent folder
        self.assertEqual(Path(r["outcomes"][0]["destination"]).name, "a (2).pdf")
        self.assertEqual((self.root / "a.pdf").read_text(encoding="utf-8"), "a.pdf")  # never overwritten
        self.assertIn("1 renamed", ui.describe_drop(r, "move"))

    def test_download_copy_single_and_multi(self):
        r = self.drop("copy", [self.dl / "hw1.pdf"], self.root / "Labs")
        self.assertEqual(ui.describe_drop(r, "copy"), "Copied 1 download to Labs.")
        r = self.drop("copy", [self.dl / "hw1.pdf", self.dl / "hw2.pdf"], self.root / "Labs")
        self.assertEqual(ui.describe_drop(r, "copy"), "Copied 2 downloads to Labs (1 renamed to avoid a name clash).")
        self.assertEqual(sorted(p.name for p in (self.root / "Labs").iterdir()),
                         ["hw1 (2).pdf", "hw1.pdf", "hw2.pdf", "inner"])
        self.assertTrue((self.dl / "hw1.pdf").is_file() and (self.dl / "hw2.pdf").is_file())  # originals kept

    def test_invalid_destinations_change_nothing(self):
        before = self.snapshot()
        cases = [("move", [self.root / "a.pdf"], self.root),                         # its own folder
                 ("move", [self.root / "Labs"], self.root / "Labs/inner"),           # into a descendant
                 ("move", [self.root / "Labs"], self.root / "Labs"),                 # into itself
                 ("move", [self.root / "a.pdf"], self.root / "c.txt"),               # not a folder
                 ("move", [self.root / "a.pdf"], self.root.parent / "Downloads"),    # outside the workshop
                 ("copy", [self.dl / "hw1.pdf"], self.dl)]                           # outside / own folder
        for effect, src, dest in cases:
            with self.subTest(dest=dest.name), self.assertRaises(O.OrganizeError):
                O.plan_drop(self.state, effect, [str(s) for s in src], str(dest))
        self.assertEqual(self.snapshot(), before)

    def test_mixed_valid_and_invalid_is_all_or_nothing(self):
        before = self.snapshot()
        with self.assertRaises(O.OrganizeError):  # Lectures/old.pdf is already in Lectures
            O.plan_drop(self.state, "move", [str(self.root / "a.pdf"), str(self.root / "Lectures/old.pdf")],
                        str(self.root / "Lectures"))
        self.assertEqual(self.snapshot(), before)

    def test_link_destination_rejected(self):
        link = self.root / "Linked"
        try:
            import _winapi
            _winapi.CreateJunction(str(self.root / "Labs"), str(link))  # no admin needed, unlike a symlink
        except (ImportError, OSError):
            self.skipTest("junctions are Windows-only")
        with self.assertRaises(O.OrganizeError):
            O.plan_drop(self.state, "move", [str(self.root / "a.pdf")], str(link))

    def test_missing_source(self):
        with self.assertRaises(O.OrganizeError) as cm:
            O.plan_drop(self.state, "copy", [str(self.dl / "gone.pdf")], str(self.root))
        self.assertEqual(cm.exception.code, "missing_source")
        plan = O.plan_drop(self.state, "move", [str(self.root / "a.pdf")], str(self.root / "Labs"))
        (self.root / "a.pdf").unlink()  # vanished between drop and execution
        r = O.execute_plan(plan)
        self.assertEqual((r["status"], r["outcomes"][0]["error"]["code"]), ("failed", "missing_source"))
        self.assertIn("FAILED", ui.describe_drop(r, "move"))

    def test_cancelled_drag_changes_nothing(self):
        before, selected = self.snapshot(), set(self.state["selected"])
        O.drop_sources([], self.root / "a.pdf")  # a drag started; no drop target recorded -> no plan runs
        self.assertEqual((self.snapshot(), self.state["selected"]), (before, selected))

    def test_click_selection_still_works(self):
        rows = [str(e["path"]) for e in workshops.browse(self.state)]  # Labs, Lectures, a.pdf, b.pdf, c.txt
        self.assertTrue(workshops.toggle_selection(self.state, rows[2]))  # plain/Ctrl click
        added = workshops.select_range(self.state, rows, rows[2], rows[4])  # Shift+click
        self.assertEqual([p.name for p in added], ["b.pdf", "c.txt"])
        self.assertFalse(workshops.toggle_selection(self.state, rows[3]))  # toggle off one in the range
        self.assertEqual(sorted(p.name for p in self.state["selected"]), ["a.pdf", "c.txt"])
        workshops.browse(self.state, rows[1])  # opening a folder keeps the selection
        self.assertEqual(len(self.state["selected"]), 2)

    def test_numbers_sort_like_explorer_and_shift_range_follows_them(self):
        lectures = self.root / "Lectures"
        for n in (1, 2, 3, 10, 18, 19, 20, 21, 22, 30):
            self.write(lectures / f"lecture {n}.pdf", str(n))
        names = [e["name"] for e in workshops.browse(self.state, lectures)]
        self.assertEqual(names, ["lecture 1.pdf", "lecture 2.pdf", "lecture 3.pdf", "lecture 10.pdf", "lecture 18.pdf",
                                 "lecture 19.pdf", "lecture 20.pdf", "lecture 21.pdf", "lecture 22.pdf",
                                 "lecture 30.pdf", "old.pdf"])
        rows = [str(e["path"]) for e in workshops.browse(self.state)]
        workshops.toggle_selection(self.state, rows[4])  # click lecture 18
        workshops.select_range(self.state, rows, rows[4], rows[8])  # Shift+click lecture 22
        self.assertEqual([p.name for p in workshops.selected_sorted(self.state)],
                         [f"lecture {n}.pdf" for n in (18, 19, 20, 21, 22)])

    def test_drag_label(self):
        self.assertEqual(ui.drag_label("move", [str(self.root / "a.pdf")]), "Move: a.pdf")
        self.assertEqual(ui.drag_label("copy", ["x", "y"]), "Copy 2 downloads")


if __name__ == "__main__":
    unittest.main()
