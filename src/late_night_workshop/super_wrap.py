"""Super Wrap grouping: pure name -> relative destination mapping (no filesystem, no UI).

Rules (PHASE_2_PROJECT_MAP_AND_MILESTONES.md, "Super Wrap: deterministic recursive grouping"):
work on stems split at "_", keep extensions exactly; at each level a stem's key is
  - every token through its first all-digit token, when tokens follow that number (Cal_1_assignment_2 -> Cal_1)
  - the tokens before that number, when the number is last (assignment_2 -> assignment)
  - nothing, when there is no number, the key is empty, or no nonempty remainder is left.
Buckets use the exact key spelling. A bucket with two or more files becomes a folder named by the
key; "key_" is removed from each member's stem and the level repeats inside it. Files alone in
their bucket keep their whole current name. Each step strips a nonempty prefix, so it terminates.

group(names) -> (destinations, folders):
    destinations[i] = tuple of relative path parts for names[i] (last part = new file name)
    folders = tuple paths of folders to create, parents before children
Validation of the resulting names (reserved names, case clashes, collisions) is organizing's job.
"""


def key(stem: str):
    tokens = stem.split("_")
    i = next((n for n, t in enumerate(tokens) if t.isascii() and t.isdigit()), None)
    if i is None:
        return None
    key_tokens = tokens[:i + 1] if i < len(tokens) - 1 else tokens[:i]
    k = "_".join(key_tokens)
    if not key_tokens or any(t == "" for t in key_tokens) or not stem[len(k) + 1:]:
        return None
    return k


def _split(name: str) -> tuple[str, str]:
    dot = name.rfind(".")
    return (name[:dot], name[dot:]) if dot > 0 else (name, "")


def group(names: list[str]) -> tuple[list[tuple], list[tuple]]:
    destinations: list = [None] * len(names)
    folders: list[tuple] = []

    def level(entries, prefix):  # entries: [(index, stem, ext)]
        buckets = {}
        for e in entries:
            k = key(e[1])
            if k is not None:
                buckets.setdefault(k, []).append(e)
        grouped = {k: m for k, m in buckets.items() if len(m) >= 2}
        in_group = {e[0] for m in grouped.values() for e in m}
        for i, stem, ext in entries:
            if i not in in_group:
                destinations[i] = prefix + (stem + ext,)
        for k in sorted(grouped):
            folders.append(prefix + (k,))
            level([(i, stem[len(k) + 1:], ext) for i, stem, ext in grouped[k]], prefix + (k,))

    level([(i, *_split(n)) for i, n in enumerate(names)], ())
    return destinations, folders
