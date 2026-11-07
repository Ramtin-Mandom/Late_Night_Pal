"""Orchestrator: request snapshot -> validated, rendered, published PDFs.

    generate(request, on_progress) -> {"status": "ok", "output_root", "paths", "warnings"}
                                    | {"status": "error", "error": envelope}

request = {"workshop_root", "destination", "selected_paths", "task_id", "parameters", "efficient"}
Components are passed in through `deps` so each boundary can be swapped for a stub.
"""

import tempfile
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


def _subtitle(sources: list[dict]) -> str:
    names = ", ".join(s["source_id"] for s in sources)
    return f"From {names} · {date.today():%Y-%m-%d}"


def generate(request: dict, on_progress=lambda event: None, deps: dict | None = None) -> dict:
    d = {**DEFAULT_DEPS, **(deps or {})}

    def progress(stage, message):
        on_progress({"stage": stage, "message": message, "source_id": None})

    try:
        if request.get("task_id") not in tasks.TASKS:
            raise RequestError("invalid_task", f"Task '{request.get('task_id')}' is not available yet.")
        if not request.get("selected_paths"):
            raise RequestError("no_inputs", "Select at least one PDF first.")
        checked = workshops.validate_paths(request["workshop_root"], request["destination"], request["selected_paths"])

        progress("preparing", "Checking LaTeX and output folder...")
        d["check_runtime"]()  # before any paid call
        outputs.check_destination(checked["destination"], checked["root"])
        prep = inputs.prepare_inputs(checked["root"], checked["paths"], request.get("efficient", False),
                                     gemini_client.get_capabilities())
        sources = prep["sources"]
        task = tasks.resolve_task(request, sources)

        progress("generating", f"Sending {len(sources)} PDF(s) to Gemini ({gemini_client.model_name()})...")
        response = d["generate_content"](task, sources)

        progress("validating", "Checking Gemini's response...")
        bundle = validation.validate_bundle(response["raw_text"], task, sources)

        with tempfile.TemporaryDirectory(prefix="lnp_job_") as work_dir:
            progress("rendering", "Compiling PDF locally...")
            rendered = d["render_bundle"](bundle, task, work_dir, _subtitle(sources))
            progress("publishing", "Saving...")
            published = d["publish"](rendered, task, checked["destination"], checked["root"])
        return {"status": "ok", **published, "warnings": prep["warnings"]}
    except AppError as e:
        return {"status": "error", "error": e.envelope()}
    except OSError as e:
        return {"status": "error", "error": {"code": "io_error", "stage": "", "message": f"File error: {e.strerror or e}",
                                             "source_id": None, "retryable": True, "details": {}}}
