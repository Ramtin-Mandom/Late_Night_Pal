"""Complete guide: plan -> balanced parts -> parallel writers -> one joined document
(python -m unittest tests.test_parallel_guide -v). Codex and the compiler are stubbed: no allowance, no LaTeX."""
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from late_night_workshop import codex_client, generation, parallel_guide, tasks  # noqa: E402


def source(label, pages):
    return {"source_id": label, "filename": Path(label).name, "mode": "text",
            "text_parts": [{"unit": "page", "number": p, "text": f"{label} page {p} text " * 20} for p in range(1, pages + 1)]}


SOURCES = [source("Lec/a.pdf", 6), source("Lec/b.pdf", 6)]  # 12 pages -> 5 parts
TASK = {"label": "Complete guide", "prompt": "TASK PROMPT", "expected": {"roles": ["notes"]}}
UNITS = [{"file": "Lec/a.pdf", "first": f, "last": l, "topic": f"A{f}", "covers": [f"Example A{f}"],
          "defines": [f"term A{f}"], "needs": ["term A1: recap"] if f > 1 else []}
         for f, l in ((1, 2), (3, 4), (5, 6))] + \
        [{"file": "b.pdf", "first": f, "last": l, "topic": f"B{f}", "covers": [], "defines": [], "needs": []}
         for f, l in ((1, 2), (3, 4), (5, 6))]
PLAN = {"title": "Course Study Guide Plan", "intro": "Covers A and B; 100% of it.", "notation": ["x̄ = mean"],
        "continuing_examples": [], "units": UNITS}


class FakeCodex:
    """Answers by schema: the plan, a part body (naming its own pages), or a fix."""

    def __init__(self, plans, bad_parts=(), fixes=()):
        self.plans, self.bad, self.fixes = list(plans), set(bad_parts), list(fixes)
        self.prompts, self.lock = [], threading.Lock()

    def __call__(self, executable, prompt, schema, model, effort, images=()):
        with self.lock:
            self.prompts.append((schema, model, prompt))
        if schema is parallel_guide.PLAN_SCHEMA:
            return json.dumps(self.plans.pop(0))
        if schema is parallel_guide.FIX_SCHEMA:
            return json.dumps({"latex_code": self.fixes.pop(0)})
        k = int(prompt.split("PARALLEL ASSIGNMENT ")[1].split(" ")[0])
        body = r"\section{Part %d}" % k + ("\\BROKEN" if k in self.bad else "") + "\n\\newcommand{\\v}{x}"
        return json.dumps({"latex_code": body, "takeaways": [f"takeaway {k}"]})


def compile_check(code):
    return "! Undefined control sequence \\BROKEN" if "\\BROKEN" in code else ""


class Rules(unittest.TestCase):
    def test_part_count(self):
        self.assertEqual([parallel_guide.part_count(p) for p in (12, 99, 100, 160, 300)], [5, 5, 5, 7, 13])

    def test_balance_minimises_the_largest_part(self):
        self.assertEqual(parallel_guide.balance([10, 10, 10, 40, 10, 10, 10], 3), [(0, 3), (3, 4), (4, 7)])
        self.assertEqual(parallel_guide.balance([1, 1], 5), [(0, 1), (1, 2)])  # never more parts than units

    def test_plan_must_cover_every_page_once(self):
        units, problem = parallel_guide.check_units(dict(PLAN, units=UNITS[:-1]), SOURCES)
        self.assertEqual(units, [])
        self.assertIn("b.pdf p5", problem)
        units, problem = parallel_guide.check_units(PLAN, SOURCES)
        self.assertEqual((len(units), problem), (6, ""))


class Generate(unittest.TestCase):
    def run_guide(self, fake):
        statuses = []
        with mock.patch.object(codex_client, "find_cli", return_value="codex"):
            result = parallel_guide.generate(TASK, SOURCES, statuses.append, run=fake, compile_check=compile_check)
        return json.loads(result["raw_text"]), statuses

    def test_parts_are_written_at_once_and_joined_in_order(self):
        fake = FakeCodex([PLAN])
        bundle, statuses = self.run_guide(fake)
        doc = bundle["documents"][0]
        self.assertEqual((doc["role"], doc["day"], doc["title"]), ("notes", 0, "Course Study Guide"))
        code = doc["latex_code"]
        self.assertTrue(code.startswith(r"Covers A and B; 100\% of it."))
        self.assertLess(code.index("Part 1"), code.index("Part 5"))
        self.assertIn("\\section*{Key takeaways}", code)
        self.assertIn("\\item takeaway 5", code)
        self.assertNotIn("\\newcommand", code)
        writers = [p for s, m, p in fake.prompts if s is parallel_guide.PART_SCHEMA]
        self.assertEqual(len(writers), 5)
        self.assertEqual(fake.prompts[0][1], parallel_guide.PLANNER_MODEL)
        first = next(p for p in writers if "ASSIGNMENT 1 OF" in p)
        self.assertIn("[Lec/a.pdf - page 1]", first)
        self.assertNotIn("[Lec/b.pdf - page 1]", first)  # a writer sees only its own pages
        self.assertIn("x̄ = mean", first)
        self.assertIn("5 of 5 parts written", statuses[-2])

    def test_unusable_plan_is_asked_again_then_written_in_one_request(self):
        bad = dict(PLAN, units=UNITS[:2])
        fake = FakeCodex([bad, bad])
        with mock.patch.object(codex_client, "generate_content",
                               return_value={"raw_text": "single", "usage": {}}) as single, \
                mock.patch.object(codex_client, "find_cli", return_value="codex"):
            result = parallel_guide.generate(TASK, SOURCES, lambda m: None, run=fake, compile_check=compile_check)
        self.assertEqual(result["raw_text"], "single")
        self.assertEqual(single.call_count, 1)
        self.assertIn("previous plan was rejected", fake.prompts[1][2])

    def test_a_broken_part_gets_one_small_fix(self):
        fake = FakeCodex([PLAN], bad_parts={3}, fixes=[r"\section{Part 3 fixed}"])
        bundle, statuses = self.run_guide(fake)
        self.assertIn("Part 3 fixed", bundle["documents"][0]["latex_code"])
        fix = [p for s, m, p in fake.prompts if s is parallel_guide.FIX_SCHEMA]
        self.assertEqual(len(fix), 1)
        self.assertIn("\\BROKEN", fix[0])
        self.assertNotIn("Part 1", fix[0])  # only that part is sent

    def test_a_part_still_broken_after_its_fix_fails_the_job(self):
        fake = FakeCodex([PLAN], bad_parts={2}, fixes=[r"\section{x}\BROKEN"])
        with self.assertRaises(codex_client.CodexError):
            self.run_guide(fake)


class Wiring(unittest.TestCase):
    def test_complete_guide_is_a_codex_task(self):
        self.assertIn(("complete-guide", "Complete guide"), tasks.tasks_for(tasks.SINGLE_FILE))
        result = generation.generate({"workshop_root": ".", "destination": ".", "selected_paths": ["x.pdf"],
                                      "provider": "gemini", "task_id": "complete-guide", "parameters": {}})
        self.assertEqual(result["status"], "error")
        self.assertIn("written by Codex", result["error"]["message"])


if __name__ == "__main__":
    unittest.main()
