# Late Night Pal — project map and milestones

## Product and current state

Late Night Pal is a desktop study sidekick: open a real local folder, select study sources across its subfolders, and generate useful study PDFs into that workshop. Eight coding hours are available. All eight generation tasks below remain in scope.

**Verified existing:** `AGENTS.md` contains the working agreement; `CLAUDE.md` references it; `architecture.md` and `workflow.md` are starter templates; `GEMINI_API_GUIDE_FOR_CLAUDE.md` describes the intended Gemini integration. No README, application entry point, dependency manifest, converters, prompts, renderer, or packaging configuration currently exists. An `.env` file exists; its contents were not inspected or verified. This document is the implementation plan, not a report of working features. All source paths below are **proposed**.

Proposed small stack: Python, PySide6 desktop UI, `google-genai`, deterministic local extractors, local LaTeX compilation, and PyInstaller for a Windows executable. Keep one process and ordinary functions/modules. Confirm dependencies in the first milestone; no web server, database, installer, CI/CD, OCR service, or manual file organizer is required.

Explicitly exclude drag-and-drop moves, file reordering, grouping selections into folders, and folder flattening. Generation may create its own folders and files. Do not move or modify source files.

## Workshop and action-panel behavior

- Startup shows recent workshops with their full paths, plus **Open Workshop** and **Create Workshop**. A workshop is a real folder. Save recent paths in the user's local application-data directory, outside the repository; handle missing paths by offering to locate/open another folder.
- Browse subfolders within the workshop. Clicking a file toggles its selection, blue highlight, and entry in a visible **Selected Inputs** list. Keep selection in a set of canonical paths independent of the current directory view. Show relative paths in the list so duplicate basenames are distinguishable. Reject paths escaping the workshop, including resolved links.
- Keep two dropdowns: output type (**Study plan**, **Single file**) and its task type. Changing tasks updates parameters while retaining selected inputs.
- Study plan exposes a positive-integer **Days** and optional **Folder name**. Use placeholders `Study Schedule` and `Daily Study Plan` respectively, and use those names when empty. Reject invalid days before calling Gemini.
- Single file exposes **Language style**: **Technical**, **Standard**, **Simple**. Append reusable style fragments to its task prompt. Study-plan prompts use Standard by default without adding another required control.
- Both output types expose an **Efficient** checkbox, initially off, with this text immediately underneath:

  “Converts files to text before sending them to Gemini. This can be much cheaper for some files, but diagrams, equations, tables, and formatting may be lost.”

- Disable duplicate Generate clicks during a job; show preparation, generation, rendering, success, and actionable error states. Keep selection and parameters on failure. Success lists output paths and offers Open document / Open output folder.

## Feature matrix

All tasks take Selected Inputs and Efficient. Every final document is a locally compiled PDF. “Current folder” means the browser's currently open folder inside the workshop, captured when Generate is clicked, regardless of input locations.

| Output type / task | Additional parameters | Expected files | Destination |
| --- | --- | --- | --- |
| Study plan / Make schedule | Days; optional Folder name, default `Study Schedule` | Exactly `schedule.pdf`, `file-guide.pdf`, `checklist.pdf`; schedule covers exactly Days; guide describes every selected source | One new folder under current folder |
| Study plan / Make daily study plan | Days; optional Folder name, default `Daily Study Plan` | Exactly Days day folders, each with `notes.pdf`, `sample-questions.pdf`, `checklist.pdf`; 3 × Days documents | One new parent folder under current folder; `Day 01`, `Day 02`, … |
| Single file / Checklist | Language style | `checklist.pdf` | Current folder |
| Single file / Notes | Language style | `notes.pdf` | Current folder |
| Single file / Summary | Language style | `summary.pdf` | Current folder |
| Single file / Answer key | Language style | `answer-key.pdf`, preserving supplied question numbers and subparts; flag missing/ambiguous questions | Current folder |
| Single file / One-page cheat sheet | Language style | `cheat-sheet.pdf`, exactly one rendered page | Current folder |
| Single file / Sample questions | Language style | `sample-questions.pdf` | Current folder |

