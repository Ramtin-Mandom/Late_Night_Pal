"""Orchestrator: request snapshot -> validated, rendered, published PDFs.

    generate(request, on_progress, deps, decide_inputs) -> {"status": "ok", "output_root", "paths", "warnings", "timings"}
                                    | {"status": "error", "error": envelope} | {"status": "cancelled"}

request = {"workshop_root", "destination", "selected_paths", "task_id", "parameters", "efficient"}
Components are passed in through `deps` so each boundary can be swapped for a stub.
Recovery is bounded and every extra Gemini request is announced in progress:
  - transient network failure: one automatic retry of the same request
  - response fails validation: one schema-repair request (previous JSON + the problem, no sources)
  - cheat sheet over one page: one condensation request
Local compile/publish failures never trigger a Gemini call; they fail with the document named,
and nothing is published (rendering happens in a temp dir, publishing is all-or-nothing).
"""

import json
import tempfile
import time
from datetime import date

from . import AppError, gemini_client, inputs, outputs, rendering, tasks, validation, workshops


class RequestError(AppError):
    stage = "validating"


DEFAULT_DEPS = {
    "check_runtime": rendering.check_runtime,
    "generate_content": gemini_client.generate_content,
    "render_bundle": rendering.render_bundle,
    "publish": outputs.publish,
}

CONDENSE_PROMPT = """The cheat sheet below rendered to {pages} pages but must fit on exactly one page.
Rewrite it shorter: keep the most exam-relevant definitions, formulas and distinctions, cut everything
else, and use terse list items. Aim for about 60% of the current length. Keep the same JSON format
(one document with role `cheat-sheet`, day 0, empty allocation).

Current cheat sheet JSON:
{bundle}"""

REPAIR_PROMPT = """Your previous JSON response could not be used: {problem}.
Return the complete corrected JSON for the same task, fixing that problem and keeping all other
valid content. Follow the original task exactly:

{task_prompt}

Previous response:
{raw}"""


def _subtitle(sources: list[dict]) -> str:
    names = ", ".join(s["source_id"] for s in sources)
    return f"From {names} · {date.today():%Y-%m-%d}"


