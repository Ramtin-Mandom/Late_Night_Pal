# Component handoff guide

## Ownership table

All implementation paths and signatures here are **proposed**, not working code. Paths in the table are relative to `src/late_night_workshop/` unless rooted explicitly at the repository. Each row is a primary ownership role, not an assigned person. A milestone may need several owners; it does not transfer file ownership.

| Primary owner / responsibility | Owned paths | Public entry point or proposed build command | Direct dependencies | First integration |
| --- | --- | --- | --- | --- |
| UI: Desktop UI and app entry point | `__main__.py`, `ui.py` | `main()`; `python -m late_night_workshop` | Workshop functions, generation callbacks, PySide6 | M1 |
| Workshop: Browsing, selection, recents | `workshops.py` | `open_workshop()`, `browse()`, `toggle_selection()`, `validate_paths()` | Local filesystem and local app-data storage | M2 |
| Inputs: Preparation, conversion, caching | `inputs.py`, `converters.py` | `prepare_inputs()` | Workshop-validated paths; client capability values; `pypdf`, `python-pptx`, `python-docx` | M2; conversion M4 |
| Registry: Tasks, prompts, styles | `tasks.py`; `prompts/{schedule,daily-study-plan,checklist,notes,summary,answer-key,cheat-sheet,sample-questions}.md`; `prompts/styles/{technical,standard,simple}.md` | `resolve_task()` | Request, prepared source metadata; packaged text resources | M1 Summary; registry M2 |
| Client: Gemini transport | `gemini_client.py` | `get_capabilities()`, `generate_content()` | `google-genai`, runtime environment, verified model/API | M1 |
| Generation: Orchestration and validation | `generation.py`, `validation.py` | `generate()`, `validate_bundle()` | Workshop checks, inputs, registry, client, renderer, output writer | M2 |
| Renderer: LaTeX and PDF checks | `rendering.py`, `templates/document.tex`, `templates/cheat-sheet.tex` | `check_runtime()`, `render_bundle()` | Validated bundle, local LaTeX compiler, `pypdf` | M1 |
| Publisher: Layout and safe publishing | `outputs.py` | `check_destination()`, `publish()` | Workshop containment checks, rendered PDFs, resolved layout | M2 |
| Packaging: Setup and runnable handoff | Repository-root `pyproject.toml`, `packaging/late-night-workshop.spec`, `README.md`; package `__init__.py` if needed | `python -m pip install -e .`; `python -m PyInstaller packaging/late-night-workshop.spec` | All source/resources; build tools and demo machine | M1 probe; full build M7 |

Verified repository state: `architecture.md` and `workflow.md` remain templates; `AGENTS.md`, `CLAUDE.md`, `PROJECT_MAP_AND_MILESTONES.md`, and `GEMINI_API_GUIDE_FOR_CLAUDE.md` exist. No application source, README, dependency manifest, or packaging spec exists. `.claude/commands/` contains repository commands, not app components. No entry point can be inspected yet. Existing `.env` contents were not inspected. This task creates only this guide. During implementation, each component owner supplies verified architecture/workflow details for its own component; Packaging assembles setup/demo instructions in README.

## Contracts to agree on before parallel implementation

The following named values are documentation shorthand for ordinary dictionaries, lists, strings, bytes and paths. No shared types module is proposed. Agree on field names, task/role IDs, block grammar, error envelope, and temporary-file lifetime first. Keep each function in its owning module; use injection of ordinary functions for standalone checks.

### 1. Request snapshot: UI → Generation

One running example uses `C:/Study/Biology` as the workshop, two selected files in different subfolders, and `Revision` as a third destination folder. Paths below are illustrative, not repository fixtures.

```python
request = {
    "workshop_root": "C:/Study/Biology",
    "destination": "C:/Study/Biology/Revision",  # captured at Generate click
    "selected_paths": [
        "C:/Study/Biology/Lectures/cells.pdf",
        "C:/Study/Biology/Readings/genetics.pptx",
    ],
    "task_id": "daily-study-plan",
    "parameters": {"days": 2, "folder_name": ""},
    "efficient": True,
}
generate(request, on_progress, decide_inputs) -> Result
```