Daily allocation is by topic and workload, not a copy of the same material each day. Ask Gemini for distinct topic assignments, source references, and workload estimates; allow brief deliberate review but reject identical day bodies. With sparse material and many days, use practice/review activities rather than inventing source content.

## Proposed component map and ownership boundaries

Each row can be owned independently; milestone numbers below identify the first integration point. Use plain request/result values to exercise components without the UI or a live API.

| Component / proposed files | Responsibility and entry point | Inputs → outputs | First milestone |
| --- | --- | --- | --- |
| Desktop UI: `src/late_night_workshop/__main__.py`, `ui.py` | Start app; workshop screen, browser, selection list, action controls; run generation off the UI thread; open saved results | User events → request snapshot; progress/result → visible state | M1–M2 |
| Workshop: `workshops.py` in the same package | Open/create folders, enumerate children, retain selection across navigation, persist recents in local app data | Folder/path events → validated workshop, current folder, selected canonical paths | M2 |
| Input preparation: `inputs.py`, `converters.py` | Decide originals/text, extract deterministically, identify scan failures, cache text with source identity | Selected paths + Efficient → ordered source records with MIME type, filename, original bytes/reference or attributed text, warnings | M2, M4 |
| Registry: `tasks.py`; `prompts/*.md`; `prompts/styles/*.md` | Map eight task IDs to prompt file, style fragment, schema, output layout and defaults | Task + parameters + source records → prompt + expected output contract | M2–M3 |
| Gemini: `gemini_client.py` | Single SDK client, supported input transport, structured-response request, bounded retry, secret-safe errors | Prompt, source records, schema → untrusted response bundle | M1–M2 |
| Orchestrator/validation: `generation.py`, `validation.py` | Validate local request, call components, check task-specific fields and counts; coordinate bounded repair | Request snapshot → validated document bundle or useful error | M2–M3 |
| Rendering: `rendering.py`, `templates/document.tex`, `templates/cheat-sheet.tex` | Escape content, populate local templates, compile in temp directory, inspect page count | Validated content blocks → compiled temporary PDFs or diagnostics | M1–M3 |
| Output writer: `outputs.py` | Safe names, collision avoidance, staging/publishing complete outputs, result manifest | PDFs + captured destination/layout → final paths | M2–M3 |
| Setup/package: `pyproject.toml`, `packaging/late-night-workshop.spec`, `README.md` | Dependencies, executable build, documented LaTeX prerequisite and demo commands | Source + build environment → runnable executable | M1, M7 |

Paths without an explicit prefix in the component rows are under `src/late_night_workshop/`. No component in this table is implemented yet. During implementation, populate `architecture.md` with verified paths/symbols and `workflow.md` with the working flow; create README setup steps when commands exist. This planning task leaves those accurate starter files and application code unchanged.

Eight separate prompt files: `prompts/schedule.md`, `daily-study-plan.md`, `checklist.md`, `notes.md`, `summary.md`, `answer-key.md`, `cheat-sheet.md`, and `sample-questions.md`. Reusable fragments: `prompts/styles/technical.md`, `standard.md`, `simple.md`. Technical uses domain terminology and precise detail; Standard uses clear student-level explanations; Simple uses plain words and short explanations without dropping essential concepts. One registry and one pipeline serve every task; do not duplicate clients or UI implementations.

## Efficient input paths

**Off:** send supported originals, particularly PDFs, so Gemini can use page visuals and layout. Confirm the selected model/endpoint's actual MIME, size, upload, and structured-output support in M1 using official documentation; do not assume every office format is accepted. For unsupported originals, explicitly report that local text conversion is needed and use the same converter path, retaining source attribution. If neither path supports a file, name it and stop before generation rather than silently omitting it. Plain text/Markdown can be sent as text.

