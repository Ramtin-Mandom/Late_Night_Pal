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


class CustomPrompt(unittest.TestCase):
    def test_custom_summary_replaces_stock_instructions_and_publishes_as_summary(self):
        from late_night_workshop import resource_path, tasks
        mine = "Explain membranes as a story for a ten-year-old, in three paragraphs."
        stock = resource_path("prompts/summary.md").read_text(encoding="utf-8").strip()
        style = resource_path("prompts/styles/standard.md").read_text(encoding="utf-8").strip()
        with Workshop() as w:
            body = r"\section{Membranes}Cells have membranes."
            result, calls, files = w.run("summary", [bundle(("summary", 0, "Cells", body))],
                                         {"language_style": "Standard", "custom_prompt": mine})
        self.assertEqual(result["status"], "ok", result.get("error"))
        prompt = calls[0]["prompt"]
        self.assertIn(mine, prompt)
        self.assertNotIn(stock.splitlines()[0], prompt)
        self.assertNotIn(style.splitlines()[0], prompt)
        self.assertIn("role summary", prompt)  # contract kept
        self.assertIn(tasks.package_list(), prompt)  # format.md: JSON and LaTeX rules kept
        self.assertIn("Source 1:", prompt)
        self.assertEqual(calls[0]["response_schema"]["properties"]["documents"]["maxItems"], 1)
        self.assertEqual(files, ["summary.pdf"])

    def test_blank_custom_prompt_is_rejected_before_any_call(self):
        from late_night_workshop import tasks
        with self.assertRaises(tasks.TaskError):
            tasks.validate_parameters("summary", {"custom_prompt": "  \n "})


class InjectPrompt(unittest.TestCase):
    """The writer request itself: ## High priority after the instructions, before the output rules."""
    INJECTED = "Use {curly} braces as written.\n  Second line: f(x) = {x^2}\n"
    BODY = r"\section{Membranes}Cells have membranes."

    def writer_prompt(self, parameters):
        with Workshop() as w:
            result, calls, files = w.run("summary", [bundle(("summary", 0, "Cells", self.BODY))], parameters)
        self.assertEqual(result["status"], "ok", result.get("error"))
        self.assertEqual(files, ["summary.pdf"])
        return calls[0]["prompt"]

    def text(self, name):
        from late_night_workshop import resource_path
        return resource_path(name).read_text(encoding="utf-8").strip()

    def test_built_in_prompt_gets_the_injection_between_style_and_format(self):
        prompt = self.writer_prompt({"language_style": "Standard", "injection": self.INJECTED})
        self.assertEqual(prompt.count("## High priority"), 1)
        self.assertEqual(prompt.count(self.INJECTED), 1)
        style_end = prompt.index(self.text("prompts/styles/standard.md")) + len(self.text("prompts/styles/standard.md"))
        self.assertLess(prompt.index(self.text("prompts/summary.md")), style_end)
        self.assertEqual(prompt[style_end:].index("## High priority"), 2)  # immediately after the style
        self.assertIn("## High priority\n\n" + self.INJECTED + "\n\nShared rules for every task", prompt)

        cleared = self.writer_prompt({"language_style": "Standard", "injection": ""})
        self.assertNotIn("{curly}", cleared)
        self.assertIn(self.text("prompts/styles/standard.md") + "\n\n## High priority\n\nShared rules for every task",
                      cleared)  # the section stays, empty

    def test_custom_prompt_gets_the_injection_before_the_output_contract(self):
        mine = "Only the membrane parts, as a story."
        prompt = self.writer_prompt({"language_style": "Standard", "custom_prompt": mine, "injection": self.INJECTED})
        self.assertEqual(prompt.count("## High priority"), 1)
        self.assertIn(mine + "\n\n## High priority\n\n" + self.INJECTED + "\n\nRequired output", prompt)
        self.assertLess(prompt.index("Required output"), prompt.index("Shared rules for every task"))

        cleared = self.writer_prompt({"language_style": "Standard", "custom_prompt": mine})
        self.assertNotIn("{curly}", cleared)
        self.assertIn(mine + "\n\n## High priority\n\nRequired output", cleared)


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

    WIDE = (r"\section*{Cells}" "\n" r"Counts $" + "4,1,3,5,8,10,0," * 10 + r"9$ here."  # wider than one line
            "\n\n" r"Membranes are fine.")

    def test_line_past_the_margin_gets_one_snippet_fix(self):
        with Workshop() as w:
            result, calls, files = w.run("notes", [
                bundle(("notes", 0, "Cells", self.WIDE)),
                json.dumps({"snippets": [{"id": 1, "latex": r"Counts $4$, $1$, $3$ and $5$ here."}]})])
            self.assertEqual(result["status"], "ok", result.get("error"))
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[1]["response_schema"]["required"], ["snippets"])
            self.assertIn("4,1,3,5", calls[1]["prompt"])
            self.assertNotIn("Membranes are fine", calls[1]["prompt"])  # only the overflowing passage is sent
            self.assertEqual(result["warnings"], [])
            self.assertEqual(files, ["notes.pdf"])

    def test_unusable_layout_fix_keeps_the_pdf_with_a_warning(self):
        with Workshop() as w:
            result, calls, files = w.run("notes", [bundle(("notes", 0, "Cells", self.WIDE)), "not json"])
            self.assertEqual(result["status"], "ok", result.get("error"))
            self.assertEqual(len(calls), 2)
            self.assertEqual([x["code"] for x in result["warnings"]], ["layout_overflow"])
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
