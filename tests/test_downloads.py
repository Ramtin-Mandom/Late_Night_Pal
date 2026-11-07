"""P2-M6 recent-download filtering and copy-to-folder import (mocked records; no real Chrome profile).
The real Chrome evidence is the P2-M1 probe (components.md -> Downloads).
Run: python -m unittest tests.test_downloads -v"""

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from late_night_workshop import downloads as D, name_tags as T, organizing as O, workshops  # noqa: E402

NOW = 1_800_000_000.0


def webkit(unix_s: float) -> int:
    return int((unix_s + D.WEBKIT_EPOCH_OFFSET_S) * 1e6)


class Downloads(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self._appdata = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = str(base / "appdata")
        self.saved = base / "Some custom folder"        # not a Downloads folder
        self.saved.mkdir()
        self.root = base / "Workshop"
        (self.root / "Inbox").mkdir(parents=True)

    def tearDown(self):
        if self._appdata is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self._appdata
        self.tmp.cleanup()

    def file(self, name, text="download"):
        p = self.saved / name
        p.write_text(text, encoding="utf-8")
        return p

    def rec(self, path, age):
        return {"path": str(path), "downloaded_at": NOW - age, "timestamp_source": D.TIMESTAMP_SOURCE}

    def test_window_existence_and_dedup(self):
        a, b, c, old, fut = (self.file(n) for n in ("a.pdf", "b.pdf", "c.pdf", "old.pdf", "future.pdf"))
        missing = self.saved / "gone.pdf"
        records = [self.rec(a, 10), self.rec(b, 3599.9), self.rec(c, 0), self.rec(old, 3600),
                   self.rec(fut, -5), self.rec(missing, 30), self.rec(a, 20)]
        got = D.recent(records, NOW)
        self.assertEqual([(Path(r["path"]).name, round(NOW - r["downloaded_at"], 1)) for r in got],
                         [("c.pdf", 0), ("a.pdf", 10), ("b.pdf", 3599.9)])
        os.utime(old, (NOW, NOW))  # a fresh modification time never makes an old download eligible
        self.assertNotIn("old.pdf", [Path(r["path"]).name for r in D.recent(records, NOW)])

    def test_provider_reads_only_completed_rows_and_degrades_gracefully(self):
        user_data = Path(self.tmp.name) / "User Data"
        prof = user_data / "Default"
        prof.mkdir(parents=True)
        done, part = self.file("done.pdf"), self.file("part.pdf")
        con = sqlite3.connect(prof / "History")
        con.execute("CREATE TABLE downloads (target_path TEXT, end_time INTEGER, state INTEGER, tab_url TEXT)")
        con.executemany("INSERT INTO downloads VALUES (?, ?, ?, 'https://example.invalid/')", [
            (str(done), webkit(NOW - 60), 1), (str(part), 0, 0), (str(part), 0, 2), (str(part), webkit(NOW - 5), 4),
            (str(part), "garbage", 1)])
        con.commit()
        con.close()
        records, excluded = D.chrome_records(prof)
        self.assertEqual([Path(r["path"]).name for r in records], ["done.pdf"])
        self.assertEqual(excluded, {0: 1, 2: 1, 4: 1, "malformed": 1})
        got = D.recent_downloads(now=NOW, user_data=user_data)
        self.assertEqual(([Path(r["path"]).name for r in got["records"]], got["errors"]), (["done.pdf"], []))
        (user_data / "Profile 1").mkdir()
        (user_data / "Profile 1" / "History").write_bytes(b"not a database")
        got = D.recent_downloads(now=NOW, user_data=user_data)
        self.assertEqual([Path(r["path"]).name for r in got["records"]], ["done.pdf"])  # other profile still counts
        self.assertEqual(len(got["errors"]), 1)
        self.assertEqual(D.recent_downloads(now=NOW, user_data=Path(self.tmp.name) / "nope")["records"], [])

    def test_copy_to_current_folder_keeps_originals_selection_and_tags(self):
        a = self.file("notes.pdf", "from chrome")
        (self.root / "Inbox/notes.pdf").write_text("already here", encoding="utf-8")
        keep = self.root / "Inbox/notes.pdf"
        state = {"root": self.root, "current": self.root / "Inbox", "selected": {keep}}
        data = T.load()
        T.add_chip(data, self.root / "Inbox", "assignment")
        before = (a.read_text(), os.stat(a).st_mtime_ns)
        req = O.capture_request(state, "paste", {"clipboard": {"paths": [str(a)], "effect": "copy"}})
        state["current"] = self.root  # navigating after the click cannot redirect the copy
        result = O.execute_plan(O.plan_action(req))
        workshops.reconcile(state, result["outcomes"])
        T.save_reconciled(data, result["outcomes"])
        self.assertEqual([(o["status"], o["change"]) for o in result["outcomes"]], [("completed", "copied")])
        self.assertEqual((self.root / "Inbox/notes (2).pdf").read_text(), "from chrome")
        self.assertEqual(keep.read_text(), "already here")                     # never overwritten
        self.assertEqual((a.read_text(), os.stat(a).st_mtime_ns), before)      # original untouched
        self.assertEqual(state["selected"], {keep})
        self.assertEqual(T.load()["folders"], {T.key(self.root / "Inbox"): {"chips": ["assignment"], "counters": {}}})

    def test_missing_source_and_partial_failure(self):
        a, b = self.file("a.pdf"), self.file("b.pdf")
        state = {"root": self.root, "current": self.root / "Inbox", "selected": set()}
        b.unlink()
        with self.assertRaises(O.OrganizeError) as cm:  # vanished since the tray was opened: nothing copied
            O.plan_action(O.capture_request(state, "paste", {"clipboard": {"paths": [str(a), str(b)], "effect": "copy"}}))
        self.assertEqual(cm.exception.code, "missing_source")
        self.assertEqual(os.listdir(self.root / "Inbox"), [])
        b = self.file("b.pdf")
        plan = O.plan_action(O.capture_request(state, "paste", {"clipboard": {"paths": [str(a), str(b)], "effect": "copy"}}))
        real = O.DEFAULT_OPS["copy"]
        ops = {"copy": lambda s, d: (_ for _ in ()).throw(PermissionError(13, "locked")) if s.name == "b.pdf" else real(s, d)}
        result = O.execute_plan(plan, ops)
        self.assertEqual([o["status"] for o in result["outcomes"]], ["completed", "failed"])
        self.assertEqual(os.listdir(self.root / "Inbox"), ["a.pdf"])
        self.assertTrue(a.exists() and b.exists())


if __name__ == "__main__":
    unittest.main()
