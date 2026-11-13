"""Orchestrator: request snapshot -> validated, rendered, published PDFs.

    generate(request, on_progress, deps, decide_inputs) -> {"status": "ok", "output_root", "paths", "warnings", "timings"}
                                    | {"status": "error", "error": envelope} | {"status": "cancelled"}

request = {"workshop_root", "destination", "selected_paths", "task_id", "parameters", "efficient",
           "page_selections"?: {pdf path: None | [original page numbers]}}   (missing = All pages)
A successful result also carries "generation_id" (request["generation_id"] if given, else new)
and "history_record" (history.build_record, built right after publication from the pipeline's own
source/document metadata; None plus "history_error" if it could not be built). Saving it is the
caller's job (the UI worker), so the CLI and injected-dependency runs never write history.
Selected-page PDF subsets live in one job temp folder from preparation through the last retry and
are deleted on success, failure and cancellation.
Components are passed in through `deps` so each boundary can be swapped for a stub.
Recovery is bounded and every extra Gemini request is announced in progress:
  - transient network failure: one automatic retry of the same request
  - bundle fails the JSON contract (roles, days, counts, allocation): one bundle repair
    (previous JSON + the problem, no sources)
  - a document fails its own checks (unsafe LaTeX, missing day heading/source label), does not
    compile, or compiles to too many pages: one targeted repair of that document only
    (its latex_code + the problem, no sources); documents that passed are never regenerated
  - a compiled document has lines that run past the margin (LaTeX overfull boxes): one layout fix
    that sends only those passages; if it doesn't help, the original PDF is kept with a warning
Publish failures never call Gemini. Nothing is published until every document has passed:
rendering happens in a temp dir and publishing is all-or-nothing.
"""

import tempfile
import time
from datetime import date
from pathlib import Path

from . import (AppError, codex_client, costs, gemini_client, history, inputs, outputs, parallel_guide, rendering,
               tasks, validation, workshop_cache, workshops)


class RequestError(AppError):
    stage = "validating"


DEFAULT_DEPS = {
    "check_runtime": rendering.check_runtime,
    "render_bundle": rendering.render_bundle,
    "publish": outputs.publish,
}

DOCUMENT_REPAIR_PROMPT = """One document of your previous response cannot be used: {problem}

Return JSON {{"latex_code": "..."}} with the complete corrected body of this document only.
Fix that problem and keep the content, structure and language otherwise. Follow the task and
LaTeX rules below exactly.

Document: role {role}, day {day}, title {title!r}

{task_prompt}

Current latex_code:
{latex_code}"""

LAYOUT_REPAIR_PROMPT = """Some lines of one document of your previous response run past the right margin of
the compiled PDF. Rewrite only the numbered snippets below so every line fits the text width. Return
JSON {{"snippets": [{{"id": 1, "latex": "..."}}]}} with one entry per snippet; each "latex" replaces
that whole snippet. Keep the content and meaning, and keep every \\begin and \\end that the snippet has.
Typical fixes: split a long list of numbers in inline math into short $...$ pieces or a small table;
break a long display equation with aligned or multline; narrow a wide table (fewer columns, p{{}}
columns, \\small); scale down a wide TikZ picture. Follow the task's LaTeX rules below.

Document: role {role}, day {day}, title {title!r}

{task_prompt}

Snippets (points = how far the widest line sticks out):
{snippets}"""

LAYOUT_SCHEMA = {"type": "object", "required": ["snippets"], "properties": {"snippets": {
    "type": "array", "items": {"type": "object", "required": ["id", "latex"],
                               "properties": {"id": {"type": "integer"}, "latex": {"type": "string"}}}}}}
SNIPPET_MAX_LINES = 30  # an overflow is widened to its paragraph (blank-line block) up to this size


