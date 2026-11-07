"""Recent-download discovery: Chrome provider + P2-M1 feasibility probe (read-only).

Provider record: {"path": str, "downloaded_at": float (Unix seconds, UTC), "timestamp_source": str}

Chrome source (verified in P2-M1, see components.md "Downloads"): the profile's `History`
SQLite file, table `downloads`:
    target_path  final saved path (any folder the user chose, not only Downloads)
    end_time     completion time, microseconds since 1601-01-01 UTC (0 while unfinished)
    state        1 = complete; 0 in progress, 2 cancelled, 4 interrupted -> excluded
URL columns and downloads_url_chains are never read. The database is opened read-only
(immutable URI); if Chrome holds it, a temporary copy is read and deleted.

The one-hour filter, tray UI and import belong to P2-M6.
"""

import argparse
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

WEBKIT_EPOCH_OFFSET_S = 11_644_473_600  # seconds from 1601-01-01 to 1970-01-01
CHROME_COMPLETE = 1
TIMESTAMP_SOURCE = "chrome:History.downloads.end_time"


def default_chrome_user_data() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"


def _rows(history: Path) -> list[tuple]:
    query = "SELECT target_path, end_time, state FROM downloads"
    uri = "file:" + history.as_posix() + "?mode=ro&immutable=1"
    try:
        with sqlite3.connect(uri, uri=True) as con:
            return con.execute(query).fetchall()
    except sqlite3.Error:
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "History"
            shutil.copyfile(history, copy)
            con = sqlite3.connect(f"file:{copy.as_posix()}?mode=ro", uri=True)
            try:
                return con.execute(query).fetchall()
            finally:
                con.close()


def chrome_records(profile_dir) -> tuple[list[dict], dict]:
    """Completed downloads from one Chrome profile -> (records, excluded counts by state)."""
    records, excluded = [], {}
    for target, end_time, state in _rows(Path(profile_dir) / "History"):
        if state != CHROME_COMPLETE or not end_time or not target:
            excluded[state] = excluded.get(state, 0) + 1
            continue
        records.append({"path": target, "downloaded_at": end_time / 1e6 - WEBKIT_EPOCH_OFFSET_S,
                        "timestamp_source": TIMESTAMP_SOURCE})
    return records, excluded


def chrome_version(user_data: Path) -> str:
    try:
        return (user_data / "Last Version").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def probe(user_data: Path, profile: str, match: str) -> int:
    """Print only records whose filename starts with `match`, so personal history never appears."""
    from datetime import datetime, timezone
    profile_dir = user_data / profile
    if not (profile_dir / "History").is_file():
        print(f"No Chrome History at {profile_dir}")
        return 2
    records, excluded = chrome_records(profile_dir)
    print(f"Chrome {chrome_version(user_data)}; profile '{profile}'")
    shown = [r for r in records if Path(r["path"]).name.startswith(match)]
    for r in shown:
        when = datetime.fromtimestamp(r["downloaded_at"], timezone.utc).isoformat(timespec="seconds")
        print(f"complete  {r['path']}  exists={Path(r['path']).is_file()}  downloaded_at={when}  [{r['timestamp_source']}]")
    print(f"{len(shown)} matching completed; {len(records) - len(shown)} other completed not shown; "
          f"excluded by state: {dict(sorted(excluded.items()))}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m late_night_workshop.downloads")
    ap.add_argument("--user-data", type=Path, default=default_chrome_user_data())
    ap.add_argument("--profile", default="Default")
    ap.add_argument("--match", default="lnp-probe-", help="only print completed files with this name prefix")
    a = ap.parse_args(argv)
    return probe(a.user_data, a.profile, a.match)


if __name__ == "__main__":
    sys.exit(main())
