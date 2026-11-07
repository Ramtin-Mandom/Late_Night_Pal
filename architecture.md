# Architecture

Implemented through M3: workshop shell, shared pipeline, and all eight tasks with their output layouts. Package root: `src/late_night_workshop/` (internal id; the app's display name is Late Night Pal). The proposed full plan is in `components.md` and `PROJECT_MAP_AND_MILESTONES.md`; this file lists only what exists.

Pipeline order (`generation.generate`): validate parameters and paths → LaTeX + destination preflight → prepare inputs → resolve task → **one** Gemini request → validate the whole bundle → render every PDF in a temp dir → publish. A cheat sheet that overflows gets at most one condensation request.

## Desktop UI and entry point

Responsibility and entry point: start the app, show workshops, browse and select, collect task parameters, submit a request snapshot. Open `__main__.py` · `main()` first.

| File or symbol | What it does |
| --- | --- |
| `__main__.py` · `main()` | `python -m late_night_workshop`; `--check` verifies every prompt, style fragment, template and LaTeX; `--summarize FILE` runs a Standard Summary with the PDF's folder as workshop and destination → `summary.pdf` (suffixed if taken) |
| `ui.py` · `build_request(state, task_id, parameters)` | Qt-free snapshot `{workshop_root, destination, selected_paths, task_id, parameters, efficient}` taken at Generate |
| `ui.py` · `Window` start page | Welcome, Recent Workshops, Open/Create Workshop; a missing recent offers Open another folder / Remove |
| `ui.py` · `Window` workshop page | Up and folder browser (click a folder to enter, click a PDF to toggle), blue `SELECTED_BG`, Selected Inputs list (relative paths). **Output type** (Study plan / Single file) → **Task** list from `tasks.tasks_for()`. Single file shows **Language style**; Study plan shows **Days** (1–30) and **Folder name** (placeholder = default folder). `current_parameters()` → `tasks.validate_parameters()` before a job starts |
| `ui.py` · `Worker`, `job_finished` | Runs `generate` on a `QThread`; Generate disabled until done; `quit()` before `wait()` |

Debug first: `build_request(state, "daily-study-plan", {"days": 2})` shows exactly what Generate sends.

## Workshop

Responsibility and entry point: folder truth, selection and recents. `workshops.py` · `open_workshop(path)`.

| File or symbol | What it does |
| --- | --- |
| `open_workshop`, `create_workshop` | State `{root, current, selected:set}` of resolved paths; opening adds to recents |
| `browse(state, folder)`, `toggle_selection(state, path)` | Move and list (hidden entries such as publisher staging folders and out-of-workshop links are skipped); toggle one file. Selection survives navigation and task changes |
| `validate_paths(root, destination, paths)` | Generate-time recheck: containment after `resolve()`, readability, destination inside the workshop |
| `load_recents`, `add_recent`, `remove_recent` | `%LOCALAPPDATA%\late_night_workshop\recents.json`, with an `exists` flag per entry |

## Registry, prompts and inputs

| File or symbol | What it does |
| --- | --- |
| `tasks.py` · `TASKS` | Eight task IDs → label, output type, prompt file, roles, layout, default folder, template, max pages |
| `tasks.py` · `validate_parameters(task_id, params)` | Study plans: `days` must be an int 1–30 (no bools or strings); `folder_name` empty → default, and `/ \ : * ? " < > |`, `..`, trailing dot/space and reserved names are rejected. Single file: `language_style` in Technical/Standard/Simple |
| `tasks.py` · `resolve_task(request, sources)` | Prompt = source index + `prompts/<task>.md` (`{days}` filled in) + `prompts/styles/<style>.md` + `prompts/format.md`; JSON schema with the exact document count (`minItems`/`maxItems`); expected roles and days; layout |
| `prompts/*.md` | `schedule`, `daily-study-plan`, `checklist`, `notes`, `summary`, `answer-key`, `cheat-sheet`, `sample-questions`; `format.md` holds the shared block grammar and grounding rules |
| `prompts/styles/{technical,standard,simple}.md` | Language style fragments; study plans use Standard |
| `inputs.py` · `prepare_inputs(...)` | PDF originals → source records `{source_id, filename, mime_type, fingerprint, mode "original", original_path}`. Non-PDF → `unsupported_input`; Efficient → `unsupported_mode` (M4) |

| Task ID | Layout | Output (in the folder captured at Generate) |
| --- | --- | --- |
| `schedule` | schedule | `<Folder, default Study Schedule>/schedule.pdf`, `file-guide.pdf`, `checklist.pdf` |
| `daily-study-plan` | daily | `<Folder, default Daily Study Plan>/Day 01/{notes,sample-questions,checklist}.pdf` … `Day NN/` |
| `checklist`, `notes`, `summary`, `answer-key`, `cheat-sheet`, `sample-questions` | single | `<task>.pdf`; the cheat sheet must be exactly 1 page |

## Gemini client and validation

| File or symbol | What it does |
| --- | --- |
| `gemini_client.py` · `generate_content(task, sources)` | One Interactions API call, model `gemini-3.8-flash` (or `GEMINI_MODEL`). Each PDF goes inline, preceded by a `Source i: <source_id>` text item; fingerprints are rechecked; 50 MB total cap. Returns untrusted `{raw_text}`. Key-free `GeminiError` codes |
| `validation.py` · `validate_bundle(raw, task, sources)` | Blocks: `heading`/`paragraph` (`text`), `list` (`items`), `question` (`label` + `text`; labels kept verbatim, e.g. `2(b)`). Rejects the whole bundle on a wrong role set or count, a missing or duplicate (day, role), identical notes on two days, a missing `Day N` heading in the schedule, a source missing from the file guide, or an allocation that doesn't cover days 1..N, names an unknown source or leaves a source unused. Assigns `document_id` (`schedule`, `day-01-notes`, …) |

Debug first: drop one document from a fixture bundle → `invalid_response` naming the missing role and day.

## Renderer and publisher

| File or symbol | What it does |
| --- | --- |
| `rendering.py` · `check_runtime()` | Resolves `lualatex` or raises `missing_latex`; called before any Gemini call |
| `rendering.py` · `render_bundle(bundle, task, work_dir, subtitle)` | Compiles every document (`lualatex -no-shell-escape -halt-on-error`, 180 s timeout) into `work_dir`, counting pages with `pypdf`. With `max_pages`, tries `CHEAT_SHEET_SIZES` (8.5 pt, then a 7.5 pt minimum) and then raises `page_limit_exceeded`. Records `{document_id, role, day, temp_path, page_count, seconds}` |
| `templates/document.tex`, `templates/cheat-sheet.tex` | Shared fontspec + Latin Modern, with fallback to Cambria / Segoe UI Symbol. The cheat sheet is two columns with 1.2 cm margins |
| `outputs.py` · `publish(rendered, task, destination, root)` | Checks IDs and count, maps names from the layout only (`relative_output_paths`). Single: `O_EXCL` claim of `name.pdf`, `name (2).pdf`, …. Folders: everything is copied into a hidden `.lnp-staging-*` sibling, then `os.rename` to `Folder`, `Folder (2)`, … (never replaces); staging is removed on failure |

## Generation and errors

`generation.py` · `generate(request, on_progress, deps)` returns `{status, output_root, paths, warnings, timings: {gemini_s, render_s, publish_s}, documents: [{document_id, page_count, render_s}]}` or `{status: "error", error: envelope}`. `deps` swaps `check_runtime` / `generate_content` / `render_bundle` / `publish` for stubs. If `page_limit_exceeded`, one `CONDENSE_PROMPT` request is sent (no sources re-sent), then the bundle is revalidated and re-rendered; if it still overflows, the job fails with nothing published. `__init__.py` · `AppError` subclasses give `{code, stage, message, source_id, retryable, details}`.

## Packaging

| File or symbol | What it does |
| --- | --- |
| `pyproject.toml` | Dependencies (PySide6, google-genai, python-dotenv, pypdf) and package data, including `prompts/styles/*.md` |
| `packaging/late-night-workshop.spec`, `packaging/launcher.py` | PyInstaller one-folder build `dist/Late Night Pal/`; bundles the `prompts/` and `templates/` folders, never the API key |
