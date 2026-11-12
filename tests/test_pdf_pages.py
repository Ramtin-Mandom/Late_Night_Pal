"""P3-M2 PDF page selection end to end (no Qt, Gemini stubbed). Run: python -m unittest tests.test_pdf_pages -v

Fixture PDFs are written by hand (one Helvetica text line per page, or an empty page as a "scan").
"""

import base64
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from late_night_workshop import gemini_client, generation, inputs, pdf_pages, ui, workshops  # noqa: E402


def make_pdf(path, texts):
    """texts[i] is page i+1's text; None makes an empty page (no text layer, like a scan)."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for t in texts:
        stream = "" if t is None else f"BT /F1 12 Tf 72 720 Td ({t}) Tj ET"
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> "
                    f"/Contents {len(objs)} 0 R >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(texts)} >>"
    out, offsets = io.BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for i, o in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1"))
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    Path(path).write_bytes(out.getvalue())


def page_text(n):
    return f"PAGE-{n} distinct content about topic number {n} for the study workshop fixture"


def pdf_texts(data: bytes) -> list[str]:
    from pypdf import PdfReader
    return [(p.extract_text() or "").strip() for p in PdfReader(io.BytesIO(data)).pages]


class Pages(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.old_appdata = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = str(base / "appdata")  # private conversion cache
        root = base / "Workshop"
        (root / "Lectures").mkdir(parents=True)
        (root / "Revision").mkdir()
        self.pdf = root / "Lectures" / "notes.pdf"
        make_pdf(self.pdf, [page_text(n) for n in range(1, 6)])
        self.scan = root / "Lectures" / "scan.pdf"
        make_pdf(self.scan, [page_text(1), None, page_text(3), page_text(4)])
        self.txt = root / "Lectures" / "extra.txt"
        self.txt.write_text("Plain text notes about cells.", encoding="utf-8")
        self.root = root
        self.calls, self.sent, self.payload_dirs = [], [], []
        real = inputs.prepare_inputs

        def spy(*a, **k):
            self.payload_dirs.append(k.get("payload_dir"))
            return real(*a, **k)
        self._real_prepare, generation.inputs.prepare_inputs = real, spy

    def tearDown(self):
        generation.inputs.prepare_inputs = self._real_prepare
        if self.old_appdata is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self.old_appdata
        self.tmp.cleanup()

    def run_job(self, paths, pages=None, efficient=False, decide=None, before_send=None):
        """Generate with a stub client; the stub builds the real transmitted items (_source_items)."""
        first = []

        def fake(task, sources):
            self.calls.append(task)
            if not first:
                first.append(True)
                if before_send:
                    before_send(sources)
                self.sent.append({"task": task, "sources": [dict(s) for s in sources],
                                  "items": gemini_client._source_items(sources)})
            return {"raw_text": "not json"}  # stops the job after the first request (one repair, then error)

        request = {"provider": "gemini", "workshop_root": str(self.root), "destination": str(self.root / "Revision"),
                   "selected_paths": [str(p) for p in paths], "task_id": "summary",
                   "parameters": {"language_style": "Standard"}, "efficient": efficient}
        if pages is not None:
            request["page_selections"] = pages
        return generation.generate(request, deps={"generate_content": fake, "check_runtime": lambda: None},
                                   decide_inputs=decide)

    def documents(self):
        return [base64.b64decode(i["data"]) for i in self.sent[0]["items"] if i["type"] == "document"]

    def assert_cleaned(self):
        self.assertTrue(self.payload_dirs)
        for d in self.payload_dirs:
            self.assertFalse(Path(d).exists(), d)

    # ---------- parsing ----------
    def test_parse_normalizes_and_rejects_with_filename(self):
        self.assertEqual(pdf_pages.parse_spec("3-4, 1, 4, 2-3", "a.pdf"), [1, 2, 3, 4])
        self.assertEqual(pdf_pages.parse_spec(" 8,1 , 3-5 ", "a.pdf"), [1, 3, 4, 5, 8])
        self.assertIsNone(pdf_pages.parse_spec("  ", "a.pdf"))
        for bad in ("x", "4-2", "0", "-1", "1,,2", "1-", "2-0"):
            with self.assertRaises(pdf_pages.PageError) as e:
                pdf_pages.parse_spec(bad, "Lectures/a.pdf")
            self.assertTrue(e.exception.message.startswith("Lectures/a.pdf"), e.exception.message)
        with self.assertRaises(pdf_pages.PageError) as e:
            pdf_pages.validate([1, 9], 5, "Lectures/a.pdf")
        self.assertEqual(e.exception.message, "Lectures/a.pdf has 5 pages; page 9 is out of range.")
        self.assertIsNone(pdf_pages.validate([1, 2, 3, 4, 5], 5, "a.pdf"))  # every page = All pages
        self.assertEqual(pdf_pages.format_pages([1, 3, 4, 8]), "1, 3-4, 8")
        self.assertEqual(pdf_pages.describe([1, 3, 4], 5), "Pages 1, 3-4 (3 of 5)")

    # ---------- original mode ----------
    def test_original_mode_sends_only_selected_pages_with_mapping(self):
        result = self.run_job([self.pdf], {str(self.pdf): [1, 3, 4]})
        self.assertEqual(result["status"], "error")  # the stub's unusable JSON, after one request + repair
        src = self.sent[0]["sources"][0]
        self.assertEqual(src["mode"], "original")
        self.assertEqual(src["page_map"], [1, 3, 4])
        self.assertEqual(src["original_path"], str(self.pdf))
        self.assertEqual(src["fingerprint"], "sha256:" + __import__("hashlib").sha256(self.pdf.read_bytes()).hexdigest())
        self.assertNotEqual(src["payload_fingerprint"], src["fingerprint"])
        [doc] = self.documents()
        self.assertEqual(pdf_texts(doc), [page_text(1), page_text(3), page_text(4)])
        label = [i["text"] for i in self.sent[0]["items"] if i["type"] == "text"][0]
        self.assertIn("1→1, 2→3, 3→4", label)
        self.assertIn("only original pages 1, 3-4 of 5", self.sent[0]["task"]["prompt"])
        self.assert_cleaned()

    def test_pages_3_and_8_keep_their_original_numbers(self):
        make_pdf(self.pdf, [page_text(n) for n in range(1, 11)])
        self.run_job([self.pdf], {str(self.pdf): "8, 3"})  # raw text is accepted and normalized
        self.assertEqual(pdf_texts(self.documents()[0]), [page_text(3), page_text(8)])
        self.assertIn("1→3, 2→8", self.sent[0]["items"][0]["text"])
        self.run_job([self.pdf], {str(self.pdf): [3, 8]}, efficient=True)
        text = self.sent[1]["items"][0]["text"]
        self.assertIn("[Lectures/notes.pdf - page 3]", text)
        self.assertIn("[Lectures/notes.pdf - page 8]", text)
        self.assertNotIn("PAGE-1 ", text)

    def test_legacy_request_without_pages_sends_full_document(self):
        self.run_job([self.pdf])  # no page_selections field at all
        src = self.sent[0]["sources"][0]
        self.assertIsNone(src["pages"])
        self.assertNotIn("payload_path", src)
        self.assertEqual(self.documents(), [self.pdf.read_bytes()])

    # ---------- efficient mode, scans, cache ----------
    def test_efficient_mode_filters_units_and_cache_serves_two_selections(self):
        self.run_job([self.pdf, self.txt], {str(self.pdf): [1, 3, 4]}, efficient=True)
        self.assertEqual([s["source_id"] for s in self.sent[0]["sources"]], ["Lectures/extra.txt", "Lectures/notes.pdf"])
        src = self.sent[0]["sources"][1]
        self.assertEqual([u["number"] for u in src["text_parts"]], [1, 3, 4])
        self.assertEqual(src["cache"], "miss")
        text = self.sent[0]["items"][1]["text"]
        self.assertIn("[Lectures/notes.pdf - page 3]", text)
        self.assertNotIn(page_text(2), text)
        self.assertIn("Plain text notes about cells.", self.sent[0]["items"][0]["text"])  # mixed request still works
        self.run_job([self.pdf], {str(self.pdf): [2, 5]}, efficient=True)
        again = self.sent[1]["sources"][0]
        self.assertEqual(again["cache"], "hit")
        self.assertEqual([u["number"] for u in again["text_parts"]], [2, 5])
        self.assertIn(page_text(5), self.sent[1]["items"][0]["text"])

    def test_unselected_scanned_page_does_not_ask(self):
        asked = []
        self.run_job([self.scan], {str(self.scan): [1, 3, 4]}, efficient=True, decide=lambda d: asked.append(d) or {})
        self.assertEqual(asked, [])
        self.assertEqual(self.sent[0]["sources"][0]["mode"], "text")

    def test_process_original_sends_selected_pages_only(self):
        asked = []
        self.run_job([self.scan], {str(self.scan): [1, 2]}, efficient=True,
                     decide=lambda d: asked.append(d) or {"Lectures/scan.pdf": "process_original"})
        self.assertEqual(asked[0][0]["units"], [2])
        self.assertEqual(self.sent[0]["sources"][0]["page_map"], [1, 2])
        self.assertEqual(pdf_texts(self.documents()[0]), [page_text(1), ""])
        self.assert_cleaned()

    def test_cancel_makes_no_call_and_cleans_up(self):
        result = self.run_job([self.scan], {str(self.scan): [2, 3]}, efficient=True, decide=lambda d: {})
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(self.calls, [])
        self.assert_cleaned()

    # ---------- failures before / at sending ----------
    def test_invalid_ranges_fail_before_the_client(self):
        for choice, code in (("9", "invalid_pages"), ("4-2", "invalid_pages"), ([0, 1], "invalid_pages")):
            result = self.run_job([self.pdf], {str(self.pdf): choice})
            self.assertEqual(result["error"]["code"], code)
            self.assertIn("Lectures/notes.pdf", result["error"]["message"])
        self.assertEqual(self.calls, [])

    def test_encrypted_pdf_is_reported_before_sending(self):
        from pypdf import PdfReader, PdfWriter
        w = PdfWriter(clone_from=PdfReader(str(self.pdf)))
        w.encrypt("secret")
        locked = self.root / "Lectures" / "locked.pdf"
        with open(locked, "wb") as f:
            w.write(f)
        result = self.run_job([locked])
        self.assertEqual(result["error"]["code"], "pdf_encrypted")
        self.assertIn("Lectures/locked.pdf", result["error"]["message"])
        self.assertEqual(self.calls, [])

    def test_source_change_is_detected_and_payload_cleaned(self):
        def edit(sources):
            make_pdf(self.pdf, [page_text(n) + " changed" for n in range(1, 6)])
        result = self.run_job([self.pdf], {str(self.pdf): [1, 3]}, before_send=edit)
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.sent, [])  # _source_items raised source_changed
        self.assertEqual(result["error"]["code"], "source_changed")
        self.assert_cleaned()

    def test_tampered_payload_is_rejected(self):
        def tamper(sources):
            Path(sources[0]["payload_path"]).write_bytes(b"%PDF-1.4 other")
        result = self.run_job([self.pdf], {str(self.pdf): [2]}, before_send=tamper)
        self.assertEqual(result["error"]["code"], "payload_changed")
        self.assert_cleaned()

    # ---------- settings in the workshop state ----------
    def test_settings_follow_selection_navigation_search_and_moves(self):
        state = workshops.open_workshop(self.root)
        workshops.toggle_selection(state, self.pdf)
        workshops.set_pages(state, self.pdf, " 3-4, 1 ")
        request = ui.build_request(state)
        self.assertEqual(request["page_selections"], {str(self.pdf): [1, 3, 4]})
        workshops.set_pages(state, self.pdf, "2")  # a later edit cannot reach the captured request
        self.assertEqual(request["page_selections"], {str(self.pdf): [1, 3, 4]})
        workshops.browse(state, self.root / "Revision")
        __import__("late_night_workshop.search").search.search(self.root, "notes")
        self.assertEqual(state["pages"], {self.pdf: "2"})
        moved = self.root / "Revision" / "Lectures"
        workshops.reconcile(state, [{"status": "completed", "change": "moved", "source": str(self.root / "Lectures"),
                                     "destination": str(moved)}])
        self.assertEqual(state["pages"], {moved / "notes.pdf": "2"})
        workshops.toggle_selection(state, self.pdf)  # unrelated path: no effect on the moved one
        state["selected"].discard(self.pdf)
        state["selected"].add(moved / "notes.pdf")
        workshops.deselect(state, moved / "notes.pdf")
        self.assertEqual(state["pages"], {})
        self.assertEqual(ui.build_request(state)["page_selections"], {})
        legacy = {"root": self.root, "current": self.root, "selected": {self.pdf}}  # state without "pages"
        self.assertEqual(ui.build_request(legacy)["page_selections"], {})

    def test_make_me_status_names_bad_pages(self):
        state = workshops.open_workshop(self.root)
        workshops.toggle_selection(state, self.pdf)
        workshops.set_pages(state, self.pdf, "2-9")
        info = ui.count_pages([self.pdf])
        self.assertEqual(info[self.pdf]["count"], 5)
        status = ui.make_me_status(state, info)
        self.assertFalse(status["ok"])
        self.assertIn("Lectures/notes.pdf has 5 pages; page 9 is out of range.", status["message"])
        workshops.set_pages(state, self.pdf, "")
        self.assertTrue(ui.make_me_status(state, info)["ok"])
        self.assertEqual(ui.describe_pages(state, self.pdf, info[self.pdf]), "All 5 pages")


if __name__ == "__main__":
    unittest.main()
