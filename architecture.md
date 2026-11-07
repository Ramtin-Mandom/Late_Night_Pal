# Architecture

Implemented through M1 (one PDF → Gemini summary → local LaTeX PDF). Package root: `src/late_night_workshop/`. The proposed full component plan is in `components.md` and `PROJECT_MAP_AND_MILESTONES.md`; this file lists only what exists.

## Desktop UI and entry point

Responsibility and entry point: starts the app and runs the M1 pipeline. Open `__main__.py` · `main()` first.

| File or symbol | What it does |
| --- | --- |
| `__main__.py` · `main()` | `python -m late_night_workshop`; `--check` headless resource + LaTeX preflight; `--summarize FILE` headless pipeline run |
| `ui.py` · `summarize_file(pdf_path, on_progress)` | Qt-free M1 pipeline: LaTeX preflight → Gemini → render to `<stem> summary.pdf` next to the source. Temporary; M2 `generation.py` replaces it |
| `ui.py` · `run_app()` | PySide6 window: Choose PDF, Generate summary (worker `QThread`, button disabled while running), status text, Open summary PDF |
| `__init__.py` · `resource_path(rel)` | Finds `prompts/` and `templates/` from source or a PyInstaller build (`sys._MEIPASS`) |

Inputs and outputs: a PDF path from the file dialog → a new PDF path shown and opened with `QDesktopServices`.
Debug first: `python -m late_night_workshop --summarize Sample_pdf/Note_1.pdf` runs the same pipeline without Qt.

## Gemini client

Responsibility and entry point: the only Gemini transport. `gemini_client.py` · `summarize_pdf(pdf_path)`.

| File or symbol | What it does |
| --- | --- |
| `summarize_pdf()` | Sends the PDF inline (base64 `document` item, max 50 MB) + `prompts/summary.md` through `client.interactions.create` with a JSON `response_format`; returns `{title, blocks}` |
| `SUMMARY_SCHEMA` | Block kinds `heading`/`paragraph` (`text`) and `list` (`items`) |
| `model_name()` | `GEMINI_MODEL`, else `gemini-3.8-flash` (confirmed available to this key on 2026-11-07) |
| `GeminiError` · `_sanitize()` | Key-free errors: `missing_key`, `api_quota`, `api_auth`, `api_model`, `api_network`, `invalid_response` |

Inputs and outputs: PDF path → untrusted dict (only shape-checked). Reads `GEMINI_API_KEY` from the environment or `./.env`.
Debug first: missing key → `missing_key` before any request; model errors → set `GEMINI_MODEL`.

## Renderer

Responsibility and entry point: escape content, fill the template, compile locally. `rendering.py` · `render_document(document, out_pdf, subtitle)`.

| File or symbol | What it does |
| --- | --- |
| `check_runtime()` | Resolves `lualatex` on PATH or raises `missing_latex` with install guidance |
| `escape()`, `blocks_to_latex()` | Escapes LaTeX special characters; rejects unknown block kinds |
| `render_document()` | Compiles in a temp dir (`-no-shell-escape`, `-halt-on-error`, 180 s timeout); writes with exclusive create (never overwrites) |
| `unique_path()` | `summary.pdf` → `summary (2).pdf` … on collision |
| `templates/document.tex` | fontspec + Latin Modern, luaotfload fallback to Cambria / Segoe UI Symbol for Greek and symbols |

Inputs and outputs: `{title, blocks}` → compiled PDF path, or `RenderError` (`compile_failed` with the first `!` log lines).
Debug first: render `{"title": "T", "blocks": [{"kind": "paragraph", "text": "50% A&B"}]}` to a temp path.

## Prompts and packaging

| File or symbol | What it does |
| --- | --- |
| `prompts/summary.md` | Summary task prompt (source-based, plain-text fields) |
| `pyproject.toml` | Dependencies and package data; `pip install -e .` |
| `packaging/late-night-workshop.spec`, `packaging/launcher.py` | M1 PyInstaller probe (one-folder, console); bundles prompts and templates, never the API key |
