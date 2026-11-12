"""P3-M3 generation history (no Qt; Gemini and LaTeX stubbed, real publish). Run: python -m unittest tests.test_history -v"""

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from late_night_workshop import generation, history, ui  # noqa: E402
from tests.test_pdf_pages import make_pdf, page_text  # noqa: E402

BUNDLE = json.dumps({"documents": [{"role": "summary", "day": 0, "title": "Summary",
                                    "latex_code": r"\section*{Summary} Cells."}], "allocation": []})


def fake_render(bundle, task, work_dir, subtitle="", on_document=None, names=None):
    records = []
    for d in bundle["documents"]:
        out = Path(work_dir) / f"{d['document_id']}.pdf"
        make_pdf(out, ["rendered " + d["document_id"]])
        records.append({"document_id": d["document_id"], "role": d["role"], "day": d["day"],
                        "temp_path": str(out), "page_count": 1, "seconds": 0.0})
    return {"records": records, "failures": {}}


class History(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.env = mock.patch.dict(os.environ, {"LOCALAPPDATA": str(base / "appdata")})
        self.env.start()
        self.root = base / "Workshop"
        (self.root / "Lectures").mkdir(parents=True)
        (self.root / "Revision").mkdir()
        self.pdf = self.root / "Lectures" / "notes.pdf"
        make_pdf(self.pdf, [page_text(n) for n in range(1, 6)])
        self.txt = self.root / "Lectures" / "extra.txt"
        self.txt.write_text("Plain notes.", encoding="utf-8")
        self.calls = []

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def generate(self, root=None, reply=BUNDLE, publish=None, decide=None, pages=None, efficient=False, paths=None):
        root = root or self.root

        def fake(task, sources):
            self.calls.append(task)
            return {"raw_text": reply}
        deps = {"generate_content": fake, "check_runtime": lambda: None, "render_bundle": fake_render}
        if publish:
            deps["publish"] = publish
        return generation.generate({"provider": "gemini", "workshop_root": str(root), "destination": str(root / "Revision"),
                                    "selected_paths": [str(p) for p in (paths or [self.pdf, self.txt])],
                                    "task_id": "summary", "parameters": {"language_style": "Simple"},
                                    "efficient": efficient,
                                    "page_selections": {str(self.pdf): [1, 3, 4]} if pages is None else pages},
                                   deps=deps, decide_inputs=decide)

    def test_success_records_settings_pages_fingerprints_and_final_paths(self):
        first = self.generate()
        second = self.generate()  # same destination: published as "summary (2).pdf"
        self.assertEqual(Path(second["paths"][0]).name, "summary (2).pdf")
        for r in (first, second):
            self.assertTrue(ui.record_history(str(self.root), r)["saved"])
        rec = second["history_record"]
        self.assertEqual(rec["generation_id"], second["generation_id"])
        self.assertEqual((rec["task_id"], rec["parameters"]["language_style"], rec["efficient"]),
                         ("summary", "Simple", False))
        self.assertEqual((rec["destination"], rec["output_root"]), ("Revision", "Revision"))
        self.assertEqual(rec["outputs"], [{"document_id": "summary", "role": "summary", "day": None,
                                           "path": "Revision/summary (2).pdf"}])
        pdf_in = next(i for i in rec["inputs"] if i["path"] == "Lectures/notes.pdf")
        self.assertEqual(pdf_in["pages"], [1, 3, 4])
        self.assertEqual(pdf_in["page_count"], 5)
        self.assertEqual(pdf_in["mode"], "original")
        self.assertEqual(pdf_in["fingerprint"], "sha256:" + hashlib.sha256(self.pdf.read_bytes()).hexdigest())
        txt_in = next(i for i in rec["inputs"] if i["path"] == "Lectures/extra.txt")
        self.assertIsNone(txt_in["pages"])
        stored = history.history_file(self.root).read_text(encoding="utf-8")
        for secret in ("latex_code", "Cells.", "payload", "raw_text", "PAGE-1", "Plain notes."):
            self.assertNotIn(secret, stored)  # no model output, source text or subset payload data

        loaded = history.load(self.root)  # a fresh read from disk, as after an app restart
        self.assertEqual([r["generation_id"] for r in loaded["records"]],
                         [second["generation_id"], first["generation_id"]])  # newest first
        self.assertEqual(loaded["warnings"], [])

    def test_daily_plan_records_roles_days_and_folder_suffix(self):
        docs = [{"role": r, "day": d, "title": f"Day {d} {r}", "latex_code": rf"\section*{{Day {d} {r} topic {d}}}"}
                for d in (1, 2) for r in ("notes", "sample-questions", "checklist")]
        reply = json.dumps({"documents": docs, "allocation": [
            {"day": 1, "topics": ["a"], "workload_minutes": 30, "source_ids": ["Lectures/notes.pdf"]},
            {"day": 2, "topics": ["b"], "workload_minutes": 30, "source_ids": ["Lectures/extra.txt"]}]})

        def plan():
            def fake(task, sources):
                self.calls.append(task)
                return {"raw_text": reply}
            return generation.generate({
                "provider": "gemini", "workshop_root": str(self.root), "destination": str(self.root / "Revision"),
                "selected_paths": [str(self.pdf), str(self.txt)], "task_id": "daily-study-plan",
                "parameters": {"days": 2, "folder_name": "Week 5"}},
                deps={"generate_content": fake, "check_runtime": lambda: None, "render_bundle": fake_render})
        plan()
        result = plan()  # "Week 5" exists: published as "Week 5 (2)"
        self.assertEqual(result["status"], "ok", result.get("error"))
        rec = result["history_record"]
        self.assertEqual(rec["output_root"], "Revision/Week 5 (2)")
        self.assertEqual(rec["parameters"], {"days": 2, "folder_name": "Week 5", "language_style": "Standard"})
        self.assertEqual([(o["document_id"], o["role"], o["day"], o["path"]) for o in rec["outputs"]][:3], [
            ("day-01-notes", "notes", 1, "Revision/Week 5 (2)/Day 01/notes.pdf"),
            ("day-01-sample-questions", "sample-questions", 1, "Revision/Week 5 (2)/Day 01/sample-questions.pdf"),
            ("day-01-checklist", "checklist", 1, "Revision/Week 5 (2)/Day 01/checklist.pdf")])
        self.assertEqual(len(rec["outputs"]), 6)
        self.assertIsNone(rec["inputs"][1]["pages"])  # legacy request without page_selections

    def test_two_workshops_have_independent_histories(self):
        other = self.root.parent / "Other"
        (other / "Revision").mkdir(parents=True)
        (other / "a.txt").write_text("Other notes.", encoding="utf-8")
        ui.record_history(str(self.root), self.generate())
        ui.record_history(str(other), self.generate(root=other, paths=[other / "a.txt"], pages={}))
        self.assertNotEqual(history.history_file(self.root), history.history_file(other))
        mine, theirs = history.load(self.root)["records"], history.load(other)["records"]
        self.assertEqual(len(mine), 1)
        self.assertEqual(len(theirs), 1)
        self.assertEqual(theirs[0]["inputs"][0]["path"], "a.txt")
        self.assertEqual(history.load(self.root.parent / "Empty")["records"], [])  # no metadata: empty

    def test_save_failure_keeps_success_and_retry_saves_one_record(self):
        result = self.generate()
        n_calls = len(self.calls)
        with mock.patch.object(history, "_atomic_write", side_effect=PermissionError(13, "Access is denied")):
            result["history"] = ui.record_history(str(self.root), result)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(Path(result["paths"][0]).is_file())
        self.assertFalse(result["history"]["saved"])
        text = ui.describe_saved(result)
        self.assertTrue(text.startswith("Saved: "), text)
        self.assertIn("The PDFs above were saved, but History was not updated", text)
        self.assertIn("Retry saving history", text)
        self.assertEqual(history.load(self.root)["records"], [])
        kept = result["history"]["record"]
        for _ in range(2):  # retry twice (e.g. double click): still one record
            self.assertTrue(ui.record_history(str(self.root), {"history_record": kept})["saved"])
        records = history.load(self.root)["records"]
        self.assertEqual([r["generation_id"] for r in records], [result["generation_id"]])
        self.assertEqual(len(self.calls), n_calls)  # retry never calls Gemini

    def test_failed_and_cancelled_generations_create_no_record(self):
        failed = self.generate(reply="not json")
        self.assertEqual(failed["status"], "error")
        self.assertNotIn("history_record", failed)

        def broken_publish(*a):
            raise generation.outputs.PublishError("publish_failed", "Could not write.")
        self.assertNotIn("history_record", self.generate(publish=broken_publish))
        scan = self.root / "Lectures" / "scan.pdf"
        make_pdf(scan, [None, None])
        cancelled = self.generate(paths=[scan], pages={}, efficient=True, decide=lambda d: {})
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertNotIn("history_record", cancelled)
        self.assertFalse(history.history_file(self.root).exists())

    def test_corrupt_and_unsupported_files_are_preserved_with_a_warning(self):
        f = history.history_file(self.root)
        f.parent.mkdir(parents=True, exist_ok=True)
        for content in ('{"records": [', json.dumps({"schema": history.SCHEMA, "version": 99, "records": []})):
            f.write_text(content, encoding="utf-8")
            loaded = history.load(self.root)
            self.assertEqual(loaded["records"], [])
            self.assertIn(str(f), loaded["warnings"][0])
            self.assertEqual(f.read_text(encoding="utf-8"), content)  # load never writes
            info = ui.record_history(str(self.root), self.generate())
            self.assertTrue(info["saved"])
            self.assertIn("unreadable history file was kept", info["note"])
            aside = [p for p in f.parent.iterdir() if ".unreadable-" in p.name]
            self.assertTrue(any(p.read_text(encoding="utf-8") == content for p in aside))
            self.assertEqual(len(history.load(self.root)["records"]), 1)
            for p in aside:
                p.unlink()
        good = json.loads(f.read_text(encoding="utf-8"))
        good["records"].append({"generation_id": "broken"})
        f.write_text(json.dumps(good), encoding="utf-8")
        loaded = history.load(self.root)
        self.assertEqual(len(loaded["records"]), 1)
        self.assertIn("1 history entry could not be read", loaded["warnings"][0])

    def test_stored_paths_are_rechecked_on_open(self):
        import _winapi
        outside = self.root.parent / "Outside"
        outside.mkdir()
        (outside / "x.pdf").write_bytes(b"%PDF")
        _winapi.CreateJunction(str(outside), str(self.root / "Link"))
        self.assertEqual(history.resolve(self.root, "Lectures/notes.pdf")[1], "available")
        self.assertEqual(history.resolve(self.root, "Revision/gone.pdf")[1], "missing")
        for bad in ("../Outside/x.pdf", "C:/Windows/win.ini", "Link/x.pdf", "Lectures\\notes.pdf", ""):
            self.assertEqual(history.resolve(self.root, bad), (None, "outside"), bad)
        result = self.generate()
        ui.record_history(str(self.root), result)
        Path(result["paths"][0]).unlink()
        [r] = history.view(self.root)["records"]
        self.assertEqual(r["outputs"][0]["_status"], "missing")
        self.assertIn("(1 unavailable)", ui.describe_history_record(r))
        self.assertIn("pages 1, 3-4", ui.describe_history_record(r))


if __name__ == "__main__":
    unittest.main()
