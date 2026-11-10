"""P3-M4 Reuse settings and History path reconciliation (no Qt; Gemini/LaTeX stubbed, real publish and
real organizer moves). Run: python -m unittest tests.test_reuse -v"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from late_night_workshop import generation, history, organizing, ui, workshops  # noqa: E402
from tests.test_history import BUNDLE, fake_render  # noqa: E402
from tests.test_pdf_pages import make_pdf, page_text  # noqa: E402

PLAN = json.dumps({"documents": [{"role": r, "day": d, "title": f"Day {d} {r}", "latex_code": rf"\section*{{Day {d}}}"}
                                 for d in (1, 2) for r in ("notes", "sample-questions", "checklist")],
                   "allocation": [{"day": 1, "topics": ["a"], "workload_minutes": 30, "source_ids": ["Lectures/notes.pdf"]},
                                  {"day": 2, "topics": ["b"], "workload_minutes": 30, "source_ids": ["Lectures/extra.txt"]}]})


class Reuse(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.env = mock.patch.dict(os.environ, {"LOCALAPPDATA": str(base / "appdata")})
        self.env.start()
        self.root = base / "Workshop"
        for d in ("Lectures", "Revision", "Archive"):
            (self.root / d).mkdir(parents=True)
        self.pdf = self.root / "Lectures" / "notes.pdf"
        make_pdf(self.pdf, [page_text(n) for n in range(1, 6)])
        self.txt = self.root / "Lectures" / "extra.txt"
        self.txt.write_text("Plain notes.", encoding="utf-8")
        self.calls = []

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def generate(self, task="summary", params=None, reply=BUNDLE, efficient=True):
        def fake(t, sources):
            self.calls.append(t)
            return {"raw_text": reply}
        result = generation.generate({
            "workshop_root": str(self.root), "destination": str(self.root / "Revision"),
            "selected_paths": [str(self.pdf), str(self.txt)], "task_id": task,
            "parameters": params or {"language_style": "Simple"}, "efficient": efficient,
            "page_selections": {str(self.pdf): [1, 3, 4]}},
            deps={"generate_content": fake, "check_runtime": lambda: None, "render_bundle": fake_render})
        self.assertEqual(result["status"], "ok", result.get("error"))
        self.assertTrue(ui.record_history(str(self.root), result)["saved"])
        return result

    def stored(self, gid):
        return next(r for r in history.load(self.root)["records"] if r["generation_id"] == gid)

    def move(self, sources, folder):
        state = workshops.open_workshop(self.root)
        plan = organizing.plan_drop(state, "move", [str(p) for p in sources], str(folder))
        result = organizing.execute_plan(plan)
        self.assertEqual(result["status"], "ok", result)
        return result["outcomes"]

    # ---------- Reuse settings ----------
    def test_reuse_restores_everything_without_calling_gemini(self):
        gid = self.generate()["generation_id"]
        n = len(self.calls)
        check = history.check_reuse(self.root, self.stored(gid))
        self.assertEqual([e["status"] for e in check["inputs"]], ["ok", "ok"])
        self.assertIsNone(check["destination"]["problem"])
        state = workshops.open_workshop(self.root)  # navigated elsewhere, nothing selected
        workshops.browse(state, self.root / "Archive")
        ui.apply_reuse(state, check)
        self.assertEqual(state["selected"], {self.pdf, self.txt})
        self.assertEqual(state["pages"], {self.pdf: "1, 3-4"})
        self.assertEqual(state["current"], self.root / "Revision")
        self.assertTrue(ui.make_me_status(state, ui.count_pages([self.pdf]), check)["ok"])
        request = ui.build_request(state, check["task_id"], check["parameters"], check["efficient"])
        self.assertEqual((request["destination"], request["page_selections"], request["efficient"],
                          request["parameters"]["language_style"]),
                         (str(self.root / "Revision"), {str(self.pdf): [1, 3, 4]}, True, "Simple"))
        self.assertEqual(len(self.calls), n)  # reuse never calls Gemini

    def test_problems_block_until_corrected_and_record_stays_intact(self):
        gid = self.generate()["generation_id"]
        before = self.stored(gid)
        make_pdf(self.pdf, [page_text(1), page_text(2)])  # changed, and page 3-4 no longer exist
        self.txt.unlink()  # missing
        (self.root / "Revision").rename(self.root / "Old")  # destination gone
        check = history.check_reuse(self.root, before)
        by = {e["rel"]: e for e in check["inputs"]}
        self.assertEqual(by["Lectures/notes.pdf"]["status"], "changed")
        self.assertEqual(by["Lectures/notes.pdf"]["page_problem"],
                         "Lectures/notes.pdf has 2 pages; page 4 is out of range.")
        self.assertEqual(by["Lectures/extra.txt"]["status"], "missing")
        self.assertIn("Revision is unavailable", check["destination"]["problem"])
        state = workshops.open_workshop(self.root)
        workshops.browse(state, self.root / "Archive")
        ui.apply_reuse(state, check)
        self.assertEqual(state["current"], self.root / "Archive")  # never silently substituted
        self.assertIn(self.txt, state["selected"])  # missing input kept visible, not dropped
        info = ui.count_pages([self.pdf])
        status = ui.make_me_status(state, info, check)
        self.assertFalse(status["ok"])
        self.assertIn("no longer exists", status["message"])
        workshops.deselect(state, self.txt)  # explicit correction 1
        status = ui.make_me_status(state, info, check)
        self.assertIn("page 4 is out of range", status["message"])  # bad pages via the existing check
        workshops.set_pages(state, self.pdf, "1-2")  # correction 2
        status = ui.make_me_status(state, info, check)
        self.assertEqual(set(status["reuse"]), {"destination", "input:Lectures/notes.pdf"})
        fresh = history.check_input(self.root, {"path": "Lectures/notes.pdf", "pages": [1, 2],
                                                "fingerprint": before["inputs"][1]["fingerprint"]})
        by["Lectures/notes.pdf"].update(fresh, accepted=True)  # "Accept current file" revalidates pages
        self.assertIsNone(by["Lectures/notes.pdf"]["page_problem"])
        check["destination"]["resolved"] = True  # "Save to current folder"
        self.assertTrue(ui.make_me_status(state, info, check)["ok"])
        self.assertEqual(self.stored(gid), before)  # the History entry itself never changes

    def test_unsafe_input_and_invalid_task_need_explicit_choices(self):
        import _winapi
        gid = self.generate()["generation_id"]
        record = json.loads(json.dumps(self.stored(gid)))
        outside = self.root.parent / "Outside"
        outside.mkdir()
        (outside / "notes.pdf").write_bytes(self.pdf.read_bytes())
        _winapi.CreateJunction(str(outside), str(self.root / "Linked"))
        record["inputs"][1]["path"] = "Linked/notes.pdf"
        record["parameters"] = {"language_style": "Shouty"}
        check = history.check_reuse(self.root, record)
        self.assertEqual(check["inputs"][1]["status"], "unsafe")
        self.assertIn("Shouty", check["task_problem"])
        state = workshops.open_workshop(self.root)
        ui.apply_reuse(state, check)
        self.assertNotIn(self.root / "Linked" / "notes.pdf", state["selected"])
        self.assertEqual(set(ui.reuse_blockers(check, state)), {"task", "input:Linked/notes.pdf"})
        check["inputs"][1]["dropped"] = True
        check["task_resolved"] = True
        self.assertEqual(ui.reuse_blockers(check, state), {})
        other = {"root": self.root.parent, "current": self.root.parent, "selected": set()}
        self.assertEqual(ui.reuse_blockers({**check, "task_resolved": False}, other), {})  # another workshop

    # ---------- organizer -> History ----------
    def test_moving_a_plan_folder_remaps_every_output_and_folder(self):
        plan = self.generate("daily-study-plan", {"days": 2, "folder_name": "Week 5"}, PLAN)
        summary = self.generate()
        outcomes = self.move([self.root / "Revision" / "Week 5"], self.root / "Archive")
        res = ui.reconcile_history(str(self.root), outcomes)
        self.assertEqual((res["ok"], res["changed"]), (True, 1))
        rec = self.stored(plan["generation_id"])
        self.assertEqual(rec["output_root"], "Archive/Week 5")
        self.assertEqual(rec["destination"], "Revision")  # Revision itself did not move
        self.assertEqual([o["path"] for o in rec["outputs"]][:2], ["Archive/Week 5/Day 01/notes.pdf",
                                                                   "Archive/Week 5/Day 01/sample-questions.pdf"])
        self.assertTrue(all(history.resolve(self.root, o["path"])[1] == "available" for o in rec["outputs"]))
        self.assertEqual([(o["document_id"], o["role"], o["day"]) for o in rec["outputs"]][0],
                         ("day-01-notes", "notes", 1))
        self.assertEqual(self.stored(summary["generation_id"])["output_root"], "Revision")  # untouched

    def test_moving_or_renaming_an_input_updates_its_path_only(self):
        gid = self.generate()["generation_id"]
        before = self.stored(gid)
        ui.reconcile_history(str(self.root), self.move([self.pdf], self.root / "Archive"))
        state = workshops.open_workshop(self.root)
        workshops.browse(state, self.root / "Archive")  # tag renames act in the folder shown
        moved = self.root / "Archive" / "notes.pdf"
        req = organizing.capture_request(state, "rename", {"new_name": "notes_1.pdf"}, sources=[str(moved)])
        out = organizing.execute_plan(organizing.plan_action(req))
        ui.reconcile_history(str(self.root), out["outcomes"])
        rec = self.stored(gid)
        pdf_in = next(i for i in rec["inputs"] if i["fingerprint"] == before["inputs"][1]["fingerprint"])
        self.assertEqual(pdf_in["path"], "Archive/notes_1.pdf")
        self.assertEqual(pdf_in["pages"], [1, 3, 4])
        self.assertEqual({k: v for k, v in rec.items() if k != "inputs"}, {k: v for k, v in before.items() if k != "inputs"})
        self.assertEqual(history.check_reuse(self.root, rec)["inputs"][1]["status"], "ok")

    def test_partial_runs_and_copies_change_only_confirmed_moves(self):
        gid = self.generate()["generation_id"]
        r = self.root
        outcomes = [
            {"source": str(self.pdf), "destination": str(r / "Archive" / "notes.pdf"), "kind": "file",
             "status": "completed", "change": "moved", "error": None},
            {"source": str(self.txt), "destination": str(r / "Archive" / "extra.txt"), "kind": "file",
             "status": "failed", "change": None, "error": {"code": "x", "message": "locked"}},
            {"source": str(r / "Revision"), "destination": str(r / "Archive" / "Revision"), "kind": "folder",
             "status": "unattempted", "change": None, "error": None},
            {"source": str(r / "Revision" / "summary.pdf"), "destination": str(r / "Archive" / "copy.pdf"),
             "kind": "file", "status": "completed", "change": "copied_source_kept", "error": None},
            {"source": str(r / "Revision" / "summary.pdf"), "destination": str(r / "Archive" / "c2.pdf"),
             "kind": "file", "status": "completed", "change": "copied", "error": None}]
        history.reconcile(r, outcomes)
        rec = self.stored(gid)
        self.assertEqual(sorted(i["path"] for i in rec["inputs"]), ["Archive/notes.pdf", "Lectures/extra.txt"])
        self.assertEqual(rec["outputs"][0]["path"], "Revision/summary.pdf")  # copies keep the original

    def test_pending_retry_keeps_reconciled_paths_and_stale_saves_lose(self):
        result = self.generate()
        gid = result["generation_id"]
        old = self.stored(gid)
        outcomes = self.move([self.root / "Revision"], self.root / "Archive")
        ui.reconcile_history(str(self.root), outcomes)
        self.assertTrue(history.save_record(self.root, old)["already_saved"])  # stale save: no effect
        self.assertEqual(self.stored(gid)["output_root"], "Archive/Revision")

        (self.root / "Revision").mkdir()
        pending = self.generate()  # a second job whose save "failed": kept in memory
        rec = pending["history_record"]
        history_file = history.history_file(self.root)
        data = json.loads(history_file.read_text(encoding="utf-8"))
        data["records"] = [x for x in data["records"] if x["generation_id"] != pending["generation_id"]]
        history_file.write_text(json.dumps(data), encoding="utf-8")  # as if its save never happened
        moves = self.move([self.root / "Revision"], self.root / "Archive" / "Revision")
        rec = history.remap_record(rec, self.root, moves)[0]  # what organize_finished does in memory
        self.assertTrue(ui.record_history(str(self.root), {"history_record": rec})["saved"])
        self.assertEqual(self.stored(pending["generation_id"])["output_root"], "Archive/Revision/Revision")

    def test_failed_reconcile_retries_metadata_only(self):
        gid = self.generate()["generation_id"]
        n_calls = len(self.calls)
        with mock.patch.object(history, "_atomic_write", side_effect=PermissionError(13, "Access is denied")):
            outcomes = self.move([self.pdf], self.root / "Archive")
            res = ui.reconcile_history(str(self.root), outcomes)
        self.assertFalse(res["ok"])
        self.assertIn("History paths could not be updated", res["message"])
        self.assertTrue((self.root / "Archive" / "notes.pdf").is_file())  # the move itself happened
        self.assertEqual(self.stored(gid)["inputs"][1]["path"], "Lectures/notes.pdf")
        with mock.patch.object(organizing, "execute_plan") as no_moves:
            out = ui.retry_metadata([(str(self.root), res["moves"], res["at"])], {})
        no_moves.assert_not_called()
        self.assertEqual((out["reconciled"], out["failed_reconciles"]), (1, []))
        self.assertEqual(self.stored(gid)["inputs"][1]["path"], "Archive/notes.pdf")
        self.assertEqual(len(self.calls), n_calls)
        make_pdf(self.pdf, [page_text(n) for n in range(1, 6)])  # a new file at the old path
        later = self.generate()  # completed after the move: a late retry must not touch it
        history.reconcile(self.root, res["moves"], before=res["at"])
        self.assertEqual(self.stored(later["generation_id"])["inputs"][1]["path"], "Lectures/notes.pdf")

    def test_corrupt_history_is_left_for_recovery(self):
        f = history.history_file(self.root)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("{broken", encoding="utf-8")
        res = ui.reconcile_history(str(self.root), self.move([self.pdf], self.root / "Archive"))
        self.assertTrue(res["ok"])
        self.assertIn("left untouched for recovery", res["warning"])
        self.assertEqual(f.read_text(encoding="utf-8"), "{broken")
        self.assertIn(str(f), history.load(self.root)["warnings"][0])


if __name__ == "__main__":
    unittest.main()
