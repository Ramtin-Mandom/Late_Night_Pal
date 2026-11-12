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
Publish failures never call Gemini. Nothing is published until every document has passed:
rendering happens in a temp dir and publishing is all-or-nothing.
"""

import tempfile
import time
from datetime import date
from pathlib import Path

from . import AppError, codex_client, gemini_client, history, inputs, outputs, rendering, tasks, validation, workshops


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
    """decide_inputs(decisions) -> {source_id: "process_original" | "cancel"}; missing means cancel."""
    with tempfile.TemporaryDirectory(prefix="lnp_inputs_", ignore_cleanup_errors=True) as payload_dir:
        return _generate(request, on_progress, deps, decide_inputs, payload_dir)


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

    def ask_provider(task, sources, label):
        """One request, plus at most one visible retry for a transient network failure."""
        try:
            return timed(f"{method}_s", generate_content, task, sources)
        except AppError as e:
            if e.code != "api_network":
                raise
            progress("generating", f"Network problem while {label}; retrying once...")
            return timed(f"{method}_s", generate_content, task, sources)

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

    try:
        if method not in ("codex", "gemini"):
            raise RequestError("invalid_parameter", "Choose Codex or Gemini API in Settings.")
        tasks.validate_parameters(request.get("task_id"), request.get("parameters"))  # before any work
        if not request.get("selected_paths"):
            raise RequestError("no_inputs", "Select at least one PDF first.")
        checked = workshops.validate_paths(request["workshop_root"], request["destination"], request["selected_paths"])

        progress("preparing", "Checking LaTeX and output folder...")
        d["check_runtime"]()  # before any paid call
        outputs.check_destination(checked["destination"], checked["root"])
        caps = {"original_mime_types": []} if method == "codex" else gemini_client.get_capabilities()
        efficient = method == "codex" or bool(request.get("efficient", False))
        if efficient:
            progress("preparing", "Converting files to text locally...")
        selections = page_choices(request, checked["paths"])
        prep = inputs.prepare_inputs(checked["root"], checked["paths"], efficient, caps,
                                     page_selections=selections, payload_dir=payload_dir)
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
                                         payload_dir=payload_dir)
            if prep["decisions"]:
                raise RequestError("needs_original", "Some files still need a decision.")
        sources = prep["sources"]
        for w in prep["warnings"]:
            progress("preparing", w["message"])
        task = tasks.resolve_task(request, sources)
        subtitle = _subtitle(sources)

        progress("generating", f"{task['label']}: sending {len(sources)} file(s) to {provider}...")
        response = ask_provider(task, sources, "generating")
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
            rendered = [records[x["document_id"]] for x in bundle["documents"]]
            progress("publishing", f"Saving {len(rendered)} PDF{'s' if len(rendered) > 1 else ''}...")
            published = timed("publish_s", d["publish"], rendered, task, checked["destination"], checked["root"])
        result = {"status": "ok", **published, "warnings": prep["warnings"], "timings": timings,
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
