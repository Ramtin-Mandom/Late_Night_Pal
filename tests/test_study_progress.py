"""P3-M5 study progress (no Qt; Gemini/LaTeX stubbed, real publish and organizer).
Run: python -m unittest tests.test_study_progress -v"""

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from late_night_workshop import generation, history, organizing, study_progress as sp, ui, workshops  # noqa: E402
from tests.test_history import fake_render  # noqa: E402
from tests.test_pdf_pages import make_pdf, page_text  # noqa: E402
from tests.test_reuse import PLAN  # noqa: E402


class Progress(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.env = mock.patch.dict(os.environ, {"LOCALAPPDATA": str(base / "appdata")})
        self.env.start()
        self.root = base / "Workshop"
        for d in ("Lectures", "Revision", "Archive"):
            (self.root / d).mkdir(parents=True)
        self.pdf = self.root / "Lectures" / "notes.pdf"
        make_pdf(self.pdf, [page_text(n) for n in range(1, 4)])
        self.txt = self.root / "Lectures" / "extra.txt"
        self.txt.write_text("Plain notes.", encoding="utf-8")
        self.calls = []

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def plan(self, root=None):
        root = root or self.root

        def fake(t, sources):
            self.calls.append(t)
            return {"raw_text": PLAN}
        r = generation.generate({"workshop_root": str(root), "destination": str(root / "Revision"),
                                 "selected_paths": [str(self.pdf), str(self.txt)], "task_id": "daily-study-plan",
                                 "parameters": {"days": 2, "folder_name": "Week 5"}},
                                deps={"generate_content": fake, "check_runtime": lambda: None, "render_bundle": fake_render})
        self.assertEqual(r["status"], "ok", r.get("error"))
        self.assertTrue(ui.record_history(str(root), r)["saved"])
        return r

    def plan_view(self, gid):
        v = sp.view(self.root)
        rec = next(r for r in v["plans"] if r["generation_id"] == gid)
        return sp.manifest(rec), v["done"].get(gid, {}), v

    def test_two_day_plan_tracks_six_items_and_persists(self):
        gid = self.plan()["generation_id"]
        m, done, v = self.plan_view(gid)
        self.assertEqual(v["warnings"], [])
        self.assertEqual([d["day"] for d in m["days"]], [1, 2])
        self.assertEqual([[i["label"] for i in d["items"]] for d in m["days"]],
                         [["Notes", "Sample questions", "Checklist"]] * 2)
        self.assertEqual(sp.totals(m, done), {"done": 0, "total": 6, "days": {1: (0, 3), 2: (0, 3)}})  # new: 0/6
        sp.set_done(self.root, gid, "day-01-notes", True)
        sp.set_done(self.root, gid, "day-02-checklist", True)
        _, done, _ = self.plan_view(gid)  # fresh read from disk, as after a restart
        self.assertEqual(sp.totals(m, done), {"done": 2, "total": 6, "days": {1: (1, 3), 2: (1, 3)}})
        sp.set_done(self.root, gid, "day-02-checklist", False)
        self.assertEqual(sp.totals(m, self.plan_view(gid)[1])["done"], 1)

    def test_same_title_plans_and_reuse_have_independent_progress(self):
        first = self.plan()
        sp.set_done(self.root, first["generation_id"], "day-01-notes", True)
        second = self.plan()  # same folder name: published as "Week 5 (2)", a new generation
        v = sp.view(self.root)
        labels = [sp.describe_plan(r) for r in v["plans"]]
        self.assertTrue(labels[0].startswith("Revision/Week 5 (2) · ") and labels[1].startswith("Revision/Week 5 · "),
                        labels)
        self.assertEqual([r["output_root"] for r in v["plans"]], ["Revision/Week 5 (2)", "Revision/Week 5"])
        m2, done2, _ = self.plan_view(second["generation_id"])
        self.assertEqual(sp.totals(m2, done2)["done"], 0)
        self.assertEqual(sp.totals(*self.plan_view(first["generation_id"])[:2])["done"], 1)
        self.assertEqual(len(self.calls), 2)

    def test_records_from_before_progress_load_as_incomplete(self):
        gid = self.plan()["generation_id"]
        self.assertFalse(sp.progress_file(self.root).exists())
        m, done, v = self.plan_view(gid)
        self.assertEqual((sp.totals(m, done)["done"], v["warnings"]), (0, []))

    def test_failed_save_keeps_the_last_saved_value(self):
        gid = self.plan()["generation_id"]
        sp.set_done(self.root, gid, "day-01-notes", True)
        before = sp.progress_file(self.root).read_bytes()
        with mock.patch.object(sp, "_atomic_write", side_effect=PermissionError(13, "Access is denied")):
            with self.assertRaises(sp.ProgressError) as e:
                sp.set_done(self.root, gid, "day-01-notes", False)
        self.assertIn("last saved value", e.exception.message)
        self.assertEqual(sp.progress_file(self.root).read_bytes(), before)
        self.assertTrue(self.plan_view(gid)[1]["day-01-notes"])

    def test_concurrent_saves_never_lose_an_item(self):
        gid = self.plan()["generation_id"]
        docs = [f"day-0{d}-{r}" for d in (1, 2) for r in sp.ROLES]
        threads = [threading.Thread(target=sp.set_done, args=(self.root, gid, doc, True)) for doc in docs * 3]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        m, done, _ = self.plan_view(gid)
        self.assertEqual(sp.totals(m, done)["done"], 6)

    def test_organizer_move_keeps_progress_and_updates_paths(self):
        gid = self.plan()["generation_id"]
        sp.set_done(self.root, gid, "day-02-notes", True)
        state = workshops.open_workshop(self.root)
        out = organizing.execute_plan(organizing.plan_drop(state, "move", [str(self.root / "Revision" / "Week 5")],
                                                          str(self.root / "Archive")))
        self.assertTrue(ui.reconcile_history(str(self.root), out["outcomes"])["ok"])
        m, done, _ = self.plan_view(gid)
        paths = [i["path"] for d in m["days"] for i in d["items"]]
        self.assertTrue(all(p.startswith("Archive/Week 5/Day 0") for p in paths), paths)
        self.assertTrue(all(i["status"] == "available" for d in m["days"] for i in d["items"]))
        self.assertEqual(sp.totals(m, done)["done"], 1)

    def test_missing_pdf_stays_in_totals_with_saved_completion(self):
        r = self.plan()
        gid = r["generation_id"]
        sp.set_done(self.root, gid, "day-01-checklist", True)
        Path(next(p for p in r["paths"] if p.endswith("checklist.pdf"))).unlink()
        m, done, _ = self.plan_view(gid)
        item = next(i for i in m["days"][0]["items"] if i["role"] == "checklist")
        self.assertEqual(item["status"], "missing")
        self.assertEqual(sp.totals(m, done), {"done": 1, "total": 6, "days": {1: (1, 3), 2: (0, 3)}})

    def test_bad_manifest_entries_warn_and_count_once(self):
        rec = {"outputs": [{"document_id": "day-01-notes", "role": "notes", "day": 1, "path": "a.pdf"},
                           {"document_id": "day-01-notes", "role": "notes", "day": 1, "path": "a.pdf"},
                           {"document_id": "x", "role": "summary", "day": None, "path": "b.pdf"}]}
        m = sp.manifest(rec)
        self.assertEqual(m["total"], 1)
        self.assertEqual(len(m["warnings"]), 2)
        self.assertEqual(sp.totals(m, {"day-01-notes": True, "stray": True})["done"], 1)  # strays never count

    def test_corrupt_progress_is_preserved_with_a_warning(self):
        gid = self.plan()["generation_id"]
        f = sp.progress_file(self.root)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("{oops", encoding="utf-8")
        v = sp.view(self.root)
        self.assertIn(str(f), v["warnings"][0])
        self.assertEqual(f.read_text(encoding="utf-8"), "{oops")
        saved = sp.set_done(self.root, gid, "day-01-notes", True)
        self.assertEqual(Path(saved["moved_aside"]).read_text(encoding="utf-8"), "{oops")
        self.assertTrue(self.plan_view(gid)[1]["day-01-notes"])

    def test_progress_and_history_never_overwrite_each_other(self):
        gid = self.plan()["generation_id"]
        hfile, pfile = history.history_file(self.root), sp.progress_file(self.root)
        self.assertNotEqual(hfile, pfile)
        h_before = hfile.read_bytes()
        sp.set_done(self.root, gid, "day-01-notes", True)
        self.assertEqual(hfile.read_bytes(), h_before)  # a progress save leaves History alone
        p_before = pfile.read_bytes()
        state = workshops.open_workshop(self.root)
        out = organizing.execute_plan(organizing.plan_drop(state, "move", [str(self.root / "Revision")],
                                                          str(self.root / "Archive")))
        ui.reconcile_history(str(self.root), out["outcomes"])
        self.assertNotEqual(hfile.read_bytes(), h_before)
        self.assertEqual(pfile.read_bytes(), p_before)  # History reconciliation leaves progress alone
        self.assertEqual(json.loads(hfile.read_text(encoding="utf-8"))["records"][0]["output_root"],
                         "Archive/Revision/Week 5")

    def test_workshops_are_separate(self):
        other = self.root.parent / "Other"
        (other / "Revision").mkdir(parents=True)
        gid = self.plan()["generation_id"]
        sp.set_done(self.root, gid, "day-01-notes", True)
        self.assertNotEqual(sp.progress_file(self.root), sp.progress_file(other))
        self.assertEqual(sp.load(other)["plans"], {})


if __name__ == "__main__":
    unittest.main()
