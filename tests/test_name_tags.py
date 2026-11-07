"""P2-M5 name tags on disposable workshops (no Qt). Run: python -m unittest tests.test_name_tags -v"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from late_night_workshop import name_tags as T, organizing as O, workshops  # noqa: E402

FAKE_RECYCLE = {"recycle": lambda s, d: shutil.rmtree(s) if s.is_dir() else s.unlink()}  # keep the real bin clean


class NameTags(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self._appdata = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = str(base / "appdata")
        self.root = base / "Workshop"
        self.batch = self.root / "Coursework/Batch"
        self.topics = self.batch / "Topics"
        for i in range(1, 6):
            self.write(f"Coursework/Batch/scan{i}.pdf")
        self.write("Coursework/Batch/Topics/Deep/notes.txt")
        self.state = {"root": self.root, "current": self.batch, "selected": set()}
        self.data = T.load()

    def tearDown(self):
        if self._appdata is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self._appdata
        self.tmp.cleanup()

    def write(self, rel, text="x"):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def drop(self, tag, file, ops=None):
        """What the UI does on a chip drop: reserve -> plan -> execute -> finish -> reconcile."""
        folder = self.state["current"]
        res = T.reserve(self.data, folder, tag, file)
        try:
            plan = O.plan_action(O.capture_request(self.state, "rename", {"new_name": res["new_name"]}, sources=[file]))
        except O.OrganizeError:
            T.finish(self.data, folder, res, succeeded=False)
            raise
        result = O.execute_plan(plan, ops)
        T.finish(self.data, folder, res, succeeded=result["status"] == "ok")
        T.save_reconciled(self.data, result["outcomes"])
        return result

    def run_action(self, action, sources, current, ops=None, **params):
        self.state["selected"], self.state["current"] = set(sources), current
        result = O.execute_plan(O.plan_action(O.capture_request(self.state, action, params)), ops)
        workshops.reconcile(self.state, result["outcomes"])
        T.save_reconciled(self.data, result["outcomes"])
        return result

    def test_chip_rules_and_restart(self):
        for name in ("assignment", "lab", "quiz", "notes", "exam", "draft"):
            T.add_chip(self.data, self.batch, name)
        with self.assertRaises(T.TagError) as cm:
            T.add_chip(self.data, self.batch, "seventh")
        self.assertEqual(cm.exception.code, "too_many_tags")
        T.remove_chip(self.data, self.batch, "draft")
        for bad, code in (("ASSIGNMENT", "duplicate_tag"), ("", "invalid_tag"), ("a/b", "invalid_tag"),
                          ("CON", "invalid_tag"), ("trail ", "invalid_tag")):
            with self.assertRaises(T.TagError) as cm:
                T.add_chip(self.data, self.batch, bad)
            self.assertEqual(cm.exception.code, code, bad)
        T.add_chip(self.data, self.root / "Coursework", "assignment")  # another folder is independent
        self.assertEqual(T.chips(T.load(), self.batch), ["assignment", "lab", "quiz", "notes", "exam"])  # restart
        self.assertEqual(T.chips(T.load(), self.root / "Coursework"), ["assignment"])

    def test_five_drops_restart_recreate_continues_from_six(self):
        T.add_chip(self.data, self.batch, "assignment")
        for i in range(1, 6):
            self.drop("assignment", self.batch / f"scan{i}.pdf")
        self.assertEqual(sorted(p.name for p in self.batch.glob("assignment_*")),
                         [f"assignment_{i}.pdf" for i in range(1, 6)])
        self.assertEqual((self.batch / "assignment_3.pdf").exists(), True)
        self.data = T.load()                                   # restart
        T.remove_chip(self.data, self.batch, "assignment")
        T.add_chip(self.data, self.batch, "assignment")
        self.write("Coursework/Batch/extra.docx")
        self.drop("assignment", self.batch / "extra.docx")
        self.assertTrue((self.batch / "assignment_6.docx").exists())

    def test_occupied_numbers_skipped_and_failures_do_not_advance(self):
        T.add_chip(self.data, self.batch, "assignment")
        self.write("Coursework/Batch/Assignment_1.txt")       # occupies 1 (any case, any extension)
        self.drop("assignment", self.batch / "scan1.pdf")
        self.assertTrue((self.batch / "assignment_2.pdf").exists())
        with self.assertRaises(T.TagError):
            T.reserve(self.data, self.batch, "assignment", self.topics)  # folder: refused before reserving
        boom = {"move": lambda s, d: (_ for _ in ()).throw(PermissionError(13, "locked"))}
        r = self.drop("assignment", self.batch / "scan2.pdf", ops=boom)
        self.assertEqual(r["status"], "failed")
        self.assertTrue((self.batch / "scan2.pdf").exists())
        self.drop("assignment", self.batch / "scan3.pdf")
        self.assertTrue((self.batch / "assignment_3.pdf").exists())  # 3 reused: the failure released it
        with self.assertRaises(O.OrganizeError) as cm:                # never overwrite on rename
            O.plan_action(O.capture_request(self.state, "rename", {"new_name": "Scan4.pdf"},
                                            sources=[self.batch / "scan5.pdf"]))
        self.assertEqual(cm.exception.code, "destination_exists")
        self.assertEqual((self.batch / "scan4.pdf").read_text(), "x")
        self.assertEqual(T.load()["folders"][T.key(self.batch)]["counters"]["assignment"], 4)

    def test_delete_tree_clears_state_and_recreated_folder_starts_at_one(self):
        T.add_chip(self.data, self.batch, "assignment")
        for i in (1, 2):
            self.drop("assignment", self.batch / f"scan{i}.pdf")
        T.add_chip(self.data, self.topics, "lecture")
        self.run_action("delete", [self.batch], self.root / "Coursework", ops=FAKE_RECYCLE)
        self.assertEqual(T.load()["folders"], {})               # Batch and its descendant Topics cleared
        self.batch.mkdir()
        self.write("Coursework/Batch/new.pdf")
        self.state["current"] = self.batch
        T.add_chip(self.data, self.batch, "assignment")
        self.drop("assignment", self.batch / "new.pdf")
        self.assertTrue((self.batch / "assignment_1.pdf").exists())

    def test_rip_keeps_child_state_and_clears_wrapper_only_when_removed(self):
        T.add_chip(self.data, self.batch, "assignment")
        T.add_chip(self.data, self.topics, "lecture")
        T.add_chip(self.data, self.topics / "Deep", "proof")
        boom_rmdir = {"rmdir": lambda s, d: (_ for _ in ()).throw(PermissionError(13, "locked"))}
        r = self.run_action("rip", [self.batch], self.root, ops=boom_rmdir)  # children move, wrapper removal fails
        self.assertEqual(r["status"], "partial")
        data = T.load()
        self.assertEqual(T.chips(data, self.root / "Coursework/Topics"), ["lecture"])
        self.assertEqual(T.chips(data, self.root / "Coursework/Topics/Deep"), ["proof"])  # descendant followed
        self.assertEqual(T.chips(data, self.batch), ["assignment"])  # wrapper survived, keeps its state
        r = self.run_action("rip", [self.batch], self.root)          # now empty: removed
        self.assertEqual(r["status"], "ok")
        self.assertNotIn(T.key(self.batch), T.load()["folders"])

    def test_super_wrap_moves_tagged_folder_and_descendants_partial_keeps_rest(self):
        T.add_chip(self.data, self.topics, "lecture")
        T.add_chip(self.data, self.topics / "Deep", "proof")
        T.add_chip(self.data, self.batch, "assignment")
        real_move = O.DEFAULT_OPS["move"]
        ops = {"move": lambda s, d: (_ for _ in ()).throw(PermissionError(13, "locked")) if s.name == "scan1.pdf"
               else real_move(s, d)}
        (self.root / "Revision").mkdir()
        r = self.run_action("super_wrap", [self.topics, self.batch / "scan1.pdf"], self.root / "Revision",
                            ops=ops, folder_name="Pack")
        self.assertEqual([o["status"] for o in r["outcomes"]], ["failed", "unattempted"])
        self.assertEqual(T.chips(T.load(), self.topics), ["lecture"])  # nothing confirmed, nothing moved
        r = self.run_action("super_wrap", [self.topics], self.root / "Revision", folder_name="Pack")
        self.assertEqual(r["status"], "ok")
        data = T.load()
        self.assertEqual(T.chips(data, self.root / "Revision/Pack/Topics"), ["lecture"])
        self.assertEqual(T.chips(data, self.root / "Revision/Pack/Topics/Deep"), ["proof"])
        self.assertEqual(T.chips(data, self.batch), ["assignment"])
        self.assertNotIn(T.key(self.topics), data["folders"])
        r = self.run_action("paste", [], self.root / "Revision", clipboard={  # copies never clone tags
            "paths": [str(self.root / "Revision/Pack/Topics")], "effect": "copy"})
        self.assertEqual(T.chips(T.load(), self.root / "Revision/Topics"), [])


if __name__ == "__main__":
    unittest.main()