Workshop provides canonical absolute paths, containment validation (including resolved links), and selected paths sorted by workshop-relative path for stable order. UI copies them into a snapshot: later browsing cannot redirect this job. Generation rechecks readability, containment and destination immediately before work/publishing. Days must be a positive integer, excluding booleans; folder name is optional. Single-file parameters instead contain `{"language_style": "Standard"}`. Task ID determines output type; do not maintain an independent conflicting output-type field. Input selection must be nonempty. Invalid requests return a failure before an API call.

### 2. Prepared inputs and an explicit decision round trip

```python
prepare_inputs(root, selected_paths, efficient, capabilities,
               original_overrides=set()) -> Preparation

preparation = {
    "sources": [
        {"source_id": "Lectures/cells.pdf", "filename": "cells.pdf",
         "relative_path": "Lectures/cells.pdf", "mime_type": "application/pdf",
         "fingerprint": "sha256:<actual-content-hash>", "mode": "text",
         "text_parts": [{"unit": "page", "number": 1, "text": "Cell structure..."}],
         "original_path": None},
        {"source_id": "Readings/genetics.pptx", "filename": "genetics.pptx",
         "relative_path": "Readings/genetics.pptx",
         "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
         "fingerprint": "sha256:<actual-content-hash>", "mode": "text",
         "text_parts": [{"unit": "slide", "number": 1, "text": "Inheritance..."}],
         "original_path": None},
    ],
    "decisions": [], "warnings": [],
}
```

`source_id` is the canonical workshop-relative POSIX path, stable for an unchanged path within this workshop and distinct for duplicate basenames. The workshop root scopes the ID. Fingerprint identifies the bytes; renaming changes the ID, changing bytes changes the fingerprint. Original mode carries `original_path` and empty `text_parts`; the client reads/uploads that original and manages SDK upload references internally. Text/Markdown use `unit="document", number=None`; PDF pages and PPTX slides are one-based. Prefix submitted text with source ID, filename and unit numbers. Client must verify a file fingerprint before upload; changed content produces `source_changed` rather than mixing snapshots.

If extraction finds little text or conversion is unavailable, Preparation includes a decision instead of pretending that source succeeded:

```python
{"source_id": "Lectures/cells.pdf", "filename": "cells.pdf",
 "code": "needs_original", "reason": "little_text", "units": [1, 2],
 "choices": ["process_original", "cancel"]}

# Generation passes all decisions to UI, without calling Gemini:
decide_inputs(decisions) -> {"Lectures/cells.pdf": "process_original"}
# Generation reruns preparation with that ID in original_overrides.
```

The UI marshals this callback onto its UI thread and returns the decision to the worker; no worker opens a Qt dialog directly. Cancel ends the job with `cancelled`. Missing decisions keep the job blocked; silence is not approval. Overrides last only for this job/source fingerprint. Offer original processing only when client capabilities support it; otherwise return `unsupported_input` with an export suggestion. Partial sources are not sent while decisions remain unresolved.

Inputs owns routing: Efficient off sends supported originals (including PDFs) and uses declared local conversion fallback for unsupported formats; warn which file required fallback. Efficient on extracts PDF text by page, PPTX text by slide, DOCX paragraphs/table text, and passes TXT/Markdown through. Cache successful deterministic conversions by content hash, converter version and options in local app data, reattaching the current source ID. Do not cache empty/failed extraction as success. Little-text heuristic initially matches the map: under 40 non-whitespace characters per PDF page on average, or empty pages, prompts review. No OCR is planned. Diagrams, equations, layout, table structure and reading order may be lost; savings are input- and model-dependent.

Client supplies `capabilities = {"original_mime_types": [...], "input_limit": ..., "structured_output": ...}` using limits verified for the chosen model/endpoint in M1. These are application capability values, not assumed SDK field names. Inputs uses them to route; Client enforces transport limits too.

### 3. Resolved task: Registry → Generation, Client, Validator, Renderer, Publisher

