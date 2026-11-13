"""Generate a structured study document with the user's locally signed-in Codex CLI.

    generate_content(task, sources) -> {"raw_text", "usage"}

Two steps when a source has scanned pages (image_parts from inputs.prepare_inputs):
  1. read_scans: READER_MODEL transcribes each page image to Markdown (LaTeX math), one page per
     call (a batch can merge pages that run on, shifting their numbers) and READER_WORKERS calls at
     once. An empty answer is retried once. Only a checked page is cached, in
     %LOCALAPPDATA%\\late_night_workshop\\transcriptions by file fingerprint + page + model, so the
     next job on the same lecture skips this step.
  2. WRITER_MODEL gets text only: the transcriptions replace those pages' text, page numbers kept.
"""
import json
import os
import shutil
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import AppError
from .gemini_client import text_source_item
from .workshops import app_data_dir


CAPABILITIES = {"original_mime_types": [], "scan_images": True}  # no PDF input; scans go as page images
READER_MODEL, READER_EFFORT = "gpt-6-luna", "medium"     # scanned page images -> Markdown
WRITER_MODEL, WRITER_EFFORT = "gpt-6.1-terra", "medium"  # text -> study documents
READER_WORKERS = 6  # transcription calls at once (one page each)
TRANSCRIPTION_VERSION = 2  # bump when READER_PROMPT changes, so old cached pages are not reused (v1: batched)

READER_PROMPT = """Transcribe the attached image, page {page} of {source}, into Markdown.
Copy the page faithfully, in reading order: headings, lists, definitions, theorems, proofs, examples, tables.
It may start or end mid-sentence; keep it exactly that way.
Write all mathematics in LaTeX ($...$ inline, $$...$$ display). Leave out crossed-out writing.
For a diagram or figure write one line: [Figure: what it shows, with its labels].
Write [illegible] for anything you cannot read. Do not summarize, explain, correct or add anything.
For a blank page return an empty string."""

READER_SCHEMA = {"type": "object", "required": ["markdown"], "properties": {"markdown": {"type": "string"}}}


class CodexError(AppError):
    stage = "generating"


def strict_schema(node):
    """Codex structured output requires closed objects, including nested array items."""
    if not isinstance(node, dict):
        return node
    result = {key: strict_schema(value) for key, value in node.items()}
    if node.get("type") == "object":
        result["additionalProperties"] = False
    return result


def find_cli():
    executable = shutil.which("codex")
    if executable or os.name != "nt" or not os.environ.get("LOCALAPPDATA"):
        return executable
    # Explorer-launched apps may not inherit the Codex desktop app's private PATH.
    directory = Path(os.environ["LOCALAPPDATA"], "OpenAI", "Codex", "bin")
    candidates = directory.glob("*/codex.exe")
    return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


_usage, _usage_lock = [], threading.Lock()


def take_usage() -> list[dict]:
    """Token usage of every Codex call since the last take: [{model, input, cached, output}]; clears it.
    Generation takes it at the start and end of a job (one job runs at a time)."""
    with _usage_lock:
        records, _usage[:] = list(_usage), []
    return records


