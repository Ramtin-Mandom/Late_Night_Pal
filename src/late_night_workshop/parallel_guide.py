"""Complete guide: one study guide written by several Codex calls at once.

    generate(task, sources, on_status, run=codex_client.run_codex, compile_check=compile_part)
        -> {"raw_text": bundle JSON, "usage": {}}   (the same bundle a single Codex call returns)

1. Scanned pages are read first (codex_client.read_scans), so every step below sees text only.
2. PLANNER_MODEL marks the course as ordered topic units (contiguous pages, never inside an example)
   with shared notation; check_units() rejects a plan that skips or repeats a page (asked once more).
3. balance() groups the units into part_count(pages) parts of near-equal text length:
   fewer than 100 pages -> 5 parts; otherwise about PAGES_PER_PART pages per part (300 pages -> 13).
4. Every part goes to codex_client.WRITER_MODEL at the same time with only its pages, the task prompt and
   PART_RULES (its topics, the terms it defines, recaps of earlier topics, the topics around it).
5. Each part is checked and compiled on its own; a failing part gets one small repair request, so a
   mistake never forces a rewrite of the whole guide.
6. Python joins intro + parts + Key takeaways into one notes document.
If the plan is unusable twice, or there are too few units to split, the guide is written in one request.
"""

import json
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import codex_client, rendering, validation
from .codex_client import CodexError

PLANNER_MODEL, PLANNER_EFFORT = "gpt-6-luna", "low"
PAGES_PER_PART = 23
MAX_WRITERS = 13

PLAN_PROMPT = """You are the lead editor of one study guide. Writers will produce it in parallel from the lecture
files below (Markdown, one "## Page n" section per page or slide); each writer sees only some pages plus your
plan. The application will group your units into {n} writer assignments of similar size, so mark the course's
structure precisely and give the shared context. Do not write the guide.

units: the whole course as an ordered list of topic units, about {units_lo}-{units_hi} units in total.
- Each unit is ONE contiguous page range of ONE file, named by the file's exact label. Together the units cover
  all {total} pages exactly once, in course order (file 1 first, then file 2, ...). Title pages belong to the
  first unit of their file.
- A unit boundary must fall between topics. Never cut inside a worked example, an exercise and its solution, a
  derivation or proof, or a table that runs over pages. Read the pages to find these.
- topic: a short name. covers: the concepts and every lecture example or exercise in the unit, named briefly
  (e.g. "Example: firm bids on 3 jobs"), at most 8 items of a few words each. defines: terms first defined here.
  needs: concepts from earlier units it builds on, each as "term: one-line recap", at most 4.

Also give:
- title: the guide's title (a document title such as "STAT 271 Study Guide"; never the word "plan").
- intro: 2-3 plain sentences: what the guide covers and how to use it.
- notation: at most 8 conventions every writer must share exactly (symbols, parametrisations, which variance
  divides by n-1, percentile convention).
- continuing_examples: at most 5 examples or data sets that appear in more than one unit, naming the units.
Keep the whole plan short: about 2000 words at most.{retry}

{files}"""

_STR, _STRS = {"type": "string"}, {"type": "array", "items": {"type": "string"}}
PLAN_SCHEMA = {"type": "object", "required": ["title", "intro", "notation", "continuing_examples", "units"],
               "properties": {"title": _STR, "intro": _STR, "notation": _STRS, "continuing_examples": _STRS,
                              "units": {"type": "array", "items": {"type": "object", "required": [
                                  "file", "first", "last", "topic", "covers", "defines", "needs"], "properties": {
                                  "file": _STR, "first": {"type": "integer"}, "last": {"type": "integer"},
                                  "topic": _STR, "covers": _STRS, "defines": _STRS, "needs": _STRS}}}}}
PART_SCHEMA = {"type": "object", "required": ["latex_code", "takeaways"],
               "properties": {"latex_code": _STR, "takeaways": _STRS}}
FIX_SCHEMA = {"type": "object", "required": ["latex_code"], "properties": {"latex_code": _STR}}