```python
resolve_task(request, sources) -> task
task = {
    "task_id": "daily-study-plan",
    "prompt": "<daily-study-plan.md + Standard fragment + parameters/source index>",
    "response_schema": {"type": "object", "required": ["documents", "allocation"],
                        "properties": "<full block/document schema in tasks.py>"},
    "expected": {"days": [1, 2],
                 "roles_per_day": ["notes", "sample-questions", "checklist"],
                 "document_count": 6},
    "layout": {"kind": "daily", "folder_name": "Daily Study Plan"},
    "template": "document", "max_pages": None,
}
```

The schema illustration abbreviates nested properties; implementation must emit a real JSON schema, not the placeholder string above. Registry owns that declarative contract and output rules; Validation implements enforcement. Folder names resolve empty input to the task's default. Model responses cannot supply output paths. Source text is material to study, not instructions to execute.

| Task ID / visible label | Prompt file under `prompts/` | Required roles/count | Layout / default name |
| --- | --- | --- | --- |
| `schedule` / Make schedule | `schedule.md` | `schedule`, `file-guide`, `checklist`; exactly 3, `day=None` | `schedule`; new `Study Schedule` folder |
| `daily-study-plan` / Make daily study plan | `daily-study-plan.md` | `notes`, `sample-questions`, `checklist` per day 1…Days; exactly 3 × Days | `daily`; new `Daily Study Plan` folder |
| `checklist` / Checklist | `checklist.md` | `checklist`; 1, `day=None` | `single`; `checklist.pdf` |
| `notes` / Notes | `notes.md` | `notes`; 1, `day=None` | `single`; `notes.pdf` |
| `summary` / Summary | `summary.md` | `summary`; 1, `day=None` | `single`; `summary.pdf` |
| `answer-key` / Answer key | `answer-key.md` | `answer-key`; 1, `day=None` | `single`; `answer-key.pdf` |
| `cheat-sheet` / One-page cheat sheet | `cheat-sheet.md` | `cheat-sheet`; 1, `day=None` | `single`; `cheat-sheet.pdf`; cheat-sheet template, max_pages=1 |
| `sample-questions` / Sample questions | `sample-questions.md` | `sample-questions`; 1, `day=None` | `single`; `sample-questions.pdf` |

Study-plan tasks take Days and optional Folder name; Single file tasks take Language style. All take Efficient. Append `styles/technical.md`, `standard.md`, or `simple.md`; study plans default to Standard without an extra required control. Technical uses precise domain terms; Standard uses clear student explanations; Simple uses short, plain explanations retaining essential concepts. Answer-key blocks preserve explicit supplied labels/subparts and flag ambiguous/missing questions. Schedule includes exactly Days schedule entries and a guide covering every source. Daily allocation must split topic/workload, allowing deliberate review without identical day bodies. No task-specific client, pipeline or UI implementation is needed.

### 4. Model response → validated document bundle

```python
generate_content(task, sources, purpose="initial") -> {
    "raw_text": "<untrusted JSON text>", "usage": {},
}
validate_bundle(raw_text, task, sources) -> bundle
```

An illustrative response has this content (expand documents to all six before validation):

```python
{
 "allocation": [
   {"day": 1, "topics": ["Cell structure"], "workload_minutes": 45,
    "source_ids": ["Lectures/cells.pdf"]},
   {"day": 2, "topics": ["Inheritance"], "workload_minutes": 50,
    "source_ids": ["Readings/genetics.pptx"]}],
 "documents": [
   {"role": "notes", "day": 1, "title": "Cell structure",
    "blocks": [{"kind": "paragraph", "text": "Compare cell structures..."}]},
   # plus day 1 sample-questions/checklist and all three day 2 documents
 ]
}
```

Minimal shared block grammar: `heading {text, level:1|2}`, `paragraph {text}`, `list {items:[string]}`, `table {headers:[string], rows:[[string]]}`, `math {text}` (restricted syntax only), and `question {label:string, text:string}`. All blocks also have `kind`. Labels are strings, e.g. `"2(b)"`, not renumbered list positions. Reject unknown kinds, empty required content, invalid shapes/types and unrestricted LaTeX. Per-task fields in the registry schema add schedule entries/source-guide coverage when required; they must have explicit consumer checks in Validation and rendering rules before use.

