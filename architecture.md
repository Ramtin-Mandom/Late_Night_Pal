# Architecture

Implemented through M7 (packaged as a Windows one-folder build): workshop shell, shared pipeline, all eight tasks with their output layouts, Efficient (local text conversion) with caching and scan handling, and bounded recovery with actionable errors. Package root: `src/late_night_workshop/` (internal id; the app's display name is Late Night Pal). The proposed full plan is in `components.md` and `PROJECT_MAP_AND_MILESTONES.md`; this file lists only what exists.

Pipeline order (`generation.generate`): validate parameters and paths → LaTeX + destination preflight → prepare inputs (original or local text; scan decisions go back to the UI, and Cancel ends here with zero API calls) → resolve task → **one** Gemini request → validate the whole bundle → render every PDF in a temp dir → publish (all or nothing). The only extra Gemini requests, each announced in the status: one retry after a network error, one schema repair after a failed validation, and one cheat-sheet condensation. Compile and publish failures never call Gemini.

## Desktop UI and entry point

Responsibility and entry point: start the app, show workshops, browse and select, collect task parameters, submit a request snapshot. Open `__main__.py` · `main()` first.

| File or symbol | What it does |
| --- | --- |
| `__main__.py` · `main()` | `python -m late_night_workshop` or `Late Night Pal.exe`. `--check` verifies every prompt, style fragment and template, LaTeX, whether a Gemini key is present (never printing it) and `frozen build`; `--extract FILE` prints a local conversion; `_console_streams()` attaches the windowed exe to its parent console for these modes; `--summarize FILE` runs a Standard Summary with the PDF's folder as workshop and destination → `summary.pdf` (suffixed if taken) |
| `ui.py` · `build_request(state, task_id, parameters)` | Qt-free snapshot `{workshop_root, destination, selected_paths, task_id, parameters, efficient}` taken at Generate |
| `ui.py` · `make_me_status(state)` | Qt-free Generate eligibility `{ok, blockers, message}` from `inputs.generation_blockers()`: missing entries, folders, unsupported types and unreadable files block Generate and are named |
| `ui.py` · `Window` start page | Welcome, Recent Workshops, Open/Create Workshop; a missing recent offers Open another folder / Remove |
| `ui.py` · `Window` workshop page | Up, **Refresh** (`workshops.prune`, reports what it dropped) and the folder browser. Each row: a checkbox selects/deselects a file or folder; the name opens a folder or toggles a file. Selected entries are blue. **Selected Inputs (n: files, folders)** lists `[folder]`/`[missing]` + relative path with a **Remove** button (deselect only, works off-screen and for missing entries). **Organize** / **Make me** below it (default Make me; switching keeps selection and settings). Organize: Delete, Rip, Wrap, Copy, Paste, Super Wrap, disabled until P2-M3, with Rip's helper text. Make me: **Output type** (Study plan / Single file) → **Task** list from `tasks.tasks_for()`. Single file shows **Language style**; Study plan shows **Days** (any positive whole number) and **Folder name** (placeholder = default folder). Both show **Efficient** (default off) with `EFFICIENT_NOTE`, a red eligibility note, then Generate. `current_parameters()` returns the visible task's settings |
| `ui.py` · `Worker`, `job_finished` | Runs `generate` on a `QThread`; Generate disabled until done; `quit()` before `wait()`. `Worker.decide()` emits `decision_needed` and blocks on a `threading.Event`; `Window.answer_decisions()` → `choose_for()` shows the **Process original / Cancel** dialog on the UI thread. A cancelled result shows "Cancelled. Nothing was sent…" and re-enables Generate |
| `ui.py` · `describe_progress`, `describe_error` | Status text `<Stage>: <message>` (Preparing, Gemini, Checking, Rendering, Saving). Errors show `<stage> failed: <message>`, a note that nothing was saved and the settings are unchanged, a next step from `NEXT_STEP` by code, and the LaTeX log path when there is one |

Debug first: `build_request(state, "daily-study-plan", {"days": 2})` shows exactly what Generate sends.

## Workshop

Responsibility and entry point: folder truth, selection and recents. `workshops.py` · `open_workshop(path)`.

| File or symbol | What it does |
| --- | --- |
| `open_workshop`, `create_workshop` | State `{root, current, selected:set}` of resolved paths; opening adds to recents |
| `browse(state, folder)`, `toggle_selection(state, path)` | Move and list (hidden entries such as publisher staging folders and out-of-workshop links are skipped); toggle one existing file or folder (not the root, not a link). `state["selected"]` is the one selection, shared by both modes and kept across navigation |
| `deselect(state, path)`, `prune(state)`, `is_link(path)` | Remove one entry by canonical path even if missing or off-screen; Refresh-only removal of missing entries (returned for reporting) and move to the nearest surviving folder; symlink/junction test shared with `organizing` |
| `validate_paths(root, destination, paths)` | Generate-time recheck: containment after `resolve()`, readability, destination inside the workshop |
| `load_recents`, `add_recent`, `remove_recent` | `%LOCALAPPDATA%\late_night_workshop\recents.json`, with an `exists` flag per entry |

## Registry, prompts and inputs

| File or symbol | What it does |
| --- | --- |
| `tasks.py` · `TASKS` | Eight task IDs → label, output type, prompt file, roles, layout, default folder, template, max pages |
| `tasks.py` · `validate_parameters(task_id, params)` | Study plans: `days` must be an int ≥ 1 (no bools, strings, zero or negatives; no upper cap, and requests are never shortened); `folder_name` empty → default, and `/ \ : * ? " < > |`, `..`, trailing dot/space and reserved names are rejected. Single file: `language_style` in Technical/Standard/Simple |
| `tasks.py` · `resolve_task(request, sources)` | Prompt = source index + `prompts/<task>.md` (`{days}` filled in) + `prompts/styles/<style>.md` + `prompts/format.md`; JSON schema with the exact document count (`minItems`/`maxItems`); expected roles and days; layout |
| `prompts/*.md` | `schedule`, `daily-study-plan`, `checklist`, `notes`, `summary`, `answer-key`, `cheat-sheet`, `sample-questions`; `format.md` holds the shared block grammar and grounding rules. Its `Math mode = plain` line is fixed text: no setting changes it, and the renderer escapes every backslash, so LaTeX-mode math would print literally |
| `prompts/styles/{technical,standard,simple}.md` | Language style fragments; study plans use Standard |
| `inputs.py` · `prepare_inputs(root, paths, efficient, capabilities, original_overrides)` | Per file → source record `{source_id, filename, mime_type, fingerprint, mode "original"|"text", original_path, text_parts, cache}` plus `decisions` and `warnings`. TXT/MD always pass through as text. **Efficient off:** original if the client supports the MIME type (PDF), otherwise local conversion with a `converted_locally` warning (PPTX, DOCX). **Efficient on:** local conversion. **Little text** (PDF: average under 40 non-whitespace characters per page, or empty pages; other types: no text) → a `needs_original` decision naming the pages if the original is supported, otherwise `unsupported_input` with an export hint. `original_overrides` (this job only) forces the original for the approved source IDs. Unreadable files give a filename-specific `conversion_failed` |
| `converters.py` · `convert(path, data)` | `pypdf` text per page, `python-pptx` text frames and table rows per slide (including groups), `python-docx` paragraphs and table rows in body order, UTF-8/UTF-16 text with normalized newlines. Cache in `%LOCALAPPDATA%\late_night_workshop\conversions\<sha256>-<converter>-v<CONVERTER_VERSION>-<OPTIONS>.json`; returns `cache: hit|miss`. Only conversions with some text are cached; cached units get the current source ID attached by `inputs` |

| Task ID | Layout | Output (in the folder captured at Generate) |
| --- | --- | --- |
| `schedule` | schedule | `<Folder, default Study Schedule>/schedule.pdf`, `file-guide.pdf`, `checklist.pdf` |
| `daily-study-plan` | daily | `<Folder, default Daily Study Plan>/Day 01/{notes,sample-questions,checklist}.pdf` … `Day NN/` |
| `checklist`, `notes`, `summary`, `answer-key`, `cheat-sheet`, `sample-questions` | single | `<task>.pdf`; the cheat sheet must be exactly 1 page |

## Gemini client and validation

| File or symbol | What it does |
| --- | --- |
| `gemini_client.py` · `generate_content(task, sources)` | One Interactions API call, model `gemini-3.8-flash` (or `GEMINI_MODEL`). The key comes from `GEMINI_API_KEY` in the environment, `./.env`, or (packaged) a `.env` beside `Late Night Pal.exe`. Originals (PDF) go inline as `document` items, each preceded by a `Source i: <source_id>` text item, with fingerprints rechecked. Text sources become one text item per file (`text_source_item`): `Source i: <id> (text extracted locally…)` with `[<id> - page N]` / `[<id> - slide N]` markers and `[end of <id>]`. One request can mix both. 50 MB total cap. Returns untrusted `{raw_text}`. Key-free `GeminiError` codes: `missing_key`, `api_quota`, `api_auth`, `api_model`, `api_limit` (HTTP 400: input, output or schema too large or complex; no verified numeric limit is known, so the API's own rejection is reported), `api_network`, `api_error` |
| `validation.py` · `validate_bundle(raw, task, sources)` | Blocks: `heading`/`paragraph` (`text`), `list` (`items`), `question` (`label` + `text`; labels kept verbatim, e.g. `2(b)`). Rejects the whole bundle on a wrong role set or count, a missing or duplicate (day, role), identical notes on two days, a missing `Day N` heading in the schedule, a source missing from the file guide, or an allocation that doesn't cover days 1..N, names an unknown source or leaves a source unused. Assigns `document_id` (`schedule`, `day-01-notes`, …). In sample questions, `_label_answers` gives unlabelled answers after the `Answers` heading the matching question labels (only when the counts match) |

Debug first: drop one document from a fixture bundle → `invalid_response` naming the missing role and day.

## Renderer and publisher

| File or symbol | What it does |
| --- | --- |
| `rendering.py` · `check_runtime()` | Resolves `lualatex` or raises `missing_latex`; called before any Gemini call |
| `rendering.py` · `render_bundle(bundle, task, work_dir, subtitle)` | Compiles every document with two `lualatex -no-shell-escape -halt-on-error` passes (`COMPILE_PASSES`, 180 s timeout each, so contents and references settle) into `work_dir`, then deletes that document's `.tex`/`.aux`/`.log`/other byproducts so only the PDF stays (on failure the `.log` is kept for the diagnostic copy; about 3 s per PDF), counting pages with `pypdf`. With `max_pages`, tries `CHEAT_SHEET_SIZES` (8.5 pt, then a 7.5 pt minimum) and then raises `page_limit_exceeded`. Records `{document_id, role, day, temp_path, page_count, seconds}`. `on_document(i, n, id)` reports progress. `names` (from `outputs.relative_output_paths`) turns a failure into `Couldn't compile Day 02/sample-questions.pdf (document 5 of 6).`, and the LaTeX log is copied to `%LOCALAPPDATA%\late_night_workshop\logs\` (document text only, never keys or request data). Daily PDFs' subtitles list only that day's `allocation.source_ids`. `blocks_to_latex` escapes all text, collapses titles, headings and question labels to one line (`one_line`; a blank line inside a command argument is a LaTeX error) and writes list items as `\item{}` so text starting with `[` stays text |
| `templates/document.tex`, `templates/cheat-sheet.tex` | Shared fontspec + Latin Modern, with fallback to Cambria / Segoe UI Symbol. The cheat sheet is two columns with 1.2 cm margins |
| `outputs.py` · `publish(rendered, task, destination, root)` | Checks IDs and count, maps names from the layout only (`relative_output_paths`). Single: `O_EXCL` claim of `name.pdf`, `name (2).pdf`, …. Folders: everything is copied into a hidden `.lnp-staging-*` sibling, then `os.rename` to `Folder`, `Folder (2)`, … (never replaces); staging is removed on failure |

## Generation and errors

`generation.py` · `generate(request, on_progress, deps)` returns `{status, output_root, paths, warnings, timings: {gemini_s, render_s, publish_s}, documents: [{document_id, page_count, render_s}]}` or `{status: "error", error: envelope}`. `deps` swaps `check_runtime` / `generate_content` / `render_bundle` / `publish` for stubs. `decide_inputs(decisions) -> {source_id: "process_original"|"cancel"}`: anything other than process_original for every pending source returns `{status: "cancelled"}` before any API call; otherwise preparation reruns with those `original_overrides`. Without a `decide_inputs` callback (the CLI), the job is cancelled. Bounded recovery: `ask_gemini` retries once only after `api_network` (quota, auth and limit errors are not retried). `validated` sends one `REPAIR_PROMPT` request (the problem, the task prompt and the previous JSON, without re-sending sources) and fails with "… (also after one repair attempt)". If `page_limit_exceeded`, one `CONDENSE_PROMPT` request is sent, revalidated without further repair and re-rendered; if it still overflows, the job fails with nothing published. `RenderError compile_failed` and publish errors are returned directly, with no Gemini call. Rendering happens in a `TemporaryDirectory` that is always removed. `__init__.py` · `AppError` subclasses give `{code, stage, message, source_id, retryable, details}`.

## Organizer and downloads (Phase 2, P2-M1: planning and discovery only)

Not wired into the UI yet; no organizer code moves, copies or deletes files. Selection contract and the remaining rules are in `components.md`.

| File or symbol | What it does |
| --- | --- |
| `organizing.py` · `capture_request(state, action, parameters)` | Click-time snapshot `{action, workshop_root, destination, sources, parameters}`, like `ui.build_request` |
| `organizing.py` · `plan_action(request)` | Validates the whole request and returns `{action, root, destination, create_folder, items: [{source, destination, kind}]}`, or raises `OrganizeError` (`code`, `.paths`) before any change. Only `wrap` is planned (new folder under the captured current folder); other actions raise `not_implemented`. Shared preflight: raw folder-name check before `tasks.safe_folder_name`, root/outside/missing sources, symlinks and junctions, selected descendants dropped, folder into itself, case-insensitive name clashes, existing destination |
| `organizing.py` · `outcome(item, status, change, error)`, `preview(plan)` | Per-item executor record (completed / failed / unattempted; `copied_source_kept` when the copy succeeded but source removal failed) for P2-M3; relative `src -> dst` lines |
| `downloads.py` · `chrome_records(profile_dir)` | Read-only Chrome `History.downloads`: `target_path`, `end_time` (µs since 1601 UTC), `state == 1` only → `{path, downloaded_at, timestamp_source}` |
| `python -m late_night_workshop.downloads` | Probe; prints only completed files named `lnp-probe-*` (`--match`) plus excluded counts by state |
| `tests/test_organizing.py`, `tests/test_selection.py`, `tests/chrome_download_probe.py` | Wrap planning fixture; selection, eligibility, `capture_request` snapshot and files-only Generate boundary (`python -m unittest tests.test_organizing tests.test_selection -v`); manual disposable-profile Chrome harness (results recorded in `components.md` → Downloads) |

## Packaging

| File or symbol | What it does |
| --- | --- |
| `pyproject.toml` | Dependencies (PySide6, google-genai, python-dotenv, pypdf, python-pptx, python-docx) and package data, including `prompts/styles/*.md` |
| `packaging/late-night-workshop.spec`, `packaging/launcher.py` | PyInstaller one-folder **windowed** build `dist/Late Night Pal/Late Night Pal.exe`. Bundles `prompts/` (8 tasks, `format.md`, `styles/`) and `templates/`, all `late_night_workshop`, `pptx` and `docx` submodules plus their package data (XML templates), and pypdf, dotenv and the Qt plugins (via PyInstaller hooks). Never bundles the API key |
| `packaging/build_release.py` | Runs the spec, stages `Late Night Pal/` with `Demo/` (a copy of `demo/`), `.env.example` and `READ ME FIRST.txt`, refuses `.env`, `*.log`, `recents.json`, cache folders, any file containing the developer key, and any path over 150 characters, then writes `dist/LateNightPal-win64.zip` |
