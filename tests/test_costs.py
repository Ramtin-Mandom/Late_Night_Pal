"""Time, tokens and estimated cost of a job (python -m unittest tests.test_costs -v). No Codex call is made."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from late_night_workshop import codex_client, costs, ui  # noqa: E402


def events(*usages):
    lines = [{"type": "thread.started"}] + [{"type": "turn.completed", "usage": u} for u in usages]
    return ("\n".join(json.dumps(x) for x in lines) + "\nnot json\n").encode("utf-8")


class Usage(unittest.TestCase):
    def test_codex_json_events_are_recorded_and_taken_once(self):
        codex_client.take_usage()
        codex_client._record_usage("gpt-6.1-terra", events({"input_tokens": 51896, "cached_input_tokens": 0,
                                                            "output_tokens": 13799, "reasoning_output_tokens": 18}))
        codex_client._record_usage("gpt-6-luna", None)  # a failed call with no output records nothing
        self.assertEqual(codex_client.take_usage(),
                         [{"model": "gpt-6.1-terra", "input": 51896, "cached": 0, "output": 13799}])
        self.assertEqual(codex_client.take_usage(), [])

    def test_cost_counts_cached_input_at_the_cached_price(self):
        # The real Complete guide run of 2026-11-12: 1 Luna plan + 9 Terra calls (7 parts, 1 fix, 1 layout fix).
        records = [{"model": "gpt-6-luna", "input": 47966, "cached": 8576, "output": 3539},
                   {"model": "gpt-6.1-terra", "input": 198228, "cached": 73728, "output": 50135}]
        s = costs.summarize(records, 359.7)
        self.assertEqual((s["calls"], s["input"], s["cached"], s["output"]), (2, 246194, 82304, 53674))
        expected = ((47966 - 8576) * 0.10 + 8576 * 0.01 + 3539 * 0.50
                    + (198228 - 73728) * 1.00 + 73728 * 0.05 + 50135 * 5.00) / 1e6
        self.assertAlmostEqual(s["cost_usd"], round(expected, 4))
        self.assertIn("about $0.38 at API prices", costs.describe(s))
        self.assertTrue(costs.describe(s).startswith("Took 6 min 0 s · 2 Codex calls · 246K tokens in (82K cached)"))

    def test_unknown_model_is_counted_but_not_priced(self):
        s = costs.summarize([{"model": "gpt-new", "input": 1000, "cached": 0, "output": 10},
                             {"model": "gpt-6-luna", "input": 1000, "cached": 0, "output": 10}], 42)
        self.assertFalse(s["priced"])
        self.assertIn("at least $0.000 at API prices", costs.describe(s))

    def test_no_reported_tokens_shows_time_only(self):
        self.assertEqual(costs.describe(costs.summarize([], 75.4), "Gemini"),
                         "Took 1 min 15 s · token use not reported by Gemini")

    def test_status_line_after_saving(self):
        text = ui.describe_saved({"paths": ["C:/W/notes.pdf"], "run_summary": "Took 12 s · 1 Codex call"})
        self.assertTrue(text.endswith("\nTook 12 s · 1 Codex call"))


if __name__ == "__main__":
    unittest.main()