Validated bundle retains `allocation` and documents, adding deterministic `document_id`, e.g. `day-01-notes`; IDs derive locally from day/role, never filenames. Single-file IDs equal role; schedule IDs equal role. Validation checks counts, unique role/day pairs, exactly days 1…Days, valid source references, required fields, schedule day/source coverage and identical day-body regressions. Answer numbering is checked against identifiable source question labels; uncertain extraction is surfaced as a warning rather than invented labels. Topic completeness and reasonable workload remain content-review checks in the demo; structural validation alone cannot prove them.

Client returns untrusted text, not a ValidatedBundle. Generation owns recovery: at most one schema-repair call after validation failure and at most one cheat-sheet condensation call after overflow. Each uses the same client and is revalidated; no unbounded loops. Client may retry a transient transport failure once; it does not decide content repair. Surface progress when a recovery call occurs.

### 5. Rendered PDFs → published result → UI

```python
check_runtime() -> {"compiler": "<resolved executable>", "ready": True}
render_bundle(bundle, task, work_dir) -> [
    {"document_id": "day-01-notes", "role": "notes", "day": 1,
     "temp_path": "<work_dir>/day-01-notes.pdf", "page_count": 2},
    # five remaining records for this example
]
publish(rendered, task, destination, workshop_root) -> {
    "output_root": "C:/Study/Biology/Revision/Daily Study Plan",
    "paths": ["C:/Study/Biology/Revision/Daily Study Plan/Day 01/notes.pdf",
              # remaining five full paths
             ],
}
```

Generation owns `work_dir` lifetime: keep it until publishing finishes; remove it on success/failure, retaining a sanitized diagnostic log in local app data when needed. Renderer owns temporary artifact contents, not final names. Publisher consumes every rendered record exactly once and rejects missing/duplicate IDs. Generation returns `{"status":"ok", "output_root":..., "paths":[...], "warnings":[...]}` to UI. UI opens those returned paths, never guessed filenames. Client usage values may be included as optional result metadata; Generation consumes them without exposing secrets.

Exact example output:

```text
Revision/Daily Study Plan/
  Day 01/notes.pdf
  Day 01/sample-questions.pdf
  Day 01/checklist.pdf
  Day 02/notes.pdf
  Day 02/sample-questions.pdf
  Day 02/checklist.pdf
```

Schedule instead publishes exactly `Revision/Study Schedule/{schedule,file-guide,checklist}.pdf`. Single file publishes one PDF directly in `Revision`, even when inputs came from several folders. New folder/file collisions use ` (2)`, ` (3)`, etc.; nothing existing is overwritten. No `.tex`, logs or cache files appear in output folders.

### Progress, failures and preflight

Use `on_progress({"stage": "preparing|awaiting_input|generating|validating|rendering|publishing", "message": "...", "source_id": None})`; source ID is populated when relevant. UI displays stages, not invented percentages. All component failures use an ordinary envelope such as `{"code":"compile_failed", "stage":"rendering", "message":"Could not compile Day 01 notes.", "source_id":None, "retryable":True, "details":{}}`. Component functions may raise one local error carrying this dictionary; Generation catches it and returns `{"status":"error", "error":...}`. Do not create an exception framework. Cancellation returns `{"status":"cancelled"}`; no final output is published. Warnings are displayable records with code/message/source ID, not raw stack traces.

Generation calls Renderer `check_runtime()` **before any Gemini generation/repair call**, and Publisher `check_destination()` before expensive work. Missing LaTeX produces `missing_latex` with installation guidance. Packaging documents/ships resource lookup and prerequisites; Renderer detects the live compiler. Client checks credentials/capabilities without printing the key. Filesystem/API/compiler errors are sanitized at their owning boundary; logs never include credentials.

## Component implementation briefs

### UI — entry point and desktop presentation

Own `__main__.py` and `ui.py`. `main()` starts PySide6; the UI calls Workshop functions and submits a copied Request to `generate()` on a worker. Consume progress, decisions, Result and Failure exactly as above. Own clicks, blue highlights, dialogs, loading state and Open actions; Workshop owns selection/path truth and Generation owns task execution. Preserve request controls and selection after failure; disable duplicate Generate while active.