def snippet_spans(lines: list[str], overflows: list[dict]) -> list[tuple[int, int, float]]:
    """Overflowing body line ranges widened to their blank-line-separated block, merged:
    [(first, last, points)], 1-based and inclusive."""
    spans = []
    for o in sorted(overflows, key=lambda o: o["first"]):
        a, b = o["first"], o["last"]
        while b > a and not lines[b - 1].strip():
            b -= 1
        s, e = a, b
        while s > 1 and lines[s - 2].strip():
            s -= 1
        while e < len(lines) and lines[e].strip():
            e += 1
        if e - s + 1 > SNIPPET_MAX_LINES:
            s, e = a, b
        if spans and s <= spans[-1][1]:
            spans[-1] = (min(s, spans[-1][0]), max(e, spans[-1][1]), max(o["points"], spans[-1][2]))
        else:
            spans.append((s, e, o["points"]))
    return spans


def _overflow_points(record: dict) -> float:
    return sum(o["points"] for o in record.get("overflows") or [])


REPAIR_PROMPT = """Your previous JSON response could not be used: {problem}.
Return the complete corrected JSON for the same task, fixing that problem and keeping all other
valid content. Follow the original task exactly:

{task_prompt}

Previous response:
{raw}"""


def _subtitle(sources: list[dict]) -> str:
    names = ", ".join(s["source_id"] for s in sources)
    return f"From {names} · {date.today():%Y-%m-%d}"


def page_choices(request: dict, paths) -> dict:
    """{canonical path: choice} for the selected paths only; a missing field means All pages."""
    wanted = {Path(p) for p in paths}
    out = {}
    for k, v in (request.get("page_selections") or {}).items():
        try:
            key = Path(k).resolve()
        except OSError:
            continue
        if key in wanted:
            out[key] = list(v) if isinstance(v, (list, tuple)) else v
    return out


def generate(request: dict, on_progress=lambda event: None, deps: dict | None = None,
             decide_inputs=None) -> dict:
    """decide_inputs(decisions) -> {source_id: "process_original" | "cancel"}; missing means cancel.
    Every result also carries "usage" (costs.summarize: time, Codex calls, tokens, estimated cost) and
    "run_summary", its one-line description for the status line."""
    codex_client.take_usage()  # drop anything left over from an earlier job
    start = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="lnp_inputs_", ignore_cleanup_errors=True) as payload_dir:
        result = _generate(request, on_progress, deps, decide_inputs, payload_dir)
    result["usage"] = costs.summarize(codex_client.take_usage(), time.perf_counter() - start)
    result["run_summary"] = costs.describe(result["usage"],
                                           "Gemini" if request.get("provider") == "gemini" else "Codex")
    return result


