"""P3-M1 workshop name search (no Qt). Run: python -m unittest tests.test_search -v"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from late_night_workshop import search, ui, workshops  # noqa: E402


def rels(result):
    return [m["relative"] for m in result["matches"]]


class Search(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        root = base / "Workshop"
        for rel in ("Lectures/Topic.pdf", "Readings/topic.pdf", "Readings/Deep/TOPIC notes.txt",
                    "Labs/other.docx", ".hidden/topic.pdf", "Labs/.topic-draft.pdf"):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text("fixture\n", encoding="utf-8")
        (root / "Topics").mkdir()
        (base / "Outside").mkdir()
        (base / "Outside" / "topic-secret.pdf").write_text("outside\n", encoding="utf-8")
        self.base, self.root = base, root
        self.state = {"root": root, "current": root, "selected": set()}

    def tearDown(self):
        self.tmp.cleanup()

    def test_recursive_case_insensitive_sorted_relative_paths(self):
        result = search.search(self.root, "toPIC")
        self.assertEqual(rels(result), ["Lectures/Topic.pdf", "Readings/Deep/TOPIC notes.txt",
                                        "Readings/topic.pdf", "Topics"])
        self.assertEqual(result["warnings"], [])
        self.assertEqual(rels(search.search(self.root, "toPIC")), rels(result))  # deterministic
        topics = result["matches"][-1]
        self.assertTrue(topics["is_dir"])
        self.assertEqual(search.search(self.root, "   ")["matches"], [])

    def test_hidden_entries_and_links_are_skipped(self):
        import _winapi
        _winapi.CreateJunction(str(self.base / "Outside"), str(self.root / "Linked topic"))
        _winapi.CreateJunction(str(self.root / "Readings"), str(self.root / "Labs" / "Loop"))
        self.assertTrue(workshops.is_link(self.root / "Linked topic"))
        found = rels(search.search(self.root, "topic"))
        self.assertNotIn(".hidden/topic.pdf", found)
        self.assertNotIn("Labs/.topic-draft.pdf", found)
        self.assertFalse(any("secret" in r or "Linked" in r or "Loop" in r for r in found))
        self.assertEqual(found.count("Readings/topic.pdf"), 1)  # in-workshop junction not followed twice

    def test_results_use_shared_selection_and_keep_destination(self):
        workshops.browse(self.state, self.root / "Labs")  # destination = Labs
        match = next(m for m in search.search(self.root, "topic")["matches"] if m["relative"] == "Readings/topic.pdf")
        self.assertTrue(workshops.toggle_selection(self.state, match["path"]))
        self.assertEqual(self.state["current"], self.root / "Labs")
        self.assertEqual(ui.build_request(self.state)["destination"], str(self.root / "Labs"))
        workshops.browse(self.state)  # clearing search redraws the current folder
        self.assertIn(self.root / "Readings" / "topic.pdf", self.state["selected"])

    def test_stale_responses_are_rejected(self):
        req = {"root": self.root, "query": "topic", "seq": 3}
        self.assertTrue(ui.search_is_current(req, self.state, " topic ", 3))
        self.assertFalse(ui.search_is_current(req, self.state, "topic", 4))   # newer request exists
        self.assertFalse(ui.search_is_current(req, self.state, "topi", 3))    # box changed
        other = {"root": self.base / "Outside", "current": self.base / "Outside", "selected": set()}
        self.assertFalse(ui.search_is_current(req, other, "topic", 3))       # another workshop opened
        self.assertFalse(ui.search_is_current(req, None, "topic", 3))
        self.assertTrue(search.search(self.root, "topic", cancelled=lambda: True)["cancelled"])

    def test_refresh_sees_additions_and_deletions(self):
        os.remove(self.root / "Lectures" / "Topic.pdf")
        (self.root / "Labs" / "topic-lab.pdf").write_text("new\n", encoding="utf-8")
        found = rels(search.search(self.root, "topic"))
        self.assertIn("Labs/topic-lab.pdf", found)
        self.assertNotIn("Lectures/Topic.pdf", found)

    def test_unreadable_folder_gives_incomplete_warning(self):
        real = os.scandir
        blocked = str(self.root / "Readings")

        def scandir(path):
            if str(path) == blocked:
                raise PermissionError(13, "Access is denied", blocked)
            return real(path)
        with mock.patch.object(search.os, "scandir", scandir):
            result = search.search(self.root, "topic")
        self.assertEqual(rels(result), ["Lectures/Topic.pdf", "Topics"])
        self.assertEqual(result["warnings"], ["Results may be incomplete: 1 folder could not be read (Readings)."])


if __name__ == "__main__":
    unittest.main()
