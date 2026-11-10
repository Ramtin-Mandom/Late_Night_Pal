# Late Night Pal — Phase 3 workshop study tools and milestones

## Purpose and status

Phase 3 plans four features for the existing Windows/PySide6 app. **P3-M1 (workshop search) and P3-M2 (PDF page selection) are implemented** (see Implementation notes); P3-M3 through P3-M6 are proposed and pending implementation.

1. Search across the workshop.
2. Choose PDF pages for generation.
3. Generation history.
4. Study progress tracking.

The verified baseline is described in `architecture.md`. It includes cross-folder selection, eight generation tasks, local input conversion, PDF compilation and publication, organization actions, and PDF opening through Chrome with a default-viewer fallback. `workflow.md` describes the working user flow.

Implementation order places history before progress because a saved generation ID gives progress a stable owner. Each milestone delivers an independently usable part of the study workflow. Routine implementation decisions can be resolved within these contracts.

## Feature contracts

### Search across the workshop

- Add a search field above the folder browser. Search filenames and folder names recursively beneath the open workshop using case-insensitive substring matching.
- Show workshop-relative paths so `Lectures/topic.pdf` and `Readings/topic.pdf` are distinguishable. Use deterministic relative-path ordering.
- Search runs off the UI thread. Associate each request with its workshop and query so a late response cannot replace newer results. Debounce typing and cancel or discard obsolete work.
- Search uses the browser's containment, hidden-entry and link rules. Skip inaccessible subfolders and show a concise warning when results are incomplete.
- Selecting a result uses the existing shared selection. Double-click opens a folder or PDF through the existing actions. Provide **Show in folder** for locating a file in its parent folder.
- Keep the current generation destination visible while results are shown. Selecting a search result does not navigate or change that destination. Explicit folder navigation changes it normally.
- Clearing search returns to the current folder. Refresh reruns the current query and uses the existing missing-selection reconciliation.
- The first version searches names. Document-content indexing can be evaluated after this feature is used.

### Choose PDF pages for generation

- Add a **Pages** control to each selected PDF. Default to **All pages**. Accept one-based physical page numbers and inclusive ranges such as `1, 3-5, 8`; normalize duplicates and overlaps into ascending page order.
- Show the PDF's page count and the normalized selection. Reject malformed ranges, reversed ranges, zero, negative and out-of-bounds pages with a filename-specific message before any API call. An empty field means All pages.
- Non-PDF inputs continue through their existing preparation path. Each PDF has its own selection, including when selected through search.
- Capture page selections with the Generate request. Requests created before Phase 3 that omit this field use All pages. Deselecting a PDF removes its page setting. Confirmed organizer moves remap retained settings with the selected path.
- In original mode, build a temporary PDF containing only selected pages and send that payload. Apply the existing size check to the actual payload. Keep original source identity and a mapping from payload page positions to original page numbers.
- In Efficient mode, filter extracted units to the chosen pages and retain their original page markers. Evaluate low-text/scan decisions only against those pages. **Process original** sends the selected-page PDF.
- Keep the existing full-file conversion cache reusable by filtering after extraction. If derived PDFs are cached later, their identity must include the source fingerprint and normalized page set.
- Recheck source fingerprints before sending. Fingerprints used to verify a derived payload must match its bytes, while the original fingerprint remains available for source-change checks and history.
- Include the original page mapping in the prompt for original-PDF payloads. A selection of pages 3 and 8 must be described as original pages 3 and 8 throughout the source index and text markers.
- Keep subset payloads inside the generation job's temporary lifetime, including scan decisions and retries. Clean them up on success, failure and cancellation. Report encrypted or unreadable PDFs before sending anything.

### Generation history