**On:** prefer deterministic local conversion. Preserve source filenames and PDF page / PowerPoint slide markers in the assembled request. Cache successful conversion results in local app data, keyed by content hash, converter version, and options; reuse only for unchanged content. Failed or empty conversions are not successful cache entries. Do not cache API credentials.

| Input format | Proposed local conversion | Preserved | May be lost |
| --- | --- | --- | --- |
| PDF | `pypdf`, text per page | Filename, page number, embedded extractable text | Diagrams, layout, equations, tables/reading order; scans may have no text |
| PowerPoint `.pptx` | `python-pptx`, text per slide | Filename, slide number, text from supported shapes/table cells | Charts, images, spatial relationships, equations, unsupported objects |
| Word `.docx` | `python-docx`, paragraphs and table cells | Filename, paragraph order and basic table text | Pagination, floating objects, styling, equations and layout |
| `.txt`, `.md` | Decode locally; pass text through | Filename, text, Markdown syntax | Rendered appearance; warn on unsupported encoding |
| Images / legacy office formats | No deterministic text converter in demo | Original visual content only if API supports format | Efficient conversion unavailable; offer original path or request supported export |

For a PDF with very little text (initial heuristic: fewer than 40 non-whitespace characters per page on average, or empty pages), name the affected file/pages and warn that it may be scanned. Offer **Process original** or **Cancel** before any API call; the explicit original override applies to that source only. This heuristic cannot establish extraction accuracy. Show the same option for unsupported Efficient conversion; never silently upload originals against the selected mode.

Savings depend on the input and model: extracted text can reduce billed input for some files, but it is not guaranteed cheaper and can reduce answer quality. Do not promise a fixed percentage or add benchmarks to the eight-hour plan. Check the project's actual usage for the representative demo call.

## Shared request-to-output flow

1. **Snapshot and validate locally.** Capture workshop root, current destination, selected paths, task, Days/folder name or style, and Efficient. Confirm nonempty readable inputs, containment, writable destination, valid integer Days, and safe folder name. Resolve source references before navigation can change the request.
2. **Prepare inputs.** `inputs.py` returns attributed originals or text using the path above, including per-source original overrides. Surface unsupported files, unreadable files, size limits, and scan warnings before generation. Bound the request to the selected model's verified limits; ask the student to reduce inputs if necessary.
3. **Resolve task.** Registry composes the dedicated task prompt, optional style fragment, expected schema, and layout. Treat source text as study material, not instructions. Ask for source-based content and explicit uncertainty, never executable code or output paths.
4. **Call Gemini once per task where practical.** Use the repository guide's intended Google GenAI SDK and Interactions API, subject to M1 verification of current capabilities. Read `GEMINI_API_KEY` only in the local service process; optional `GEMINI_MODEL` selects a verified available model. Never bundle a key into the executable or log it. Return sanitized quota/network/authentication errors and allow explicit retry. Use a bounded transient retry; avoid silent repeated paid requests.
5. **Validate and render.** Request JSON bundles, especially for multi-document actions. Proposed contract: `{documents: [{role, day, title, blocks}], allocation: [...]}`; blocks are restricted headings, paragraphs, lists, tables, and constrained math content. Single-file tasks have one document; schedule has exactly three unique roles; daily has exactly one of each role for each day 1…Days. Reject missing/extra/empty documents, invalid day indexes, duplicate roles, and wrong data types. Check daily allocation covers the source topics without identical day content and answer-key labels match extracted question labels where identifiable; review semantic quality in the demo. Permit one explicit schema-repair attempt, then show failure without writing final output.
6. **Compile with local templates.** Model content supplies values, never arbitrary LaTeX programs. Escape LaTeX special characters and restrict math syntax; compile without shell escape, in a temporary directory, with timeout. On failure show a concise diagnostic and retain a local diagnostic log without secrets; do not claim success. For the cheat sheet, count compiled pages with `pypdf`; first apply a compact template with readable minimum font/margins, then permit one content-condensation request and recompile. If still over one page, report failure instead of shipping a multi-page cheat sheet or shrinking indefinitely.
7. **Publish safely.** Local layout rules determine all filenames. Reject traversal/reserved names and sanitize titles. Reserve a new folder or filename atomically, using suffixes such as `Study Schedule (2)` / `notes (2).pdf` on collision. Render all documents before publishing; keep staging artifacts outside the final output folder, clean up failed partial publication, and never overwrite existing user files. Show final paths and an Open action. Retain neither `.tex` nor logs in the study output folders so the required document counts stay exact.

