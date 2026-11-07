# Architecture

Implemented through M2: workshop shell and shared pipeline, with Summary as the only working task. Package root: `src/late_night_workshop/` (internal id; the app's display name is Late Night Pal). The proposed full plan is in `components.md` and `PROJECT_MAP_AND_MILESTONES.md`; this file lists only what exists.

Pipeline order (`generation.generate`): validate request → LaTeX + destination preflight → prepare inputs → resolve task → Gemini → validate → render (temp dir) → publish.

## Desktop UI and entry point

Responsibility and entry point: start the app, show workshops, browse and select, and submit a request snapshot. Open `__main__.py` · `main()` first.

| File or symbol | What it does |
| --- | --- |
| `__main__.py` · `main()` | `python -m late_night_workshop`; `--check` resource + LaTeX preflight; `--summarize FILE` runs `generate()` with the PDF's folder as workshop and destination |
| `ui.py` · `build_request(state, task_id)` | Qt-free snapshot `{workshop_root, destination, selected_paths, task_id, parameters, efficient}` taken at Generate |
| `ui.py` · `run_app()` · `Window` | Start page (Welcome, Recent Workshops, Open/Create Workshop; a missing recent offers Open another folder / Remove). Workshop page: Up and folder browser (click a folder to enter it, click a PDF to toggle it), blue `SELECTED_BG` highlight, Selected Inputs list of relative paths, Output type / Task (Single file / Summary only), Generate, status, Open document / Open output folder |
| `ui.py` · `Worker` | Runs `generation.generate` on a `QThread`; Generate stays disabled until the job ends |

Inputs and outputs: clicks → `workshops` state and a request; Result → status text and opened path.
Debug first: `build_request(state)` after `toggle_selection` calls shows exactly what Generate will send.

## Workshop

Responsibility and entry point: folder truth, selection and recents. `workshops.py` · `open_workshop(path)`.

| File or symbol | What it does |
| --- | --- |
| `open_workshop`, `create_workshop` | State `{root, current, selected:set}` of resolved paths; opening adds to recents |
| `browse(state, folder)`, `toggle_selection(state, path)` | Move and list (hidden entries and out-of-workshop links skipped); toggle one file. Selection survives navigation |
| `validate_paths(root, destination, paths)` | Generate-time recheck: containment after `resolve()`, readability, destination inside the workshop |
| `load_recents`, `add_recent`, `remove_recent` | `%LOCALAPPDATA%\late_night_workshop\recents.json` (internal id, so a rename keeps recents); each entry has an `exists` flag |

Debug first: `validate_paths(root, root, [root/'..'/'x.pdf'])` → `outside_workshop`.

## Inputs, registry, Gemini client, validation

| File or symbol | What it does |
| --- | --- |
| `inputs.py` · `prepare_inputs(root, paths, efficient, capabilities)` | PDF originals → source records `{source_id (workshop-relative POSIX), filename, mime_type, fingerprint sha256, mode "original", original_path}`. Non-PDF → `unsupported_input`; Efficient → `unsupported_mode` (M4) |
| `tasks.py` · `TASKS`, `resolve_task(request, sources)` | Registry with only `summary`: prompt = source index + `prompts/summary.md`, `SINGLE_DOC_SCHEMA`, layout `single` / `summary.pdf` |
| `gemini_client.py` · `generate_content(task, sources)` | One Interactions API call, model `gemini-3.8-flash` (or `GEMINI_MODEL`). Each PDF goes inline, preceded by a `Source i: <source_id>` text item; fingerprints are rechecked (`source_changed`); 50 MB total cap. Returns untrusted `{raw_text}` |
| `gemini_client.py` · `_sanitize` | Key-free errors: `missing_key`, `api_quota`, `api_auth`, `api_model`, `api_network`, `api_error` |
| `validation.py` · `validate_bundle(raw, task, sources)` | JSON → `{documents:[{document_id:"summary", role, day:None, title, blocks}]}`; rejects unknown kinds and empty content (`invalid_response`) |

Debug first: `validate_bundle('{"blocks":[]}', task, [])` → `invalid_response`; `--summarize` exercises one live call.

## Renderer and publisher

| File or symbol | What it does |
| --- | --- |
| `rendering.py` · `check_runtime()` | Resolves `lualatex` or raises `missing_latex`; called before any Gemini call |
| `rendering.py` · `render_bundle(bundle, task, work_dir, subtitle)` · `compile_document` | Escaped template fill, `lualatex -no-shell-escape -halt-on-error`, 180 s timeout, PDFs stay in `work_dir` |
| `templates/document.tex` | fontspec + Latin Modern with luaotfload fallback to Cambria / Segoe UI Symbol (Greek, arrows, math symbols) |
| `outputs.py` · `check_destination`, `publish(rendered, task, destination, root)` | Claims `summary.pdf`, then `summary (2).pdf`, ... with `O_EXCL` (never overwrites); deletes only its own file if the write fails |

Debug first: publish twice into one folder and see `summary.pdf`, then `summary (2).pdf`.

## Shared error envelope

`__init__.py` · `AppError` (subclasses `WorkshopError`, `InputError`, `TaskError`, `GeminiError`, `ValidationError`, `RenderError`, `PublishError`, `RequestError`) → `envelope()` `{code, stage, message, source_id, retryable, details}`. `generate()` returns `{"status":"error","error":envelope}`, never raises.

## Packaging

| File or symbol | What it does |
| --- | --- |
| `pyproject.toml` | Dependencies and package data; `pip install -e .` |
| `packaging/late-night-workshop.spec`, `packaging/launcher.py` | PyInstaller one-folder build `dist/Late Night Pal/`; bundles prompts and templates, never the API key |