def generate(request: dict, on_progress=lambda event: None, deps: dict | None = None,
             decide_inputs=None) -> dict:
    """decide_inputs(decisions) -> {source_id: "process_original" | "cancel"}; missing means cancel."""
    d = {**DEFAULT_DEPS, **(deps or {})}
    timings = {}

    def progress(stage, message):
        on_progress({"stage": stage, "message": message, "source_id": None})

    def timed(key, fn, *args):
        start = time.perf_counter()
        try:
            return fn(*args)
        finally:
            timings[key] = round(timings.get(key, 0) + time.perf_counter() - start, 1)

    def ask_gemini(task, sources, label):
        """One request, plus at most one visible retry for a transient network failure."""
        try:
            return timed("gemini_s", d["generate_content"], task, sources)
        except gemini_client.GeminiError as e:
            if e.code != "api_network":
                raise
            progress("generating", f"Network problem while {label}; retrying once...")
            return timed("gemini_s", d["generate_content"], task, sources)

    def validated(task, sources, response):
        """Validate; on failure send one visible schema-repair request, then give up."""
        try:
            return validation.validate_bundle(response["raw_text"], task, sources)
        except validation.ValidationError as e:
            problem = e.message.split(": ", 1)[-1]
            progress("generating", f"Gemini's response was unusable ({problem}); asking Gemini once to fix it...")
            repair_task = dict(task, prompt=REPAIR_PROMPT.format(problem=problem, task_prompt=task["prompt"],
                                                                 raw=(response["raw_text"] or "")[:200_000]))
            repaired = ask_gemini(repair_task, [], "repairing the response")
            progress("validating", "Checking the repaired response...")
            try:
                return validation.validate_bundle(repaired["raw_text"], task, sources)
            except validation.ValidationError as e2:
                e2.message += " (also after one repair attempt)"
                raise e2

    try:
        tasks.validate_parameters(request.get("task_id"), request.get("parameters"))  # before any work
        if not request.get("selected_paths"):
            raise RequestError("no_inputs", "Select at least one PDF first.")
        checked = workshops.validate_paths(request["workshop_root"], request["destination"], request["selected_paths"])

        progress("preparing", "Checking LaTeX and output folder...")
        d["check_runtime"]()  # before any paid call
        outputs.check_destination(checked["destination"], checked["root"])
        caps = gemini_client.get_capabilities()
        efficient = bool(request.get("efficient", False))
        if efficient:
            progress("preparing", "Converting files to text locally...")
        prep = inputs.prepare_inputs(checked["root"], checked["paths"], efficient, caps)
        if prep["decisions"]:
            # Scan / no-text files: the student must choose before anything is sent.
            progress("awaiting_input", "Waiting for your choice about " +
                     ", ".join(x["source_id"] for x in prep["decisions"]) + "...")
            choices = decide_inputs(prep["decisions"]) if decide_inputs else {}
            pending = [x["source_id"] for x in prep["decisions"]]
            if any(choices.get(sid) != "process_original" for sid in pending):
                return {"status": "cancelled", "timings": timings}
            prep = inputs.prepare_inputs(checked["root"], checked["paths"], efficient, caps,
                                         original_overrides=frozenset(pending))
            if prep["decisions"]:
                raise RequestError("needs_original", "Some files still need a decision.")
        sources = prep["sources"]
        for w in prep["warnings"]:
            progress("preparing", w["message"])
        task = tasks.resolve_task(request, sources)
        subtitle = _subtitle(sources)

        progress("generating", f"{task['label']}: sending {len(sources)} file(s) to Gemini "
                               f"({gemini_client.model_name()})...")
        response = ask_gemini(task, sources, "generating")
        progress("validating", "Checking Gemini's response...")
        bundle = validated(task, sources, response)
        names = outputs.relative_output_paths(task, bundle["documents"])

        def on_document(i, n, document_id):
            progress("rendering", f"Compiling PDF {i}/{n}: {names[document_id]}")

        with tempfile.TemporaryDirectory(prefix="lnp_job_") as work_dir:
            n = len(bundle["documents"])
            progress("rendering", f"Compiling {n} PDF{'s' if n > 1 else ''} locally...")
            try:
                rendered = timed("render_s", d["render_bundle"], bundle, task, work_dir, subtitle, on_document, names)
            except rendering.RenderError as e:
                if e.code != "page_limit_exceeded":
                    raise
                progress("generating", "Cheat sheet is longer than one page; asking Gemini to condense it once...")
                doc = bundle["documents"][0]
                condensed_task = dict(task, prompt=CONDENSE_PROMPT.format(
                    pages=e.details, bundle=json.dumps({"documents": [{**doc, "day": 0}], "allocation": []})))
                response = ask_gemini(condensed_task, [], "condensing the cheat sheet")
                bundle = validation.validate_bundle(response["raw_text"], task, sources)  # no further repair
                progress("rendering", "Compiling condensed cheat sheet...")
                rendered = timed("render_s", d["render_bundle"], bundle, task, work_dir, subtitle, on_document, names)
            progress("publishing", f"Saving {len(rendered)} PDF{'s' if len(rendered) > 1 else ''}...")
            published = timed("publish_s", d["publish"], rendered, task, checked["destination"], checked["root"])
        return {"status": "ok", **published, "warnings": prep["warnings"], "timings": timings,
                "documents": [{"document_id": r["document_id"], "page_count": r.get("page_count"),
                               "render_s": r.get("seconds")} for r in rendered]}
    except AppError as e:
        return {"status": "error", "error": e.envelope(), "timings": timings}
    except OSError as e:
        return {"status": "error", "timings": timings,
                "error": {"code": "io_error", "stage": "", "message": f"File error: {e.strerror or e}",
                          "source_id": None, "retryable": True, "details": {}}}