PART_RULES = """PARALLEL ASSIGNMENT {k} OF {n}. These instructions override the task above where they differ.
Other writers are writing the rest of the same guide at this moment; the application joins everything in course
order into one document, so the reader sees one continuous guide.
- Return JSON {{"latex_code": "...", "takeaways": ["..."]}}. latex_code is the body of your sections only.
- Do not write the guide's opening paragraph or a Key takeaways section: the application adds both. Start
  directly with your first \\section{{...}}; sections are numbered automatically across the whole guide.
- takeaways: 2-4 one-line LaTeX items (inline math allowed) for the guide's final Key takeaways list.
- Begin every \\label name with p{k}- and do not define macros with \\newcommand.
- Never mention parts, assignments, writers or "this part". To point elsewhere, name the topic or section
  ("as in the section on conditional probability", "the next section").
- End every section with a yourturn box, as the task says.

Your topics, in order, with what each must teach completely (every named example and exercise):
{units}

Define these terms here (no other section defines them): {defines}
Built on earlier sections: where first needed, recap each in at most one sentence, then build on it:
{needs}
Taught elsewhere in the guide, so only refer to them by topic: {elsewhere}
Continuity: {before}{after}
Continuing examples across the guide: {cont}
Shared notation (use exactly): {notation}"""

FIX_PROMPT = """These sections of a study guide cannot be used yet: {problem}
Return JSON {{"latex_code": "..."}} with the complete corrected LaTeX body of these sections only. Fix that problem
and keep the content, structure and wording otherwise. Follow the LaTeX rules below exactly.

{task_prompt}

Current latex_code:
{latex_code}"""


def part_count(pages: int) -> int:
    return 5 if pages < 100 else max(5, round(pages / PAGES_PER_PART))


def balance(sizes: list[int], n: int) -> list[tuple[int, int]]:
    """Split sizes (in order) into n contiguous non-empty groups, minimising the largest group sum.
    Returns [(start, end_exclusive)]. Exact dynamic programme; unit counts are small."""
    m = len(sizes)
    n = max(1, min(n, m))
    pre = [0]
    for s in sizes:
        pre.append(pre[-1] + s)
    inf = float("inf")
    best = [[inf] * (m + 1) for _ in range(n + 1)]
    cut = [[0] * (m + 1) for _ in range(n + 1)]
    best[0][0] = 0
    for g in range(1, n + 1):
        for j in range(g, m + 1):
            for i in range(g - 1, j):
                v = max(best[g - 1][i], pre[j] - pre[i])
                if v < best[g][j]:
                    best[g][j], cut[g][j] = v, i
    groups, j = [], m
    for g in range(n, 0, -1):
        groups.append((cut[g][j], j))
        j = cut[g][j]
    return groups[::-1]


def _units_of(source: dict) -> list[tuple[int, dict]]:
    """(number, text unit) for every unit of a source; units without a page/slide number get their position."""
    return [(u.get("number") or pos, u) for pos, u in enumerate(source["text_parts"], 1)]


def course_markdown(sources: list[dict]) -> str:
    out = []
    for s in sources:
        out.append(f"# {s['source_id']}\n\n" + "\n\n".join(f"## Page {num}\n\n{(u.get('text') or '').strip()}"
                                                          for num, u in _units_of(s)))
    return "\n\n".join(out)


def _match_source(label: str, sources: list[dict]):
    for s in sources:
        if label == s["source_id"]:
            return s
    stem = Path(label).stem.lower()
    found = [s for s in sources if Path(s["source_id"]).stem.lower() == stem]
    return found[0] if len(found) == 1 else None


