"""Workshop name search (P3-M1): Qt-free, read-only, safe to run off the UI thread.

search(root, query) walks the workshop with the browser's rules and returns
    {"query", "matches": [{name, path, relative, is_dir}], "warnings": [str], "cancelled": bool}
Rules shared with workshops.browse/toggle_selection:
- names starting with "." are hidden (and not descended into);
- symlinks and junctions are skipped entirely, never followed (they can't be selected, and an
  in-workshop target is found at its real location; an outside target is never reached);
- every match is a resolved path inside the workshop, the same key the shared selection uses.
Folders that can't be listed are skipped and named in a warning, so the caller can say results
are incomplete. Matching is a case-insensitive substring test on the entry's own name.
"""

import os
from pathlib import Path

from . import workshops

MAX_RESULTS = 500
MAX_NAMED_SKIPS = 3


def _key(relative: str):
    return (relative.lower(), relative)


def search(root, query: str, cancelled=lambda: False) -> dict:
    root = Path(root).resolve()
    needle = query.strip().casefold()
    out = {"query": query, "matches": [], "warnings": [], "cancelled": False}
    if not needle:
        return out
    if not root.is_dir():
        out["warnings"].append("The workshop folder is no longer available.")
        return out
    found, skipped = [], []
    stack = [root]
    while stack:
        if cancelled():
            out["cancelled"] = True
            return out
        folder = stack.pop()
        try:
            with os.scandir(folder) as it:
                entries = list(it)
        except OSError:
            skipped.append(folder)
            continue
        for entry in entries:
            if entry.name.startswith(".") or workshops.is_link(entry.path):
                continue
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue  # vanished or unreadable entry: nothing to show
            if is_dir:
                stack.append(Path(entry.path))
            if needle in entry.name.casefold():
                found.append((entry.path, entry.name, is_dir))
    for raw, name, is_dir in found:
        try:
            path = Path(raw).resolve()
        except OSError:
            continue
        if path == root or not workshops.is_inside(root, path):
            continue
        out["matches"].append({"name": name, "path": path, "is_dir": is_dir,
                               "relative": path.relative_to(root).as_posix()})
    out["matches"].sort(key=lambda m: _key(m["relative"]))
    if skipped:
        names = sorted(p.relative_to(root).as_posix() if p != root else "Workshop root" for p in skipped)
        shown = ", ".join(names[:MAX_NAMED_SKIPS]) + (f" and {len(names) - MAX_NAMED_SKIPS} more"
                                                      if len(names) > MAX_NAMED_SKIPS else "")
        out["warnings"].append(f"Results may be incomplete: {len(names)} folder"
                               f"{'s' * (len(names) != 1)} could not be read ({shown}).")
    if len(out["matches"]) > MAX_RESULTS:
        out["warnings"].append(f"Showing the first {MAX_RESULTS} of {len(out['matches'])} matches; "
                               "type more of the name to narrow them.")
        out["matches"] = out["matches"][:MAX_RESULTS]
    return out