def _generate(request, on_progress, deps, decide_inputs, payload_dir) -> dict:
    d = {**DEFAULT_DEPS, **(deps or {})}
    method = request.get("provider", "codex")
    provider = "Codex" if method == "codex" else "Gemini"
    client = codex_client if method == "codex" else gemini_client
    generate_content = d.get("generate_content", client.generate_content)
    generation_id = request.get("generation_id") or history.new_generation_id()
    timings = {}

    def progress(stage, message):
        on_progress({"stage": stage, "message": message, "source_id": None})

    def timed(key, fn, *args):
        start = time.perf_counter()
        try:
            return fn(*args)
        finally:
            timings[key] = round(timings.get(key, 0) + time.perf_counter() - start, 1)

    def ask_provider(task, sources, label, fn=None):
        """One request, plus at most one visible retry for a transient network failure."""
        fn = fn or generate_content
        try:
            return timed(f"{method}_s", fn, task, sources)
        except AppError as e:
            if e.code != "api_network":
                raise
            progress("generating", f"Network problem while {label}; retrying once...")
            return timed(f"{method}_s", fn, task, sources)

    def prepared_text(sources, persist, root):
        """Codex: read scanned pages now (Luna), so the text is final before any writer call; then, with Cache
        checked, publish each PDF's newly prepared pages to <root>/cache. A failed save never fails the job."""
        stubbed = "generate_content" in (deps or {})  # tests that stub the provider never read scans
        if method == "codex" and not stubbed and any(s.get("image_parts") for s in sources):
            n = sum(len(s["image_parts"]) for s in sources)
            progress("preparing", f"Reading {n} scanned page{'s' * (n != 1)} with Codex...")
            executable = codex_client.find_cli()
            if not executable:
                raise codex_client.CodexError("codex_missing", "Install the Codex CLI on PATH, run codex login, "
                                                               "then restart Late Night Pal.")
            sources = timed(f"{method}_s", codex_client.read_scans, executable, sources, persist)
        if not persist:
            return sources
        for s in sources:
            pending = {im["page"] for im in s.get("image_parts") or []}  # never cache an unread scan
            units = {u.get("number"): u["text"] for u in s.get("text_parts") or []}
            done = set(s.get("transcribed_pages") or [])
            fresh = {n: {"text": units[n], "kind": "transcribed" if n in done else "text"}
                     for n in s.get("fresh_pages") or {} if n not in pending and n in units}
            if not fresh:
                continue
            try:
                md = workshop_cache.publish(root, s["source_id"], s["fingerprint"],
                                            s["page_count"], fresh)
                progress("preparing", f"Saved {len(fresh)} page(s) of {s['source_id']} to "
                                      f"{Path(md).relative_to(Path(root)).as_posix()}.")
            except OSError as e:
                progress("preparing", f"Couldn't save {s['source_id']} to the workshop cache "
                                      f"({e.strerror or e}); continuing without it.")
        return sources

    def first_request(task, sources):
        """Complete guide: parallel Codex calls (parallel_guide); every other task, and every repair: one request."""
        if task.get("parallel") and "generate_content" not in (deps or {}):
            return ask_provider(task, sources, "generating", lambda t, s: parallel_guide.generate(
                t, s, lambda message: progress("generating", message)))
        return ask_provider(task, sources, "generating")

    def validated(task, sources, response):
        """Validate; on failure send one visible schema-repair request, then give up."""
        try:
            return validation.validate_bundle(response["raw_text"], task, sources)
        except validation.ValidationError as e:
            problem = e.message.split(": ", 1)[-1]
            progress("generating", f"{provider}'s response was unusable ({problem}); asking {provider} once to fix it...")
            repair_task = dict(task, prompt=REPAIR_PROMPT.format(problem=problem, task_prompt=task["prompt"],
                                                                 raw=(response["raw_text"] or "")[:200_000]))
            repaired = ask_provider(repair_task, [], "repairing the response")
            progress("validating", "Checking the repaired response...")
            try:
                return validation.validate_bundle(repaired["raw_text"], task, sources)
            except validation.ValidationError as e2:
                e2.message += " (also after one repair attempt)"
                raise e2

    def repair_document(doc, failure, task, bundle, sources, work_dir, subtitle, names):
        """The one targeted repair for a failed document: ask, recheck, recompile; else fail the job."""
        label = names[doc["document_id"]]
        progress("generating", f"{failure['message']}; asking {provider} once to fix that document...")
        repair_task = dict(task, response_schema=tasks.REPAIR_SCHEMA, prompt=DOCUMENT_REPAIR_PROMPT.format(
            problem=failure["problem"], role=doc["role"], day=doc["day"] or 0, title=doc["title"],
            task_prompt=task["prompt"], latex_code=doc["latex_code"]))
        response = ask_provider(repair_task, [], f"repairing {label}")
        fixed = dict(doc, latex_code=validation.parse_document_repair(response["raw_text"]))
        problems = validation.document_problems(fixed, task, sources)
        if problems:
            raise validation.ValidationError(
                "invalid_response", f"{label} is unusable: {'; '.join(problems)} (also after one repair attempt)")
        doc.update(fixed)
        progress("rendering", f"Compiling repaired {label}...")
        result = timed("render_s", d["render_bundle"], dict(bundle, documents=[doc]), task, work_dir, subtitle,
                       None, names)
        if result["records"]:
            return result["records"][0]
        again = result["failures"][doc["document_id"]]
        log = f"LaTeX log: {again['log']}" if again.get("log") else ""
        raise rendering.RenderError(again["code"], f"{again['message']} (also after one repair attempt).",
                                    "\n".join(x for x in (again["problem"], log) if x), source_id=label)

    def fix_layout(doc, record, task, bundle, sources, work_dir, subtitle, names):
        """One small request for the snippets that run past the margin. Returns (record, warning or None):
        the fixed PDF when it compiles with less overflow, else the original PDF and a warning."""
        label = names[doc["document_id"]]
        lines = doc["latex_code"].splitlines()
        spans = snippet_spans(lines, record["overflows"])
        n = len(spans)
        progress("generating", f"{label}: {n} passage{'s run' if n != 1 else ' runs'} past the page margin; "
                               f"asking {provider} once to fix {'them' if n != 1 else 'it'}...")
        listing = "\n\n".join(f"--- snippet {i} ({pts} pt too wide) ---\n" + "\n".join(lines[a - 1:b])
                              for i, (a, b, pts) in enumerate(spans, 1))
        repair_task = dict(task, response_schema=LAYOUT_SCHEMA, prompt=LAYOUT_REPAIR_PROMPT.format(
            role=doc["role"], day=doc["day"] or 0, title=doc["title"], task_prompt=task["prompt"], snippets=listing))
        kept = (record, {"code": "layout_overflow", "source_id": None,
                         "message": f"{label}: {n} passage{'s' * (n != 1)} may run past the right margin."})
        try:
            replacements = validation.parse_layout_repair(
                ask_provider(repair_task, [], f"fixing the layout of {label}")["raw_text"], n)
        except AppError:
            return kept  # the PDF is still usable: never fail the job over layout
        for (a, b, _), text in sorted(zip(spans, replacements), reverse=True):
            lines[a - 1:b] = text.splitlines()
        fixed = dict(doc, latex_code="\n".join(lines))
        if validation.document_problems(fixed, task, sources):
            return kept
        before = Path(record["temp_path"]).with_name(f"{doc['document_id']}-before-layout-fix.pdf")
        Path(record["temp_path"]).replace(before)  # the recompile writes the same name
        kept = (dict(record, temp_path=str(before)), kept[1])
        progress("rendering", f"Compiling {label} again...")
        result = timed("render_s", d["render_bundle"], dict(bundle, documents=[fixed]), task, work_dir, subtitle,
                       None, names)
        new = result["records"][0] if result["records"] else None
        if new is None or _overflow_points(new) >= _overflow_points(record):
            return kept
        doc.update(fixed)
        left = len(snippet_spans(fixed["latex_code"].splitlines(), new["overflows"]))
        return new, (dict(kept[1], message=f"{label}: {left} passage{'s' * (left != 1)} may still run past the "
                                            f"right margin.") if left else None)

    try:
        if method not in ("codex", "gemini"):
            raise RequestError("invalid_parameter", "Choose Codex or Gemini API in Settings.")
        tasks.validate_parameters(request.get("task_id"), request.get("parameters"))  # before any work
        if tasks.TASKS[request["task_id"]].get("parallel") and method != "codex":
            raise RequestError("invalid_parameter", "Complete guide is written by Codex. Choose Settings → "
                                                    "Generation method → Codex, or pick Notes.")
        if not request.get("selected_paths"):
            raise RequestError("no_inputs", "Select at least one PDF first.")
        checked = workshops.validate_paths(request["workshop_root"], request["destination"], request["selected_paths"])

        progress("preparing", "Checking LaTeX and output folder...")
        d["check_runtime"]()  # before any paid call
        outputs.check_destination(checked["destination"], checked["root"])
        caps = codex_client.CAPABILITIES if method == "codex" else gemini_client.get_capabilities()
        efficient = method == "codex" or bool(request.get("efficient", False))
        if efficient:
            progress("preparing", "Converting files to text locally...")
        selections = page_choices(request, checked["paths"])
        persist = bool(request.get("cache", False))  # Make me's Cache box: may this job write caches?
        prep = inputs.prepare_inputs(checked["root"], checked["paths"], efficient, caps,
                                     page_selections=selections, payload_dir=payload_dir,
                                     cache_root=checked["root"], persist=persist)
        if prep["decisions"]:
            # Scan / no-text files: the student must choose before anything is sent.
            progress("awaiting_input", "Waiting for your choice about " +
                     ", ".join(x["source_id"] for x in prep["decisions"]) + "...")
            choices = decide_inputs(prep["decisions"]) if decide_inputs else {}
            pending = [x["source_id"] for x in prep["decisions"]]
            if any(choices.get(sid) != "process_original" for sid in pending):
                return {"status": "cancelled", "timings": timings}
            prep = inputs.prepare_inputs(checked["root"], checked["paths"], efficient, caps,
                                         original_overrides=frozenset(pending), page_selections=selections,
                                         payload_dir=payload_dir, cache_root=checked["root"], persist=persist)
            if prep["decisions"]:
                raise RequestError("needs_original", "Some files still need a decision.")
        sources = prep["sources"]
        for w in prep["warnings"]:
            progress("preparing", w["message"])
        sources = prepared_text(sources, persist, checked["root"])
        task = tasks.resolve_task(request, sources)
        subtitle = _subtitle(sources)

        progress("generating", f"{task['label']}: sending {len(sources)} file(s) to {provider}...")
        response = first_request(task, sources)
        progress("validating", f"Checking {provider}'s response...")
        bundle = validated(task, sources, response)
        names = outputs.relative_output_paths(task, bundle["documents"])

        def on_document(i, n, document_id):
            progress("rendering", f"Compiling PDF {i}/{n}: {names[document_id]}")

        with tempfile.TemporaryDirectory(prefix="lnp_job_") as work_dir:
            n = len(bundle["documents"])
            failures = {}
            for doc in bundle["documents"]:
                problems = validation.document_problems(doc, task, sources)
                if problems:
                    failures[doc["document_id"]] = {"code": "invalid_response", "message": names[doc["document_id"]]
                                                    + " is unusable", "problem": "; ".join(problems), "log": ""}
            progress("rendering", f"Compiling {n} PDF{'s' if n > 1 else ''} locally...")
            ready = dict(bundle, documents=[x for x in bundle["documents"] if x["document_id"] not in failures])
            result = timed("render_s", d["render_bundle"], ready, task, work_dir, subtitle, on_document, names)
            records = {r["document_id"]: r for r in result["records"]}
            failures.update(result["failures"])
            for doc in [x for x in bundle["documents"] if x["document_id"] in failures]:
                records[doc["document_id"]] = repair_document(doc, failures[doc["document_id"]], task, bundle,
                                                              sources, work_dir, subtitle, names)
            warnings = list(prep["warnings"])
            for doc in bundle["documents"]:
                if records[doc["document_id"]].get("overflows"):
                    records[doc["document_id"]], warning = fix_layout(
                        doc, records[doc["document_id"]], task, bundle, sources, work_dir, subtitle, names)
                    if warning:
                        warnings.append(warning)
                        progress("rendering", warning["message"])
            rendered = [records[x["document_id"]] for x in bundle["documents"]]
            progress("publishing", f"Saving {len(rendered)} PDF{'s' if len(rendered) > 1 else ''}...")
            published = timed("publish_s", d["publish"], rendered, task, checked["destination"], checked["root"])
        result = {"status": "ok", **published, "warnings": warnings, "timings": timings,
                  "generation_id": generation_id, "history_record": None,
                  "documents": [{"document_id": r["document_id"], "page_count": r.get("page_count"),
                                 "render_s": r.get("seconds")} for r in rendered]}
        try:  # the PDFs are published: nothing here may turn success into an error
            result["history_record"] = history.build_record(generation_id, checked["root"], checked["destination"],
                                                            task, efficient, sources, rendered, published)
        except Exception as e:
            result["history_error"] = f"The history entry could not be prepared ({type(e).__name__})."
        return result
    except AppError as e:
        return {"status": "error", "error": e.envelope(), "timings": timings}
    except OSError as e:
        return {"status": "error", "timings": timings,
                "error": {"code": "io_error", "stage": "", "message": f"File error: {e.strerror or e}",
                          "source_id": None, "retryable": True, "details": {}}}