def check_units(plan: dict, sources: list[dict]) -> tuple[list[dict], str]:
    """Units with "source" and "size" (characters of text) added, or [] and the problem in words."""
    lengths = {(s["source_id"], num): len(u.get("text") or "") for s in sources for num, u in _units_of(s)}
    seen, units = {}, []
    for u in plan.get("units") or []:
        s = _match_source(u.get("file", ""), sources)
        if s is None:
            return [], f"unit '{u.get('topic')}' names an unknown file '{u.get('file')}'"
        if u["first"] > u["last"]:
            return [], f"unit '{u['topic']}' has first page after last page"
        size = 0
        for pg in range(u["first"], u["last"] + 1):
            key = (s["source_id"], pg)
            if key not in lengths:
                return [], f"unit '{u['topic']}' names page {pg} of {s['source_id']}, which does not exist"
            seen[key] = seen.get(key, 0) + 1
            size += lengths[key]
        units.append(dict(u, source=s["source_id"], size=max(size, 1)))
    missing = [k for k in lengths if k not in seen]
    twice = [k for k, v in seen.items() if v > 1]
    if missing:
        return [], "these pages are in no unit: " + ", ".join(f"{a} p{b}" for a, b in missing[:12])
    if twice:
        return [], "these pages are in more than one unit: " + ", ".join(f"{a} p{b}" for a, b in twice[:12])
    return units, ""


def _part_sources(part: list[dict], sources: list[dict]) -> str:
    items = []
    for i, s in enumerate(sources, 1):
        pages = {pg for u in part if u["source"] == s["source_id"] for pg in range(u["first"], u["last"] + 1)}
        if pages:
            kept = [u for num, u in _units_of(s) if num in pages]
            items.append(codex_client.text_source_item(i, dict(s, text_parts=kept)))
    return "\n\n".join(items)


def part_prompt(k: int, parts: list[list[dict]], plan: dict, task: dict, sources: list[dict]) -> str:
    part = parts[k - 1]
    j = lambda xs: "; ".join(xs) or "none"
    own = {d.lower() for u in part for d in u["defines"]}
    elsewhere = [d for q in parts if q is not part for u in q for d in u["defines"] if d.lower() not in own]
    needs = [x for u in part for x in u["needs"] if x.split(":")[0].strip().lower() not in own]
    before = [u["topic"] for q in parts[:k - 1] for u in q]
    after = [u["topic"] for q in parts[k:] for u in q]
    rules = PART_RULES.format(
        k=k, n=len(parts),
        units="\n".join(f"- {u['topic']} ({u['source']} pp. {u['first']}-{u['last']}): {j(u['covers'])}" for u in part),
        defines=j(sorted(own)), needs="\n".join(f"  - {x}" for x in needs) or "  none", elsewhere=j(elsewhere),
        before=(f"the sections just before yours end with \"{before[-1]}\"; open your first section by connecting "
                f"from it in one sentence. " if before else "yours are the first sections of the guide. "),
        after=(f"The section right after yours is \"{after[0]}\"; end your last section's main text with one sentence "
               f"leading into it." if after else "Yours are the last sections of the guide."),
        cont=j(plan.get("continuing_examples") or []), notation=j(plan.get("notation") or []))
    return _part_sources(part, sources) + "\n\n" + task["prompt"] + "\n\n" + rules


def compile_part(latex_code: str) -> str:
    """'' when this body compiles on its own in the app's template, else the LaTeX error lines."""
    with tempfile.TemporaryDirectory(prefix="lnp_part_") as folder:
        try:
            rendering.compile_document({"title": "Part", "latex_code": latex_code}, Path(folder), "part")
        except rendering.RenderError as e:
            return e.details or e.message
    return ""


def join(plan: dict, bodies: list[str], takeaways: list[str]) -> str:
    items = "\n".join(f"  \\item {t}" for t in takeaways if t.strip())
    tail = f"\n\n\\section*{{Key takeaways}}\n\\begin{{itemize}}\n{items}\n\\end{{itemize}}\n" if items else "\n"
    return rendering.escape(plan.get("intro", "").strip()) + "\n\n" + "\n\n".join(bodies) + tail


def _title(plan: dict, task: dict) -> str:
    title = re.sub(r"\s*\b[Pp]lan\b\s*$", "", plan.get("title") or "").strip()
    return title or task["label"]


