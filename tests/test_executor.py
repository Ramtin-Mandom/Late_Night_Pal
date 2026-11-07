"""P2-M3 executor on disposable workshops (one real Recycle Bin call on a temp file).
Run: python -m unittest tests.test_executor -v"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from late_night_workshop import organizing, workshops  # noqa: E402

O = organizing


class Executor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self._appdata = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = str(base / "appdata")  # cut records go here, not the real app data
        self.root = base / "Workshop"
        for rel in ("Lectures/a.pdf", "Labs/b.pdf"):
            self.write(rel, rel)
        (self.root / "Coursework").mkdir()
        self.outside = base / "Elsewhere"
        self.state = {"root": self.root, "current": self.root, "selected": set()}

    def tearDown(self):
        if self._appdata is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self._appdata
        self.tmp.cleanup()

    def write(self, rel, text, base=None):
        p = (base or self.root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def request(self, action, sources, current, **params):
        self.state["selected"] = {Path(s) for s in sources}
        self.state["current"] = current
        return O.capture_request(self.state, action, params)

    def run_action(self, action, sources, current, ops=None, **params):
        result = O.execute_plan(O.plan_action(self.request(action, sources, current, **params)), ops)
        workshops.reconcile(self.state, result["outcomes"])
        return result

    def test_wrap_then_rip_coursework_batch(self):
        r = self.run_action("wrap", [self.root / "Lectures/a.pdf", self.root / "Labs/b.pdf"],
                            self.root / "Coursework", folder_name="Batch")
        self.assertEqual(r["status"], "ok")
        self.assertEqual((self.root / "Coursework/Batch/a.pdf").read_text(), "Lectures/a.pdf")
        self.assertFalse((self.root / "Lectures/a.pdf").exists())
        self.assertEqual(self.state["selected"], {self.root / "Coursework/Batch/a.pdf", self.root / "Coursework/Batch/b.pdf"})
        r = self.run_action("rip", [self.root / "Coursework/Batch"], self.root)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(sorted(p.name for p in (self.root / "Coursework").iterdir()), ["a.pdf", "b.pdf"])
        self.assertFalse((self.root / "Lectures/a.pdf").exists())  # no original-location restoration
        self.assertEqual(self.state["selected"], set())           # the removed wrapper is deselected

    def test_rip_collision_and_files_only_refused_before_mutation(self):
        self.write("Coursework/Batch/a.pdf", "inner")
        self.write("Coursework/a.pdf", "outer")
        with self.assertRaises(O.OrganizeError) as cm:
            O.plan_action(self.request("rip", [self.root / "Coursework/Batch"], self.root))
        self.assertEqual(cm.exception.code, "destination_exists")
        self.assertEqual((self.root / "Coursework/a.pdf").read_text(), "outer")
        self.assertTrue((self.root / "Coursework/Batch/a.pdf").exists())
        with self.assertRaises(O.OrganizeError) as cm:
            O.plan_action(self.request("rip", [self.root / "Coursework/a.pdf"], self.root))
        self.assertEqual(cm.exception.code, "no_folders")

    def test_wrap_destination_appearing_after_plan_is_not_overwritten(self):
        plan = O.plan_action(self.request("wrap", [self.root / "Lectures/a.pdf"], self.root / "Coursework",
                                          folder_name="Batch"))
        self.write("Coursework/Batch/keep.txt", "someone else's")
        r = O.execute_plan(plan)
        self.assertEqual([o["status"] for o in r["outcomes"]], ["failed"])
        self.assertTrue((self.root / "Lectures/a.pdf").exists())
        self.assertEqual(os.listdir(self.root / "Coursework/Batch"), ["keep.txt"])

    def test_paste_copy_suffix_and_into_itself(self):
        a = self.root / "Lectures/a.pdf"
        r = self.run_action("paste", [], self.root / "Lectures", clipboard={"paths": [str(a)], "effect": "copy"})
        self.assertEqual(r["outcomes"][0]["destination"], str(self.root / "Lectures/a (2).pdf"))
        self.assertTrue(a.exists() and (self.root / "Lectures/a (2).pdf").read_text() == "Lectures/a.pdf")
        ext = self.write("Pack/notes.txt", "external", base=self.outside).parent
        for src, cur in ((self.root / "Lectures", self.root / "Lectures"), (ext, ext)):
            with self.assertRaises(O.OrganizeError) as cm:
                O.plan_action({"action": "paste", "workshop_root": str(self.root), "destination": str(cur),
                               "sources": [], "parameters": {"clipboard": {"paths": [str(src)], "effect": "copy"}}})
            self.assertIn(cm.exception.code, ("into_itself", "outside_workshop"))
        (self.root / "Lectures/Sub").mkdir()
        with self.assertRaises(O.OrganizeError) as cm:  # folder into its own descendant
            O.plan_action(self.request("paste", [], self.root / "Lectures/Sub",
                                       clipboard={"paths": [str(self.root / "Lectures")], "effect": "copy"}))
        self.assertEqual(cm.exception.code, "into_itself")

    def test_three_item_external_cut_partial_then_safe_retry(self):
        srcs = [self.write(f"cut/{n}.txt", n, base=self.outside) for n in ("one", "two", "three")]
        clip = {"paths": [str(p) for p in srcs], "effect": "cut"}
        real_move = O.DEFAULT_OPS["move"]

        def fail_two(s, d):
            if s.name == "two.txt":
                raise PermissionError(13, "locked by test")
            real_move(s, d)
        r = self.run_action("paste", [], self.root / "Coursework", ops={"move": fail_two}, clipboard=clip)
        self.assertEqual([o["status"] for o in r["outcomes"]], ["completed", "failed", "unattempted"])
        self.assertEqual(r["status"], "partial")
        self.assertFalse(srcs[0].exists())
        self.assertTrue(srcs[1].exists() and srcs[2].exists())     # remaining sources preserved
        rec = O.load_cut_record(r["batch_id"])
        self.assertEqual([i["status"] for i in rec["items"]], ["completed", "failed", "unattempted"])
        srcs[0].write_text("a new file at item 1's old path")   # retry must not touch it
        r2 = self.run_action("paste", [], self.root / "Coursework", clipboard=clip)
        self.assertEqual(r2["status"], "ok")
        self.assertEqual(r2["skipped"], [str(srcs[0])])
        self.assertEqual([Path(o["source"]).name for o in r2["outcomes"]], ["two.txt", "three.txt"])
        self.assertEqual(srcs[0].read_text(), "a new file at item 1's old path")
        self.assertEqual(sorted(os.listdir(self.root / "Coursework")), ["one.txt", "three.txt", "two.txt"])
        with self.assertRaises(O.OrganizeError) as cm:
            O.plan_action(self.request("paste", [], self.root / "Coursework", clipboard=clip))
        self.assertEqual(cm.exception.code, "cut_done")

    def test_retry_refuses_when_reserved_destination_now_exists(self):
        srcs = [self.write(f"cut/{n}.txt", n, base=self.outside) for n in ("one", "two")]
        clip = {"paths": [str(p) for p in srcs], "effect": "cut"}
        boom = lambda s, d: (_ for _ in ()).throw(PermissionError(13, "locked"))
        self.run_action("paste", [], self.root / "Coursework", ops={"move": boom}, clipboard=clip)
        self.write("Coursework/one.txt", "someone else's")
        with self.assertRaises(O.OrganizeError) as cm:
            O.plan_action(self.request("paste", [], self.root / "Coursework", clipboard=clip))
        self.assertEqual(cm.exception.code, "cut_changed")
        self.assertTrue(srcs[0].exists() and srcs[1].exists())  # never deleted because a destination exists

    def test_unsafe_cut_rejected_before_mutation(self):
        with self.assertRaises(O.OrganizeError) as cm:
            O.plan_action(self.request("paste", [], self.root / "Coursework",
                                       clipboard={"paths": [r"\\server\share\notes.pdf"], "effect": "cut"}))
        self.assertEqual(cm.exception.code, "unsafe_cut")
        self.assertEqual(os.listdir(self.root / "Coursework"), [])

    def test_copied_source_kept_is_failed_and_selection_kept(self):
        a = self.root / "Lectures/a.pdf"

        def copy_then_fail(s, d):
            O._copy(s, d)
            raise O._SourceKept("source locked")
        r = self.run_action("wrap", [a, self.root / "Labs/b.pdf"], self.root / "Coursework",
                            ops={"move": copy_then_fail}, folder_name="Batch")
        self.assertEqual([(o["status"], o["change"]) for o in r["outcomes"]],
                         [("failed", "copied_source_kept"), ("unattempted", None)])
        b = self.root / "Labs/b.pdf"  # plan order is workshop-relative: Labs/b.pdf first
        self.assertTrue(b.exists() and (self.root / "Coursework/Batch/b.pdf").exists())
        self.assertFalse((self.root / "Coursework/Batch/a.pdf").exists())
        self.assertEqual(self.state["selected"], {a, self.root / "Labs/b.pdf"})

    def test_delete_uses_recycle_bin(self):
        if not O.recycle_available(self.root):
            self.skipTest("no Recycle Bin on this drive")
        f = self.write("lnp-test-recycle.txt", "disposable")
        r = self.run_action("delete", [f], self.root)
        self.assertEqual([(o["status"], o["change"]) for o in r["outcomes"]], [("completed", "deleted")])
        self.assertFalse(f.exists())
        self.assertEqual(self.state["selected"], set())


if __name__ == "__main__":
    unittest.main()