## Example generated layouts

Assume `C:/Study/Biology` is the workshop, `Revision` is the current folder, and inputs came from both `Lectures` and `Readings`. Empty folder-name fields use the defaults shown.

```text
Biology/
├── Lectures/lecture-01.pdf          # existing input
├── Readings/chapter-02.pdf          # existing input
└── Revision/
    └── Study Schedule/
        ├── schedule.pdf            # requested Days entries
        ├── file-guide.pdf          # both source files
        └── checklist.pdf
```

```text
Biology/
└── Revision/
    └── Daily Study Plan/           # Days = 2
        ├── Day 01/
        │   ├── notes.pdf
        │   ├── sample-questions.pdf
        │   └── checklist.pdf
        └── Day 02/
            ├── notes.pdf
            ├── sample-questions.pdf
            └── checklist.pdf
```

Day numbers use at least two digits. A Single file action from this same view writes, for example, `Biology/Revision/summary.pdf`.

## Eight-hour milestones

Budgets are elapsed coding time, sequential by default, and total **8 hours (480 minutes)**. An owner can take the listed files as their scope; agree on the plain request/bundle contract before touching shared files. Keep all eight tasks; resolve dependency failures early instead of cutting task types.

| Milestone | Budget / cumulative | Depends on | Owned proposed files | Done when (one observable acceptance criterion) |
| --- | --- | --- | --- | --- |
| M1: Dependency spike and first complete path | 75 min / 1h15 | Existing Gemini guide; local key available | `pyproject.toml`, minimal `__main__.py`, `ui.py`, `gemini_client.py`, `rendering.py`, `templates/document.tex`, `prompts/summary.md` | A user selects a real PDF through a minimal desktop picker, sends it to Gemini, and opens a locally compiled summary PDF; selected model/API, LaTeX executable, and minimal packaging feasibility are recorded. |
| M2: Workshop shell and shared pipeline | 90 min / 2h45 | M1 | `workshops.py`, `ui.py`, `inputs.py`, `tasks.py`, `generation.py`, `validation.py`, `outputs.py` | Starting from recent/open/create workshop, a user selects sources across two folders, sees persistent blue selections/list, and generates Summary into the captured current folder without overwriting an existing file. |
| M3: All task contracts and output layouts | 100 min / 4h25 | M2 | Eight `prompts/*.md`, three style fragments, `tasks.py`, `validation.py`, renderer templates, layout rules in `outputs.py` | Every one of the eight task IDs runs through the same pipeline, with representative live schedule and two-day output matching the exact file trees/counts and a rendered one-page cheat sheet. |
| M4: Efficient preparation and scan handling | 65 min / 5h30 | M2; coordinate input record contract with M3 | `converters.py`, `inputs.py`, preparation controls in `ui.py` | PDF/PPTX fixtures yield page/slide-attributed text, an unchanged source reuses conversion, a changed source invalidates it, and a scan identifies its filename and offers original processing. |
| M5: Focused recovery and output polish | 45 min / 6h15 | M3–M4 | `validation.py`, `rendering.py`, `outputs.py`, error/progress UI | A representative malformed response and compilation failure produce useful errors with no final partial output; retry can complete without overwriting prior results. |
| M6: Main demo rehearsal | 40 min / 6h55 | M5 | Targeted fixes in owned modules; small fixtures if needed | One rehearsal completes the walkthrough below, checking schedule counts, distinct two-day content, answer numbering, and cheat-sheet page count without a broad test suite. |
| M7: Executable, handoff and buffer | 65 min / 8h00 | M6; dependency probe from M1 | `packaging/late-night-workshop.spec`, `README.md`, verified `architecture.md`, `workflow.md` | The executable launches outside the source checkout on the demo machine, finds bundled prompts/templates, uses a runtime key and installed LaTeX, and completes the main PDF-to-PDF path using the written demo instructions. |