def generate(task, sources, on_status=lambda message: None, run=None, compile_check=compile_part):
    """The Complete guide bundle from parallel Codex calls; falls back to one request when it can't split."""
    executable = codex_client.find_cli()
    if not executable:
        raise CodexError("codex_missing", "Install the Codex CLI on PATH, run codex login, then restart Late Night Pal.")
    run = run or codex_client.run_codex
    sources = codex_client.read_scans(executable, sources)
    total = sum(len(s["text_parts"]) for s in sources)
    n = part_count(total)
    markdown = course_markdown(sources)

    on_status(f"Complete guide: planning {n} parts from {total} pages...")
    units, problem = [], ""
    for attempt in range(2):
        retry = f"\n\nYour previous plan was rejected: {problem}. Fix that." if problem else ""
        try:
            plan = json.loads(run(executable, PLAN_PROMPT.format(n=n, total=total, units_lo=3 * n, units_hi=5 * n,
                                                                 retry=retry, files=markdown),
                                  PLAN_SCHEMA, PLANNER_MODEL, PLANNER_EFFORT))
        except (ValueError, TypeError):
            plan, problem = {}, "it was not valid JSON"
            continue
        units, problem = check_units(plan, sources)
        if units:
            break
        if attempt == 0:
            on_status(f"Complete guide: the plan was unusable ({problem}); asking once more...")
    if not units or len(units) < 2:
        on_status("Complete guide: couldn't split the material; writing it in one request instead...")
        return codex_client.generate_content(task, sources)

    parts = [units[a:b] for a, b in balance([u["size"] for u in units], min(n, MAX_WRITERS))]
    n = len(parts)
    on_status(f"Complete guide: writing {n} parts at once...")
    written = [None] * n
    with ThreadPoolExecutor(max_workers=n) as pool:
        futures = {pool.submit(run, executable, part_prompt(k, parts, plan, task, sources), PART_SCHEMA,
                               codex_client.WRITER_MODEL, codex_client.WRITER_EFFORT): k for k in range(1, n + 1)}
        for done, future in enumerate(as_completed(futures), 1):
            k = futures[future]
            try:
                data = json.loads(future.result())
                written[k - 1] = {"latex_code": str(data["latex_code"]), "takeaways": list(data.get("takeaways") or [])}
            except (ValueError, KeyError, TypeError):
                written[k - 1] = {"latex_code": "", "takeaways": []}
            on_status(f"Complete guide: {done} of {n} parts written...")

    on_status("Complete guide: checking each part...")
    for w in written:
        w["latex_code"] = re.sub(r"\\newcommand\b", r"\\providecommand", w["latex_code"].strip())

    def problem_of(k):
        code = written[k]["latex_code"]
        if not code:
            return "the response had no usable latex_code"
        static = validation.latex_problems(code)
        return "; ".join(static) if static else compile_check(code)

    with ThreadPoolExecutor(max_workers=n) as pool:
        problems = list(pool.map(problem_of, range(n)))
    for k, problem in enumerate(problems):
        if not problem:
            continue
        topic = parts[k][0]["topic"]
        first_line = next((line.strip() for line in problem.splitlines() if line.strip()), problem)[:160]
        on_status(f"Complete guide: the section on {topic} has a problem ({first_line}); "
                  "asking Codex once to fix it...")
        try:
            fixed = json.loads(run(executable, FIX_PROMPT.format(problem=problem, task_prompt=task["prompt"],
                                                                 latex_code=written[k]["latex_code"]),
                                   FIX_SCHEMA, codex_client.WRITER_MODEL, codex_client.WRITER_EFFORT))["latex_code"]
        except (ValueError, KeyError, TypeError):
            fixed = ""
        fixed = re.sub(r"\\newcommand\b", r"\\providecommand", (fixed or "").strip())
        again = "the repair had no latex_code" if not fixed else \
            ("; ".join(validation.latex_problems(fixed)) or compile_check(fixed))
        if again:
            topics = ", ".join(u["topic"] for u in parts[k][:2])
            raise CodexError("codex_failed", f"The section on {topics} could not be fixed ({again.splitlines()[0][:200]}). "
                                             "Generate again.")
        written[k]["latex_code"] = fixed

    latex = join(plan, [w["latex_code"] for w in written], [t for w in written for t in w["takeaways"]])
    bundle = {"documents": [{"role": task["expected"]["roles"][0], "day": 0, "title": _title(plan, task),
                             "latex_code": latex}], "allocation": []}
    return {"raw_text": json.dumps(bundle), "usage": {}}
