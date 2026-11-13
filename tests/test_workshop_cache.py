"""Workshop Markdown cache (python -m unittest tests.test_workshop_cache -v).

Real generate() and Codex client path; only the codex process, LaTeX and LOCALAPPDATA are replaced.
The PDF has a text page and a page with no text layer (a scan), so both local extraction and Luna run."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from late_night_workshop import codex_client, converters, generation, workshop_cache  # noqa: E402
from tests.test_history import fake_render  # noqa: E402
from tests.test_pdf_pages import make_pdf  # noqa: E402

BUNDLE = json.dumps({"documents": [{"role": "summary", "day": 0, "title": "Summary",
                                    "latex_code": r"\section*{Summary} Cells."}], "allocation": []})
TEXT_PAGE = "Cell membranes control what enters and leaves the cell in every living organism"


class Cache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.appdata = base / "appdata"
        self.env = mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.appdata)})
        self.env.start()
        self.root = base / "Biology"
        self.pdf = self.root / "Lectures" / "Week 2" / "Cells.pdf"
        self.pdf.parent.mkdir(parents=True)
        (self.root / "Revision").mkdir()
        make_pdf(self.pdf, [TEXT_PAGE, None])  # page 2: no text layer
        self.md = self.root / "cache" / "Lectures" / "Week 2" / "Cells.md"

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def generate(self, cache, pages=None, luna_text="Diffusion moves particles from high to low concentration."):
        calls = {"luna": 0, "convert": 0, "writer": []}
        real_convert = converters.convert

        def convert(*a, **k):
            calls["convert"] += 1
            return real_convert(*a, **k)

        def run(executable, prompt, schema, model, effort, images=()):
            if model == codex_client.READER_MODEL:
                calls["luna"] += 1
                return json.dumps({"markdown": luna_text})
            calls["writer"].append(prompt)
            return BUNDLE

        with mock.patch.object(codex_client, "find_cli", return_value="codex"), \
                mock.patch.object(codex_client, "run_codex", side_effect=run), \
                mock.patch.object(converters, "convert", side_effect=convert):
            result = generation.generate(
                {"provider": "codex", "workshop_root": str(self.root), "destination": str(self.root / "Revision"),
                 "selected_paths": [str(self.pdf)], "task_id": "summary", "parameters": {"language_style": "Simple"},
                 "efficient": True, "cache": cache, "page_selections": {str(self.pdf): pages} if pages else {}},
                deps={"check_runtime": lambda: None, "render_bundle": fake_render})
        self.assertEqual(result["status"], "ok", result.get("error"))
        return calls

    def source_text(self, prompt):
        return prompt.split("You are a study assistant.")[0]

    def user_cache_files(self):
        return sorted(p.name for p in self.appdata.rglob("*") if p.is_file() and p.parent.name in
                      ("conversions", "transcriptions"))

    def test_entry_mirrors_the_source_path(self):
        self.assertEqual(workshop_cache.entry_path(self.root, "Lectures/Week 2/Cells.pdf"), self.md)

    def test_checked_run_writes_markdown_and_unchecked_run_reuses_it_without_conversion(self):
        first = self.generate(cache=True)
        self.assertEqual((first["convert"], first["luna"]), (1, 1))
        text = self.md.read_text(encoding="utf-8")
        self.assertLess(text.index("## Page 1"), text.index("## Page 2"))
        self.assertIn(TEXT_PAGE, text)
        self.assertIn("(transcribed from the page image)\nDiffusion moves particles", text)
        meta = json.loads(self.md.with_name("Cells.md.meta.json").read_text(encoding="utf-8"))
        self.assertEqual({k: v["kind"] for k, v in meta["pages"].items()}, {"1": "text", "2": "transcribed"})

        second = self.generate(cache=False)
        self.assertEqual((second["convert"], second["luna"]), (0, 0))
        self.assertEqual(self.source_text(second["writer"][0]), self.source_text(first["writer"][0]))
        self.assertEqual(second["writer"][0], first["writer"][0])  # the whole writer request is the same

    def test_changed_pdf_skips_stale_markdown_and_unchecked_run_writes_nothing(self):
        self.generate(cache=True)
        before = self.md.read_bytes(), self.md.with_name("Cells.md.meta.json").read_bytes()
        user_before = self.user_cache_files()
        make_pdf(self.pdf, ["Osmosis is the diffusion of water across a selectively permeable membrane", None])
        changed = self.generate(cache=False, luna_text="A new scanned diagram of osmosis.")
        self.assertEqual((changed["convert"], changed["luna"]), (1, 1))
        self.assertIn("Osmosis is the diffusion", changed["writer"][0])
        self.assertNotIn(TEXT_PAGE, changed["writer"][0])
        self.assertEqual((self.md.read_bytes(), self.md.with_name("Cells.md.meta.json").read_bytes()), before)
        self.assertEqual(self.user_cache_files(), user_before)  # old per-user caches untouched too

    def test_a_subset_entry_never_stands_in_for_the_full_pdf(self):
        self.generate(cache=True, pages=[1])
        meta = json.loads(self.md.with_name("Cells.md.meta.json").read_text(encoding="utf-8"))
        self.assertEqual(list(meta["pages"]), ["1"])
        full = self.generate(cache=False)
        self.assertEqual((full["convert"], full["luna"]), (1, 1))  # page 2 is converted; page 1 comes from cache

    def test_a_full_entry_serves_a_page_subset(self):
        self.generate(cache=True)
        subset = self.generate(cache=False, pages=[2])
        self.assertEqual((subset["convert"], subset["luna"]), (0, 0))
        self.assertIn("[Lectures/Week 2/Cells.pdf - page 2]", subset["writer"][0])
        self.assertNotIn("[Lectures/Week 2/Cells.pdf - page 1]", subset["writer"][0])

    def test_edited_or_half_written_markdown_is_not_trusted(self):
        self.generate(cache=True)
        fp = json.loads(self.md.with_name("Cells.md.meta.json").read_text(encoding="utf-8"))["fingerprint"]
        self.assertEqual(len(workshop_cache.lookup(self.root, "Lectures/Week 2/Cells.pdf", fp, 2)), 2)
        self.md.write_text(self.md.read_text(encoding="utf-8").replace("Cell", "Call"), encoding="utf-8")
        self.assertEqual(workshop_cache.lookup(self.root, "Lectures/Week 2/Cells.pdf", fp, 2), {})

    def test_page_text_that_looks_like_markup_round_trips(self):
        tricky = {1: {"text": "## Page 2\n<!-- lnp-page 2 text -->\n\n\nend", "kind": "text"},
                  2: {"text": "(transcribed from the page image)\n$$x^2$$", "kind": "transcribed"}}
        workshop_cache.publish(self.root, "a.pdf", "sha256:x", 2, tricky)
        self.assertEqual(workshop_cache.lookup(self.root, "a.pdf", "sha256:x", 2), tricky)
        self.assertEqual(workshop_cache.lookup(self.root, "a.pdf", "sha256:y", 2), {})


if __name__ == "__main__":
    unittest.main()