- Add a **History** view scoped to the open workshop. A successful generation shows task, completion time, input paths/page selections, settings, and saved output paths. List newest first.
- Give each generation a unique `generation_id`. Save the captured request and final published document IDs/roles/days so history and progress can work without parsing PDF filenames or calling Gemini.
- **Open document** uses the existing PDF opener. **Open output folder** uses the recorded destination. Missing files are marked unavailable.
- **Reuse settings** restores inputs, page choices, task parameters, Efficient and destination after current containment and availability checks. It displays missing or changed sources and invalid settings for correction before Generate is available. Starting generation remains an explicit action.
- Record history only after publication succeeds. If saving history fails, report that the PDFs were saved and offer a metadata-save retry tied to the same generation ID. A retry must avoid duplicate entries and further API calls.
- Store versioned metadata under `%LOCALAPPDATA%\late_night_workshop\`, partitioned by canonical workshop root, using workshop-relative input/output paths. Records contain settings, fingerprints and paths. API keys, full source contents and raw model responses are excluded from the record schema.
- Use atomic persistence and serialize updates within the app. Corrupt or unsupported metadata produces an actionable warning and preserves the original file for recovery. A workshop with no metadata opens with an empty history.
- Apply confirmed organizer move mappings to saved source/output paths, including descendants. Mark deleted or externally moved paths unavailable. Recreated or externally replaced source files are checked against recorded fingerprints when settings are reused.
- Existing PDFs remain browsable. History starts with generations recorded after implementation. Workshop relocation/import can be designed separately when needed.

### Study progress tracking

- Add a **Study progress** view for saved `daily-study-plan` generations. Start with one checkbox for each day's Notes, Sample questions and Checklist, grouped under the day.
- Store completion against `(generation_id, document_id)`. Two plans with the same title or overlapping dates have independent progress.
- Show completed/total items per day and across the plan. Derive totals from the recorded plan manifest. A two-day plan has six tracked items.
- Checkbox changes save locally and survive restart. A persistence failure is visible and the UI returns to the last saved value.
- Open a tracked PDF using the existing opener. A missing PDF is shown as unavailable while its saved progress remains visible.
- A newly generated plan begins with all items incomplete. Reusing a historical request creates a separate plan and progress record.
- Completion is a student-controlled study marker. It does not infer mastery from opening a document. PDFs and printed checklists retain their existing content.

## Proposed component map

Source paths in this table are relative to `src/late_night_workshop/`. New module names and functions are proposals to refine during implementation.

| Component | Responsibility and entry point | Inputs → outputs |
| --- | --- | --- |
| Existing `ui.py` | Search/results, per-PDF page control, History and Study progress views, request capture and worker integration | User actions → immutable request snapshots; results → visible state |
| New `search.py`, existing `workshops.py` | `search(root, query)` with current containment/link rules; existing selection and navigation remain the entry points | Root/query → relative-path matches and scan warnings |
| New `pdf_pages.py` | Parse/validate ranges and create subset payloads with original-page mappings, using existing pypdf dependency | Range/count or source/pages/job directory → normalized page list or prepared PDF |
| Existing `inputs.py`, `converters.py`, `gemini_client.py` | Selected-page extraction, scan eligibility, source/payload identities and transport | Captured page choices → attributed text or restricted original payload |
| Existing `generation.py`, `tasks.py` | Carry captured page metadata, manage subset lifetime, describe page mapping, emit successful generation manifest | Request → published result with stable document metadata |
| New `history.py` | Record/load successful generations, validate reusable settings, persist metadata and reconcile paths | Request + published result or confirmed moves → history records |
| New `study_progress.py` | Compute daily totals and persist completion against generation/document IDs | Saved daily-plan manifest + checkbox change → completion state/totals |
| Existing `workshops.py`, organizer completion integration | Reuse confirmed move/delete outcomes for selected-page settings and persisted metadata | Confirmed outcomes → remapped paths or unavailable entries |

Use plain values and functions for search, page parsing, record validation and progress calculation. Keep metadata owned by history/progress functions and reuse the existing atomic-write pattern where appropriate. Coordinate their writes so progress changes cannot overwrite history changes. Existing publication remains the authority for final PDF paths.

## Phase 3 milestones

| Milestone | Depends on | Deliverable | Done when |
| --- | --- | --- | --- |
| P3-M1 — Workshop search (**implemented**) | Existing workshop browser | Name search, relative-path results, selection and open/location actions | Search a disposable workshop with duplicate filenames in different subfolders. Select a result and open a PDF. Clear search and confirm the selection and captured destination behavior. A stale query cannot replace newer results. Links outside the workshop are skipped. |
| P3-M2 — PDF page selection end to end (**implemented**; the compile-dependent pipeline tests were blocked by MiKTeX) | Existing generation pipeline; independent of P3-M1 | Per-PDF ranges through capture, preparation, prompts, transport and cleanup | On a PDF with distinct text on each page, select `1, 3-4`. Inspect one original-mode payload and one Efficient-mode source record and confirm only those pages are sent with correct original numbers. Out-of-range input fails before a client call. A selected scanned page's Process original fallback sends only the selected pages. A request without page settings still uses the full document. |
| P3-M3 — Persistent generation history | P3-M2 | Versioned successful-job records, History UI, open actions and metadata retry | Generate a small output and reopen the app. Its task, settings, input page choices and final paths appear. Simulate a metadata-save failure after publication and verify the UI reports saved PDFs; retry saves one record without regenerating. A failed or cancelled generation creates no successful entry. |
| P3-M4 — Reuse history and reconcile paths | P3-M3 | Restore-settings action, source-change checks and organizer integration | Reuse a saved request and confirm its page ranges and destination. Move an output folder through Organize and open the remapped history entry. Delete an input and verify reuse identifies it for correction. Corrupt metadata shows a warning and preserves the original record file. |
| P3-M5 — Persistent study progress | P3-M4 | Daily-plan completion controls and totals | Open a two-day plan, mark two of six items complete, restart and see `2/6`. Generate another plan and confirm independent completion. A missing output is visibly unavailable. A failed save returns the checkbox to its saved state. |
| P3-M6 — Integrated demo and handoff | P3-M1 through P3-M5 | Working packaged flow and current implementation documentation | Run the walkthrough below in the Windows build. Verify search and page helpers are included, PDF opening works, history/progress survive restart, and one existing All pages generation still succeeds. Update affected sections of architecture, workflow and README with observed behavior. |

## Verification and demo

Use the repository's cheapest meaningful check at each milestone. Reuse existing tests and inject the Gemini client for payload inspection where practical. Add focused regression checks for page filtering, metadata retry and independent plan progress when existing checks cannot catch those failures. Record the observed result and any blocker in the milestone implementation notes.

1. Open a disposable workshop containing a multi-page PDF in a nested folder and a second file with the same basename elsewhere.
2. Search the common basename, identify the intended relative path and open that PDF.
3. Select it, set pages `1, 3-4`, navigate to the intended output folder and request a two-day daily study plan.
4. Inspect the prepared request to confirm page selection, then run one real generation for the integrated handoff.
5. Open History, inspect the saved page choices and open a generated PDF.
6. Mark two study items complete and restart the app. Verify the same history entry and `2/6` progress.
7. Reuse the saved settings, verify all fields and create a separate plan with empty progress.
8. Move the first plan's output folder through Organize and verify its History/Study progress links follow the confirmed move.

## Implementation notes

Add verified outcomes, relevant checks and remaining limitations as each milestone is implemented. P3-M3 through P3-M6 are pending.

### P3-M1 — Workshop search (implemented 2026-11-09)

- **Built:** `search.py` · `search(root, query, cancelled)` (Qt-free) and, in `ui.py`, the search field above the browser, debounce (250 ms), `SearchWorker` threads, `search_is_current()` stale-result rule, relative-path result rows with **Show in folder**, and the Refresh/organizer rerun. Details in `architecture.md` (Workshop and Desktop UI tables) and `workflow.md` section 2.
- **Decisions:** links and junctions are skipped, not followed, in line with the browser and selection rules: they can't be selected, an in-workshop target is found at its real path, and an outside target is never reached. Navigation from results (folder double-click, Up, Show in folder) is explicit navigation, so it clears the search and changes Save to. Results are capped at 500 with a warning. Name-tag drops are refused while results are shown, because tags belong to the folder on screen.
- **Verified (Python 3.12, Windows 10, no Qt):** `python -m unittest tests.test_search -v`, 6 tests passing, on a disposable workshop with `Lectures/Topic.pdf`, `Readings/topic.pdf` and `Readings/Deep/TOPIC notes.txt`. `toPIC` returns all three plus the `Topics` folder, in stable relative-path order. `.hidden/` and `.topic-draft.pdf` are skipped, a junction to an outside folder is skipped, and an in-workshop junction is not followed twice. Selecting a result keeps the current folder and the `build_request` destination, and the selection survives the redraw. `search_is_current` rejects an older seq, a changed query, another workshop and no workshop, and a cancelled search reports `cancelled`. A rescan sees an added and a deleted file. An unreadable folder produces the incomplete-results warning. That warning was also observed with a real `icacls /deny` (RD) on a disposable folder: `Results may be incomplete: 1 folder could not be read (Locked).` The existing `test_selection`, `test_drag_drop`, `test_organizing` and `test_name_tags` suites still pass.
- **Qt interaction, verified later during P3-M2:** this ran in a throwaway Python 3.12 venv with PySide6 6.12.0 and pypdf 7.0.0, offscreen, with the Chrome launch stubbed, on a disposable workshop holding `Lectures/topic.pdf`, `Readings/topic.pdf` and a hidden copy. It covered:
  - typing `TOPIC` (debounced) lists the two relative paths in order, without the hidden copy;
  - two quick searches end on the newer query;
  - clicking a result selects it, and Save to stays `Labs`;
  - double-clicking a PDF result opens it in Chrome without changing the selection;
  - clearing the box returns to `Labs` with the selection kept;
  - **Show in folder** navigates to `Lectures` and ends the search;
  - Refresh during a search shows a file that was added and drops one that was deleted.

  The script was a one-off check and is not in the repository.
- **Limitations:** names only (no document content). The walk is not cached, so each query rescans the workshop. A cancelled walk stops at the next folder boundary.

### P3-M2 — PDF page selection end to end (implemented 2026-11-09)

- **Built:** `pdf_pages.py` (Qt-free parsing, validation, inspection, subset writing, prompt mapping text). `workshops` keeps `state["pages"]` with `set_pages`; deselect and Refresh drop a PDF's setting, and `reconcile` remaps it after a move. `ui.build_request` adds `page_selections` (a snapshot), and `make_me_status` blocks bad pages and unreadable PDFs. The Pages field and note are on each selected PDF row, with page counts worked out on a `CallWorker` thread. `generation.generate` keeps one `lnp_inputs_*` temp folder for the whole job. `inputs.prepare_inputs` inspects every PDF, writes subsets in original mode, and in Efficient mode filters the cached full-file units. In `gemini_client`, the source fingerprint is checked, then the subset's bytes are checked against their own fingerprint, sent and counted toward the size cap. The mapping goes into the source index (`tasks.assemble_prompt`) and into each source label. Details are in `architecture.md`.
- **Decisions:** a choice naming every page is treated as All pages, so no subset is made. Every PDF, including All pages originals, is now inspected with pypdf before sending, so encrypted or unreadable PDFs fail before any API call. Unparseable text is passed through to generation, which rejects it by filename (the UI already keeps Generate off for it). Page settings exist only for selected PDFs. Derived PDFs are not cached.
- **Verified:** this ran in the same venv. `python -m unittest tests.test_pdf_pages -v` passes all 14 tests. The client stub calls the real `gemini_client._source_items`, so the checks below are on the bytes and text that would actually be sent:
  - **Original mode, pages `1, 3-4` of a 5-page PDF:** the document has three pages, whose text is PAGE-1, PAGE-3 and PAGE-4. `page_map` is `[1, 3, 4]`, and the label includes `1→1, 2→3, 3→4`. The prompt's source index says `only original pages 1, 3-4 of 5`. The source fingerprint matches the original file and differs from the payload's.
  - **Original pages 3 and 8:** in original mode the payload's pages are 3 and 8, and the label includes `1→3, 2→8`. In Efficient mode the markers are `[… - page 3]` and `[… - page 8]`.
  - **Efficient mode:** the units are `[1, 3, 4]` and no page-2 text is sent. A TXT file in the same request still goes through. A second selection, `[2, 5]`, is served from the conversion cache (`hit`) with the right units.
  - **Scans:** with a scan on page 2, choosing `1, 3-4` asks nothing. Choosing `1-2` asks about page 2, and **Process original** then sends a 2-page subset. Cancel returns `cancelled` with zero client calls, and the temp folder is gone.
  - **Bad input:** `9`, `4-2` and `[0, 1]` fail with `invalid_pages` naming `Lectures/notes.pdf`, with zero calls. An encrypted PDF fails with `pdf_encrypted`, with zero calls.
  - **Changes before sending:** editing the source gives `source_changed`, and tampering with the subset gives `payload_changed`. The temp folder is removed both times.
  - **Legacy request:** a request without `page_selections` sends the original bytes unchanged.
  - **Settings:** a captured request is not affected by later edits. Browsing and search leave settings alone, a folder move remaps them, deselecting drops them, and a state without `pages` still works.
- **Offscreen Qt check, same run as the P3-M1 interaction above:**
  - a PDF selected from search shows `All 5 pages`;
  - `3-4, 1, 4` shows `Pages 1, 3-4 (3 of 5)`;
  - `2-9` on a 3-page PDF shows the out-of-range message in red, and Generate turns off;
  - an empty field shows `All 3 pages`, and Generate turns back on;
  - after clearing search, the selection and Pages text are kept;
  - `build_request` captures `{…/Lectures/topic.pdf: [1, 3, 4]}` with destination `Labs`;
  - Refresh drops a deleted PDF's setting.

  18/18 checks passed. The script was a one-off check and is not in the repository.
- **Other tests:** the existing `test_search`, `test_selection`, `test_drag_drop`, `test_organizing`, `test_name_tags`, `test_executor`, `test_super_wrap` and `test_downloads` suites pass.
- **Blocked (environment):**
  - **LaTeX compile tests:** three `tests.test_latex_pipeline` tests that compile with lualatex fail on this PC, and so does the sandbox test, which calls `compile_document` directly and doesn't involve any P3-M2 code. MiKTeX tries to rebuild `lualatex.fmt` from inside the restricted compiler process, and Windows refuses (`CreateProcess`, error 1816, "Not enough quota"). The non-compiling pipeline tests pass. Rebuilding the format once outside the app (`miktex formats build lualatex --engine luahbtex`) should unblock them; this was not done here.
  - **Real Gemini run:** no real Gemini request was made.
- **Limitations:**
  - A Pages field is committed with Enter or Tab (on focus loss), not while typing.
  - Page counts are cached per file modification time for the session.
  - The UI recounts PDFs it has not seen. On this PC the first `import pypdf` on a worker thread is held up when the GIL isn't released. The real app's `exec()` loop releases it, and the offscreen check passed once the harness did the same.