Show startup recent full paths plus Open Workshop/Create Workshop; show Selected Inputs with relative paths. Keep output-type/task dropdowns, positive Days and default folder placeholders for study plans, and Technical/Standard/Simple for Single file. Both output types show Efficient, initially off, immediately followed by:

“Converts files to text before sending them to Gemini. This can be much cheaper for some files, but diagrams, equations, tables, and formatting may be lost.”

Failure: a `needs_original` decision names the affected file in a dialog; pass the user's per-source choice to Generation. Do not silently continue. Standalone check: use a tiny in-memory Workshop stub for two folders and a canned generator that emits preparing/rendering then six final paths. Click two files across folders, toggle one off/on, and navigate; observe blue highlights/Selected Inputs stay consistent, progress appears, and success opens a returned path. Feed a scan decision and confirm the callback returns only the selected override. No Gemini/LaTeX required.

### Workshop — filesystem state

Own `workshops.py`. Proposed signatures: `open_workshop(path) -> state`, `create_workshop(path) -> state`, `browse(state, path) -> entries`, `toggle_selection(state, path) -> state`, `validate_paths(root, destination, paths) -> canonical_values`. UI is the browsing caller; Generation and Publisher call path checks. State contains root, current folder, selected canonical paths; selection is independent of the displayed folder. Persist recents in local app data and handle stale paths.

Own canonicalization, containment, recents and selection across folders; do not own highlight colors or final generation filenames. Failure: a resolved link outside root returns `outside_workshop` with the offending path identified for the caller, without selecting it. Standalone check: create a temporary root with `Lectures/a.pdf`, `Readings/b.pdf`, and `Revision`; select both, navigate to Revision, and confirm both remain selected. Reopen state and confirm the root appears in recents; an outside-root path is rejected. Use placeholder file bytes; generation is unnecessary.

### Inputs — preparation and conversion

Own `inputs.py` and `converters.py`; Generation calls `prepare_inputs()` and consumes Preparation, Registry/Client consume the successful source records. Follow the prepared-source contract above. Own routing, converters, scan detection and successful conversion caching; Client owns upload/SDK details, UI owns consent presentation.

Failure: `Lectures/scan.pdf` with empty extracted pages returns `needs_original`, file ID and page numbers; no silent omission or upload. Unsupported originals with conversion unavailable return `unsupported_input`. Standalone check: use a known two-page text PDF and two-slide PPTX; observe page/slide text markers and filenames. Repeat unchanged input to observe a cache hit, edit source bytes to observe a miss, and use an image-only PDF to obtain the file-specific decision. Then supply its override with PDF-capable fake capabilities and observe original mode. No API/UI required.

### Registry — prompts and declarations

Own `tasks.py`, the eight task prompt files and three style fragments in the ownership table. `resolve_task(request, sources)` is called by Generation; return the ResolvedTask contract for Client, Validation, Renderer and Publisher. Own prompt assembly, declarative schema/expected roles, default names and layout IDs. Validation owns enforcement, Renderer owns compiled page count, Publisher owns actual paths.

Failure: an unknown task ID/style returns `invalid_task`/`invalid_parameter` before any request. Standalone check: resolve all eight IDs with two source metadata records; assert daily Days=2 declares six documents, schedule declares three, each Single file declares one, and cheat-sheet declares max_pages=1. Assemble Summary three times and inspect the distinct appended Technical/Standard/Simple fragments. No model call or generated test infrastructure needed.

### Client — one Gemini transport

Own `gemini_client.py`. Generation calls `generate_content(task, sources, purpose)` and reads untrusted raw text; Inputs consumes capability values from `get_capabilities()`. Consult `GEMINI_API_GUIDE_FOR_CLAUDE.md` and verify current official documentation in M1 before choosing the model/SDK/endpoint. Intended stack is Google GenAI SDK / Interactions API, subject to verified support; isolate justified endpoint adaptation here.