def _record_usage(model: str, stdout: bytes) -> None:
    """The --json event stream ends each turn with turn.completed {usage}; keep its token counts."""
    for line in (stdout or b"").decode("utf-8", "replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "turn.completed":
            u = event.get("usage") or {}
            with _usage_lock:
                _usage.append({"model": model, "input": int(u.get("input_tokens") or 0),
                               "cached": int(u.get("cached_input_tokens") or 0),
                               "output": int(u.get("output_tokens") or 0)})


def run_codex(executable, prompt, schema, model, effort, images=()) -> str:
    """One fresh read-only `codex exec` with a JSON schema; returns its raw JSON answer.
    Its --json events give the call's token usage, recorded for take_usage()."""
    with tempfile.TemporaryDirectory(prefix="lnp_codex_") as folder:
        schema_file = Path(folder, "schema.json")
        output = Path(folder, "answer.json")
        schema_file.write_text(json.dumps(strict_schema(schema)), encoding="utf-8")
        command = [executable, "-a", "never", "exec", "--json", "--sandbox", "read-only", "--ephemeral",
                   "-c", 'forced_login_method="chatgpt"', "--skip-git-repo-check", "--ignore-user-config",
                   "--disable", "shell_tool", "-c", 'web_search="disabled"',
                   "-m", model, "-c", f'model_reasoning_effort="{effort}"']
        for image in images:  # each before a flag, so the variadic --image never swallows "-"
            command += ["--image", str(Path(image).resolve())]  # Codex runs in its own folder: relative paths miss
        command += ["--output-schema", str(schema_file), "-o", str(output), "-"]
        try:
            run = subprocess.run(command, cwd=folder, input=prompt.encode("utf-8"),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=900,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            raise CodexError("codex_timeout", "Codex timed out. Try fewer files or fewer days.") from None
        _record_usage(model, run.stdout)
        if run.returncode:
            diagnostic = run.stderr.lower()
            if any(word in diagnostic for word in (b"401", b"unauthorized", b"not logged in", b"sign in")):
                raise CodexError("codex_auth", "Sign in to the Codex CLI with codex login, then generate again.")
            if any(word in diagnostic for word in (b"429", b"usage limit", b"rate limit")):
                raise CodexError("api_quota", "Codex reached its usage limit. Retry when your allowance resets.")
            if b"model" in diagnostic and any(w in diagnostic for w in (b"not found", b"not supported", b"unknown")):
                raise CodexError("codex_failed", f"Codex can't use {model} with this sign-in. Update the Codex CLI.")
            raise CodexError("codex_failed", "Codex failed. Check codex login status, CLI version and your connection.")
        if not output.is_file():
            raise CodexError("codex_failed", "Codex finished without returning a document.")
        return output.read_text(encoding="utf-8")


def _cache_file(source, page) -> Path:
    digest = source["fingerprint"].split(":", 1)[-1]
    return app_data_dir() / "transcriptions" / f"{digest}-p{page}-{READER_MODEL}-v{TRANSCRIPTION_VERSION}.json"


def _cached(source, page):
    try:
        return json.loads(_cache_file(source, page).read_text(encoding="utf-8"))["markdown"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _transcribe(executable, source, image, persist: bool = True) -> str:
    """Markdown of one scanned page; an empty or unreadable answer is asked once more. Cached only when checked,
    and only with persist (Make me's Cache box); unchecked jobs never write a new transcription."""
    prompt = READER_PROMPT.format(page=image["page"], source=source["source_id"])
    text = None
    for _ in range(2):
        raw = run_codex(executable, prompt, READER_SCHEMA, READER_MODEL, READER_EFFORT, [image["path"]])
        try:
            text = json.loads(raw)["markdown"].strip()
        except (ValueError, KeyError, TypeError, AttributeError):
            text = None
        if text:
            break
    if text is None:
        raise CodexError("codex_failed", f"Codex returned an unreadable transcription of page {image['page']} of "
                         f"{source['source_id']}. Generate again.", source_id=source["source_id"])
    text = text or "[no readable content]"  # a blank page, twice
    if not persist:
        return text
    try:
        cache = _cache_file(source, image["page"])
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"model": READER_MODEL, "markdown": text}), encoding="utf-8")
    except OSError:
        pass  # the cache is an optimization only
    return text


def read_scans(executable, sources, persist: bool = True) -> list[dict]:
    """Sources with their scanned pages as transcribed text and no image_parts (new dicts).
    transcribed_pages keeps pages that came transcribed from the workshop cache and adds the ones read now."""
    pages = {i: {} for i in range(len(sources))}
    todo = []
    for i, source in enumerate(sources):
        for im in source.get("image_parts") or []:
            text = _cached(source, im["page"])
            if text is None:
                todo.append((i, im))
            else:
                pages[i][im["page"]] = text
    if todo:
        with ThreadPoolExecutor(max_workers=min(READER_WORKERS, len(todo))) as pool:
            futures = [(i, im["page"], pool.submit(_transcribe, executable, sources[i], im, persist)) for i, im in todo]
            for i, page, future in futures:
                pages[i][page] = future.result()
    result = []
    for i, source in enumerate(sources):
        if not pages[i]:
            result.append(source)
            continue
        units, seen = [], set()
        for u in source["text_parts"]:
            if u.get("unit") == "page" and u.get("number") in pages[i]:
                seen.add(u["number"])
                kept = u["text"].strip()
                u = dict(u, text=(kept + "\n\n" if kept else "") + "(transcribed from the page image)\n"
                         + pages[i][u["number"]])
            units.append(u)
        units += [{"unit": "page", "number": n, "text": "(transcribed from the page image)\n" + t}
                  for n, t in sorted(pages[i].items()) if n not in seen]
        units.sort(key=lambda u: u.get("number") or 0)
        result.append(dict(source, text_parts=units, image_parts=[],
                           transcribed_pages=sorted(set(source.get("transcribed_pages") or []) | set(pages[i]))))
    return result


def generate_content(task, sources):
    executable = find_cli()
    if not executable:
        raise CodexError("codex_missing", "Install the Codex CLI on PATH, run codex login, then restart Late Night Pal.")
    sources = read_scans(executable, sources)
    prompt = "\n\n".join([text_source_item(i, s) for i, s in enumerate(sources, 1)] + [task["prompt"]])
    raw = run_codex(executable, prompt, task["response_schema"], WRITER_MODEL, WRITER_EFFORT)
    return {"raw_text": raw, "usage": {}}
