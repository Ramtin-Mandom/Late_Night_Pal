"""latex_code pipeline: contract, static check, sandbox, one repair per document, page count,
all-or-nothing publish. Gemini is stubbed; lualatex is real (about 3-7 s per compile).

    python -m unittest tests.test_latex_pipeline -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from late_night_workshop import generation, rendering, validation  # noqa: E402


def bundle(*docs, allocation=()):
    return json.dumps({"documents": [{"role": r, "day": day, "title": t, "latex_code": c} for r, day, t, c in docs],
                       "allocation": list(allocation)})


class Workshop:
    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "Lectures").mkdir()
        (self.root / "Lectures" / "cells.txt").write_text("Cells have membranes.", encoding="utf-8")
        (self.root / "Revision").mkdir()
        return self

    def __exit__(self, *exc):
        self.tmp.cleanup()

    def run(self, task_id, responses, parameters=None):
        calls = []

        def fake(task, sources):
            calls.append(task)
            return {"raw_text": responses[len(calls) - 1]}

        result = generation.generate({"workshop_root": str(self.root), "destination": str(self.root / "Revision"),
                                      "selected_paths": [str(self.root / "Lectures" / "cells.txt")],
                                      "task_id": task_id, "parameters": parameters or {}},
                                     deps={"generate_content": fake})
        return result, calls, sorted(p.name for p in (self.root / "Revision").iterdir())


class StaticChecks(unittest.TestCase):
    def test_forbidden_commands_and_environments(self):
        self.assertEqual(validation.latex_problems(r"\section*{A} \ce{H2O} \(x^2\) \begin{itemize}\item a\end{itemize}"), [])
        for bad in (r"\input{C:/x}", r"\begin{directlua}x\end{directlua}", r"\^^64irectlua", r"\usepackage{x}",
                    r"\begin{document}", r"\UseName{directlua}"):
            self.assertTrue(validation.latex_problems(bad), bad)

    def test_template_boxes_allowed_but_not_raw_tcolorbox(self):
        """Bodies use the template's study boxes; tcolorbox options could save or load files."""
        self.assertEqual(validation.latex_problems(
            r"\begin{definition}[Ideal]x \src{Lec/a_b.pdf}{3}\end{definition}\begin{question}{Q1}y\end{question}"
            r"\begin{checklist}\item z\end{checklist}\keyterm{w}"), [])
        for bad in (r"\begin{tcolorbox}[saveto=x.tex]a\end{tcolorbox}", r"\tcbset{record={x}}",
                    r"\tcbincludegraphics{C:/x.png}", r"\newtcolorbox{x}{}", r"\titleformat{\section}{}{}{0pt}{}"):
            self.assertTrue(validation.latex_problems(bad), bad)

    def test_bundle_contract_rejects_missing_latex_code(self):
        task = {"layout": {"kind": "single"}, "expected": {"roles": ["notes"]}, "label": "Notes"}
        with self.assertRaises(validation.ValidationError):
            validation.validate_bundle(json.dumps({"documents": [{"role": "notes", "day": 0, "title": "N",
                                                                  "blocks": []}], "allocation": []}), task, [])


class Sandbox(unittest.TestCase):
    def test_generated_code_cannot_read_files_or_the_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            secret = Path(tmp) / "secret.txt"
            secret.write_text("TOPSECRET", encoding="utf-8")
            work = Path(tmp) / "job"
            work.mkdir()
            os.environ["GEMINI_API_KEY"] = "KEYVALUE"
            body = (r"\directlua{local f=io.open('%s') tex.print(f and f:read('*a') or 'noread')} "
                    r"\directlua{tex.print(tostring(os.getenv('GEMINI_API_KEY')))} "
                    r"\newread\r\openin\r=%s \ifeof\r closed\else open\fi" % (secret.as_posix(), secret.as_posix()))
            pdf = rendering.compile_document({"title": "T", "latex_code": body}, work, "t")
            text = rendering.page_count(pdf) and __import__("pypdf").PdfReader(str(pdf)).pages[0].extract_text()
            self.assertNotIn("TOPSECRET", text)
            self.assertNotIn("KEYVALUE", text)
            self.assertIn("noread", text)
            self.assertIn("closed", text)


class Generation(unittest.TestCase):
    def test_compile_failure_gets_one_targeted_repair(self):
        with Workshop() as w:
            result, calls, files = w.run("notes", [
                bundle(("notes", 0, "Cells", r"\section*{Cells}\begin{itemize}\item membranes")),  # unclosed env
                json.dumps({"latex_code": r"\section*{Cells}\begin{itemize}\item membranes\end{itemize}"})])
            self.assertEqual(result["status"], "ok", result.get("error"))
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[1]["response_schema"]["required"], ["latex_code"])
            self.assertEqual(calls[1]["prompt"].count("membranes"), 1)  # repair carries only that document
            self.assertEqual(files, ["notes.pdf"])

    def test_cheat_sheet_page_count_is_checked_on_the_pdf(self):
        long = r"\section*{Long}" + r"Membrane. \par " * 400
        with Workshop() as w:
            result, calls, files = w.run("cheat-sheet", [
                bundle(("cheat-sheet", 0, "Cells", long)), json.dumps({"latex_code": long})])
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error"]["code"], "page_limit_exceeded")
            self.assertIn("also after one repair attempt", result["error"]["message"])
            self.assertEqual(len(calls), 2)
            self.assertEqual(files, [])  # nothing published

    def test_only_failed_documents_are_repaired_and_failure_publishes_nothing(self):
        alloc = [{"day": 1, "topics": ["cells"], "workload_minutes": 30, "source_ids": ["Lectures/cells.txt"]}]
        docs = [("schedule", 0, "Plan", r"\section*{Day 1: Cells} Read."),
                ("file-guide", 0, "Guide", r"\section*{Sources} none"),  # misses the source label
                ("checklist", 0, "Check", r"\begin{itemize}\item define\end{itemize}")]
        with Workshop() as w:
            result, calls, files = w.run("schedule", [bundle(*docs, allocation=alloc),
                                                      json.dumps({"latex_code": r"\input{x}"})],
                                         {"days": 1})
            self.assertEqual(result["status"], "error")
            self.assertEqual(len(calls), 2)
            self.assertIn("file-guide", calls[1]["prompt"])
            self.assertEqual(files, [])


if __name__ == "__main__":
    unittest.main()