Read `GEMINI_API_KEY` in the local process, optionally `GEMINI_MODEL`; no secret in UI source, executable resources or logs. Own MIME uploads, attribution transport, fingerprint check, response extraction, size limits and one bounded transient retry. Inputs decides original/text, Registry supplies prompts/schema, Generation decides repair/condensation. Failure: quota rejection returns `api_quota` with a useful sanitized message, preserving sources/parameters upstream. Standalone check: supply a hand-written Summary task and one real PDF source record to this module; one authorized runtime call returns nonempty raw content or a sanitized actionable API failure. Do not confuse raw JSON validity with successful validation. A transport stub suffices for quota handling.

### Generation — coordination and validation

Own `generation.py` and `validation.py`. UI calls `generate()`; it consumes Request, coordinates all components in contract order, and returns Result. `validate_bundle()` consumes raw text + task + source metadata and returns the only bundle Renderer may accept. Own request parameter checks, task-role/day/count enforcement and bounded recovery. Workshop remains the canonical-path authority; other owners retain their algorithms.

Sequence: validate snapshot → runtime/destination preflight → capabilities/preparation → UI decisions and preparation retry → resolve task → client → validate → render → publish → return paths. Keep progress flowing without putting UI concerns in services. Daily split/content is proposed by Gemini; do not locally divide every source identically into every day. Failure: a two-day bundle missing day-2 checklist triggers one schema-repair call, then `invalid_response` if still incomplete; never invoke Publisher with that bundle. Standalone check: inject canned client/renderer/publisher functions, provide the running Request and six handwritten document records, and observe six final paths; remove one record and observe bounded repair plus no publishing. Also observe missing-LaTeX preflight prevents any client generation call.

### Renderer — actual LaTeX and page checks

Own `rendering.py`, `templates/document.tex` and `templates/cheat-sheet.tex`. Generation calls `check_runtime()` and `render_bundle(bundle, task, work_dir)`; Publisher consumes RenderedPDF records. Own escaped template substitution, restricted math handling, local compilation without shell escape, timeouts, logs and actual page counts. Do not accept arbitrary model LaTeX, choose final filenames, or call Gemini.

Failure: compilation returns `compile_failed` and a sanitized local log reference; cheat-sheet overflow returns `page_limit_exceeded` with observed pages and document ID. Generation decides whether to request condensation. Use a readable compact template/minimum font and reject persistent overflow. Standalone check: feed a handwritten validated notes document containing `50%`, `A&B`, and a short list into the real template, compile locally and open the PDF; text renders correctly and page_count matches inspection. Render a long cheat-sheet fixture and observe overflow instead of silent multi-page success. No UI or Gemini required.

### Publisher — safe final layout

Own `outputs.py`. Generation calls `check_destination()` before API work and `publish()` only after every PDF succeeds. Consume rendered IDs/roles/days, task layout, captured destination and workshop root; return final absolute paths/output root. Own deterministic safe names, traversal/reserved-name rejection, collision suffixes, folder structure and complete publication. Renderer owns temp PDFs; Workshop supplies canonical containment checks.

Prepare study-plan output in a private staging sibling on the same filesystem, then claim a collision-free final name without replacing another directory. For Single file use an exclusive non-overwrite publication strategy. Recheck containment before writing, handle racing collisions, and roll back only this job's artifacts if publication fails. Preserve existing user files; do not move sources. Failure: destination becomes unwritable returns `publish_failed`; no completed output is reported and existing results remain intact. Standalone check: use six temporary PDFs and the daily layout; publish twice. Observe exactly six PDFs per result, a second `Daily Study Plan (2)` root, and unchanged first-result bytes. Also try `../outside` as Folder name and observe rejection. No model/compiler/UI required for this check.

### Packaging — runnable handoff

Own root `pyproject.toml`, `packaging/late-night-workshop.spec`, `README.md`, and package `__init__.py` if needed. The table's commands are proposed commands to make real; they have not been executed. Depend on each owner's files, explicitly bundle all prompts/style fragments/templates, and document package-relative resource lookup for owners to use (including frozen execution). Keep recents/cache/logs in writable local app data. No installer or CI/CD is required.