M1 should probe a minimal executable, but full packaging belongs to M7. Reserve part of M7 for fixing packaging/resource-path failures. No installer is needed. The executable may rely on documented local LaTeX prerequisites; it must detect and explain a missing compiler before making a paid generation call.

## Demo and focused verification

1. Launch the desktop executable; Create Workshop or reopen a recent real folder. Browse two subfolders and select a real text-bearing PDF plus another small supported source. Navigate away and back to demonstrate retained selection and blue highlights; toggle one file off/on.
2. With Efficient off, choose Single file → Summary → Standard. Generate into the current folder and open the locally compiled PDF. Repeat once only if needed to show collision suffixing, preserving the first document.
3. Choose Study plan → Make schedule, Days = 2, leave Folder name empty. Open the default folder and show its exactly three PDFs and source guide.
4. Choose Make daily study plan with Days = 2. Show both day folders, three PDFs each, and distinct topics/workloads. Use a short fixed source set to keep API latency manageable.
5. Enable Efficient and show page/slide attribution from a converter fixture, then the scan warning with the affected filename. Demonstrate explicit original override or cancel.
6. Show the one-page cheat sheet's page count and a small Answer key example with matching question labels. Smoke-check remaining single-file tasks via the registry; do not build eight separate UI demonstrations.

Use one real API summary for the initial boundary check; representative live multi-document outputs for layout/content, and small local response fixtures for malformed bundles and compiler failures. Verify Technical/Standard/Simple fragments are registered and appended using one captured prompt assembly. Avoid full-suite runs and benchmarks unless requested. This planning task makes no API calls and verifies no runtime capability.

## Highest risks and early decisions

| Risk | Early check and response | Owner milestone |
| --- | --- | --- |
| API endpoint/model availability, document support, quota and latency | Consult the repo Gemini guide and verify current official SDK/API docs before implementation; choose a project-accessible model. If the intended endpoint lacks a required feature, document the reason and keep any supported-endpoint adaptation inside the single client. Never copy an unverified model ID from the guide. | M1 |
| Local LaTeX missing or package downloads blocking compilation | Probe an installed compiler and render a tiny document immediately. Use a minimal template/package set, document installation, and prepare the demo machine before rehearsal. No substitute renderer is silently assumed. | M1, M7 |
| Poor extraction, scans, tables and equations | Use a small known PDF/PPTX example and visible source markers; explicit original override for scan/unsupported conversion. OCR is deferred; original processing preserves the route for those files. | M4 |
| Structured output quality and long daily plans | Validate exact counts/roles and day allocations; cap repair attempts and offer actionable errors. Check model input/output limits before submission; retain positive-integer Days rather than silently truncating requested days. | M3, M5 |
| Cheat sheet exceeds one page | Count rendered pages; bounded compact-layout/condensation path with a readable minimum size; fail clearly if unsatisfied. | M3 |
| Executable misses Qt plugins, prompts, templates or compiler path | Probe packaging early and launch the full build outside the checkout on the demo machine. Resolve resources relative to packaged assets and keep cache/recents in writable local app data. | M1, M7 |

Implementation changes should include their related architecture/workflow/setup documentation. This plan intentionally creates only this planning file and changes no application code or existing repository documentation.