Packaging owns build configuration and prerequisite/setup documentation; Renderer owns runtime LaTeX detection and Generation invokes it before paid work. The executable does not include the developer's API key. Failure: missing bundled template is diagnosed as a resource error, not a Gemini retry. Standalone check: build the minimal app, launch the executable from outside the checkout, load Summary prompt/template, and observe the runtime compiler preflight; after full integration complete one real PDF→Gemini→local PDF path on the demo machine. Record actual commands/prerequisites in README only when verified.

## Implementation order and integration checkpoints

The existing budget remains **480 minutes / eight hours**. Parallel work is possible after agreeing on contracts; it does not add time or require multiple app processes. Coordinate edits by primary owner, especially when M3/M4 need UI changes. Manual file moves, drag-and-drop organizing, reordering, grouping and flattening remain excluded. Generation alone creates its required files/folders.

| Milestone / existing budget | Owners and handoff | Observable integration acceptance |
| --- | --- | --- |
| M1 / 75 min (1h15 cumulative) | Agree Request, source records, block grammar and errors first. UI supplies real PDF picker; Client verifies API/model; Registry supplies Summary; Renderer proves local compiler; Packaging probes build. | Select a real PDF, call Gemini, compile Summary locally, and open it. Record dependency findings; a minimal executable can locate its resources. |
| M2 / 90 min (2h45) | Workshop/UI can build selection independently; Inputs/Registry/Renderer/Publisher can use the contract fixtures above. Generation connects their real boundaries. | Select across two folders, retain blue selection/list during navigation, and publish Summary into captured destination without overwriting an existing file. |
| M3 / 100 min (4h25) | Registry declares eight tasks; Generation enforces them; Renderer handles blocks/page limits; Publisher handles layouts; UI exposes parameters. These owners can work in parallel after the document contract is fixed. | All eight IDs share one pipeline; live schedule has three PDFs, two-day plan has six in correct day folders, and cheat sheet is one rendered page. |
| M4 / 65 min (5h30) | Inputs implements deterministic converters/cache and decisions; UI owner adds scan dialog; Client supplies verified original capabilities. | Page/slide attribution survives preparation, cache invalidates on change, and a named scan blocks until explicit original override or cancel. |
| M5 / 45 min (6h15) | Generation coordinates bounded repairs; Renderer/Publisher expose failures; UI displays them. | A malformed bundle and compile failure leave no final partial result; an explicit successful retry preserves earlier output. |
| M6 / 40 min (6h55) | Rehearse with all owners; fix in each owner's files. Use small representative sources, not a full suite. | Main demo completes with correct schedule count, distinct two-day topics/workloads, preserved answer labels and verified cheat-sheet page count. |
| M7 / 65 min (8h00) | Packaging assembles executable/resources and verified README; owners supply accurate architecture/workflow handoffs and fix resource-path problems in their modules. | Launch outside checkout on demo machine and complete the real PDF→Gemini→local PDF flow using only documented setup, runtime key and installed LaTeX. |

M1 is a small end-to-end slice, not eight finished components. Replace its temporary wiring with the common contracts in M2; do not leave a second generation pipeline behind. Later integration must use real Client/Renderer/Publisher boundaries at representative checkpoints, even when most standalone checks use plain fixtures. No test infrastructure or benchmark is part of this documentation task.

## Handoff cross-check

- Every proposed source/resource/build file in the project map appears under exactly one primary owner above, including eight prompts and three style fragments. The only additional potential source file, `__init__.py`, belongs to Packaging. Existing docs are not being replaced by claims of implemented behavior.
- Request is consumed by Generation; canonical paths by UI/Generation/Publisher; capabilities by Inputs/Client; Preparation by Generation; decisions by UI and then Inputs; resolved task by Client/Validation/Renderer/Publisher; raw response by Validation; validated bundle by Renderer; temporary PDFs by Publisher; final paths/progress/errors by UI. Generation consumes allocation/source checks and usage metadata, and owns cleanup/recovery.
- All eight tasks use the same preparation → registry → Gemini → validation → local LaTeX → safe publishing route. Scope retains both Efficient paths, every action/style and exact layouts, with no manual organizer features.
