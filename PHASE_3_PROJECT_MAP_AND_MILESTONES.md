# Late Night Pal — Phase 3 workshop study tools and milestones

## Purpose and status

Phase 3 plans four features for the existing Windows/PySide6 app. **P3-M1 (workshop search), P3-M2 (PDF page selection), P3-M3 (persistent generation history), P3-M4 (reuse history and reconcile paths) and P3-M5 (persistent study progress) are implemented** (see Implementation notes); P3-M6 (integrated packaged demo and handoff) is pending.

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
| P3-M3 — Persistent generation history (**implemented**; verified with stubbed Gemini/LaTeX, no real generation) | P3-M2 | Versioned successful-job records, History UI, open actions and metadata retry | Generate a small output and reopen the app. Its task, settings, input page choices and final paths appear. Simulate a metadata-save failure after publication and verify the UI reports saved PDFs; retry saves one record without regenerating. A failed or cancelled generation creates no successful entry. |
| P3-M4 — Reuse history and reconcile paths (**implemented**; verified with stubbed Gemini/LaTeX) | P3-M3 | Restore-settings action, source-change checks and organizer integration | Reuse a saved request and confirm its page ranges and destination. Move an output folder through Organize and open the remapped history entry. Delete an input and verify reuse identifies it for correction. Corrupt metadata shows a warning and preserves the original record file. |
| P3-M5 — Persistent study progress (**implemented**; verified with stubbed Gemini/LaTeX) | P3-M4 | Daily-plan completion controls and totals | Open a two-day plan, mark two of six items complete, restart and see `2/6`. Generate another plan and confirm independent completion. A missing output is visibly unavailable. A failed save returns the checkbox to its saved state. |
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

Add verified outcomes, relevant checks and remaining limitations as each milestone is implemented. P3-M6 is pending.

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
  - **LaTeX compile tests:** three of the six `tests.test_latex_pipeline` tests fail on this PC. Two are generation tests that compile with lualatex; the third is the sandbox test, which calls `compile_document` directly and doesn't involve any P3-M2 code. (Corrected 2026-11-09 during P3-M4; this was first reported as three generation tests plus the sandbox test.) MiKTeX tries to rebuild `lualatex.fmt` from inside the restricted compiler process, and Windows refuses (`CreateProcess`, error 1816, "Not enough quota"). The non-compiling pipeline tests pass. Rebuilding the format once outside the app (`miktex formats build lualatex --engine luahbtex`) should unblock them; this was not done here.
  - **Real Gemini run:** no real Gemini request was made.
- **Limitations:**
  - A Pages field is committed with Enter or Tab (on focus loss), not while typing.
  - Page counts are cached per file modification time for the session.
  - The UI recounts PDFs it has not seen. On this PC the first `import pypdf` on a worker thread is held up when the GIL isn't released. The real app's `exec()` loop releases it, and the offscreen check passed once the harness did the same.

### P3-M3 — Persistent generation history (implemented 2026-11-09)

- **Built:**
  - `history.py` (Qt-free): `build_record`, `record_problem`, `load`, `save_record`, `resolve`, `view`. The version-1 record schema, the storage location, partitioning and atomic writes are in `architecture.md`.
  - `generation.generate`: allocates `generation_id` (or takes `request["generation_id"]`). Right after publication it adds `history_record`, built from the source and rendered-document metadata while that still exists, before the temp folders are removed.
  - The UI `Worker` saves the record after a successful job, still off the UI thread. `generate` itself never writes history, so `--summarize` and injected-dependency runs are unchanged.
  - The **History** mode has rows, outputs, **Open document**, **Open output folder** and **Reload**. **Retry saving history** appears with `pending_history`.
- **Saved for P3-M4/M5:** each record holds the validated task parameters, Efficient, the captured destination, every input's relative path, original-source fingerprint, size, MIME type, mode, page count and normalized page choice, and each output's `document_id`, role, day and final relative path. P3-M4 can remap these paths with confirmed moves and check fingerprints. P3-M5 can key progress on `generation_id` + `document_id`.
- **Decisions:**
  - History is stored per workshop, in a file named by a hash of the normcased canonical root, so a workshop's name never appears in a file name.
  - Single-file outputs record `day: null`, because validation normalizes day 0 that way.
  - Loading never writes. An unusable file is moved aside only when the next save happens, so the original bytes are always kept.
  - Pending retries live for the current app session only (as specified). They are not persisted across restarts.
- **Verified:** this ran in the same throwaway venv (Python 3.12, PySide6 6.12.0, pypdf 7.0.0). Gemini and lualatex were stubbed, and publication was real.
  - **`python -m unittest tests.test_history -v`, 7 tests passing:**
    - two Summary runs into `Revision` record `Revision/summary.pdf` and `Revision/summary (2).pdf`;
    - each record has the right task, `Simple` style, Efficient off, destination and output root `Revision`, the `[1, 3, 4]` page choice with `page_count` 5, and the original PDF's own sha256;
    - the stored file contains no LaTeX, source text, raw response or payload data;
    - a fresh `load` lists the two newest first;
    - a two-day plan records six outputs with role and day under `Revision/Week 5 (2)/Day 01/…`;
    - two workshops get separate files and histories, and a workshop with no file has an empty history;
    - a forced `PermissionError` on save keeps `status: ok`, and the status text starts `Saved:` and says History was not updated. Two retries then leave exactly one record with the same id, with no additional client calls;
    - a bad response, a failed publish and a cancelled scan decision produce no record and no file;
    - bad JSON and `version: 99` produce a warning naming the file and leave it unchanged. The next save keeps the original bytes in `*.unreadable-*.json` and writes a fresh file;
    - one invalid record is hidden with a count;
    - `resolve` rejects `..`, an absolute path, backslashes, an empty path and a path through a junction, and reports a deleted output as `missing` / `(1 unavailable)`.
  - **Offscreen Qt check, 11/11:**
    - History loads off-thread with the newest entry first, showing `pages 1, 3-4`, `Standard style · Efficient off · Save to: Revision` and `1 PDF in Revision`;
    - the older entry's deleted output is greyed as unavailable, and Open document is off for it;
    - Open document launches Chrome on `Revision/summary (2).pdf`, and Open output folder opens `Revision`;
    - deleting the file before clicking gives a message with no launch, and the view reloads to mark it;
    - a load for workshop A still running when workshop B opens never shows A's entries;
    - the real `job_finished` slot, given a failed save, reports the saved PDF and shows Retry. After opening another workshop, Retry saves the entry once to its own workshop with no Gemini call, and the button hides.

    The script was a one-off check and is not in the repository. The P3-M1/M2 offscreen check still passes 18/18, and the 64 existing non-LaTeX tests still pass.
- **Not verified (environment):**
  - **Real Generate:** no real Gemini plus lualatex generation ran. The same MiKTeX `lualatex.fmt` rebuild failure recorded under P3-M2 still blocks compiling on this PC, so publication was exercised with stubbed rendering.
  - **Restarting the app:** this was simulated by a fresh `load()` from disk and a new window. The packaged exe was not run.
- **Limitations:**
  - Opening a different workshop's History needs that workshop to be open.
  - There is no delete or clear for History entries.
  - Organizer moves do not yet remap stored paths; that is P3-M4. A moved output simply shows as unavailable.

### P3-M4 — Reuse history and reconcile paths (implemented 2026-11-09)

- **Built:**
  - `history.py` (all Qt-free):
    - `confirmed_moves`, `remap_record`, and `reconcile` (serialized, atomic, limited by `before`);
    - `now_stamp` (microsecond times);
    - `check_input` and `check_reuse`;
    - `save_record` is now first-write-wins.
  - `ui.py`, Qt-free helpers: `reconcile_history`, `retry_metadata`, `apply_reuse`, `reuse_blockers`, and `make_me_status(…, reuse)`.
  - `ui.py`, window changes:
    - `OrganizeWorker` reconciles History after the file operations;
    - `organize_finished` remaps pending records, records `pending_reconcile` and reports it;
    - **Retry saving history** handles both kinds of pending work;
    - `busy()` includes the retry;
    - History has **Reuse settings**, keeps the selected entry by `generation_id`, and has the Make me reuse panel with explicit corrections.
- **Decisions:**
  - Reuse replaces the current selection.
  - Missing inputs are restored as `[missing]` entries, so the user removes them explicitly; unsafe inputs are never added to the selection and need **Leave it out**.
  - When the saved task settings are invalid, the widgets are left as they are and Generate waits for **Use settings shown**.
  - An unavailable destination is never replaced automatically.
  - Reuse is cleared when Generate starts or another workshop opens.
  - A changed file's acceptance applies to the file as re-checked at that moment; the pipeline revalidates again at Generate.
  - Reconcile skips records completed after the move. This matters for a delayed metadata retry, when a new file may exist at the old path. Record and move times now carry microseconds, so a record completed in the same second as the move is no longer remapped. That same-second case was found while writing the tests.
  - Organizer actions wait for a running History retry, and a retry waits for running jobs, so a retry can never run against paths an organizer action is changing.
- **Verified:** in the same throwaway venv (Python 3.12, PySide6 6.12.0, pypdf 7.0.0).
  - **`python -m unittest tests.test_reuse -v`, 9 tests passing:**
    - Reuse restores the selection, `1, 3-4`, `Simple`, Efficient on and `Revision` from another folder, and `build_request` matches, with zero client calls.
    - A changed 2-page PDF reports `changed` and `has 2 pages; page 4 is out of range`. A deleted TXT stays `[missing]`, and a renamed destination reports unavailable while the current folder stays put. Generate stays blocked until each is corrected. **Accept current file** re-checks pages (now valid for `1-2`), and the stored record is byte-for-byte unchanged.
    - A junction input is `unsafe` and an invalid style is a `task_problem`; both block until handled explicitly, and another workshop's reuse is ignored.
    - A real organizer move of `Revision/Week 5` to `Archive` remaps `output_root` and all six output paths (ids, roles and days unchanged). Every output resolves as available, and the other entry is untouched.
    - A real move of the input PDF plus a real tag rename records `Archive/notes_1.pdf` with the same pages and fingerprint, and Reuse sees it as `ok`.
    - In a run where one move completed, one failed, one was unattempted, plus a `copied_source_kept` and a `copied` item, only the completed move counts.
    - A stale save of the pre-move record returns `already_saved` and keeps the new paths. A pending, unsaved record remapped in memory is saved with the new paths.
    - A forced write failure after a real move leaves the file moved and History unchanged. `retry_metadata` then updates History with `organizing.execute_plan` never called and zero client calls, and a later record at the old path is not touched.
    - A corrupt file is left byte-identical with a warning naming it.
  - **Other tests:** all 80 non-LaTeX tests pass.
  - **Offscreen Qt check, 16/16:**
    - the real **Reuse settings** button restores the Pages note `Pages 1, 3-4 (3 of 5)`, task `summary`, `Simple`, Efficient on and `Save to: Revision`, switches to Make me, and leaves Generate enabled with no job and zero calls;
    - after editing the PDF, Generate is off with `…changed since this generation…`, and **Accept current file** re-enables it;
    - a real `handle_drop` move of `Revision/Week 5` to `Archive` reloads History, keeps the same entry selected and remaps every output. Open output folder and Open document use `Archive/Week 5/…`;
    - with History writes forced to fail, a real move of `extra.txt` reports that History paths were not updated and shows Retry. Retry updates the path with no file changes and zero calls.

    The P3-M3 History check (11/11) and the P3-M1/M2 check (18/18) still pass. These were one-off scripts and are not in the repository.
- **Not verified (environment):** three of the six `tests.test_latex_pipeline` tests still fail. Two are generation tests that compile with lualatex, and the third is the sandbox test. All fail on the same MiKTeX error, re-checked today: `lualatex.fmt` rebuild, `CreateProcess` error 1816 "Not enough quota". So no real generation ran for P3-M2 through P3-M4; publication was exercised with stubbed rendering. No real Gemini call was made.
- **Limitations:**
  - An unsaved retry record is kept only in memory, so it is lost if the app closes.
  - Moves made outside the app, for example in Explorer, are not followed; those entries show as unavailable.
  - Reuse restores one entry at a time and doesn't merge it with the current selection.

### P3-M5 — Persistent study progress (implemented 2026-11-09)

- **Built:**
  - `study_progress.py` (Qt-free): `manifest`, `totals`, `daily_plans`, `describe_plan`, `load`, `set_done`, `view`.
  - `ui.py`: a **Progress** mode. It has a plan chooser, per-day groups with checkboxes and `n/m` counts, the plan total, **Open document** and **Reload**. Loads and saves run through the existing `run_call` workers.
- **Decisions:**
  - Progress has its own versioned file per workshop, named like the History file but kept in a `progress` folder. Each module only ever writes its own file, so a progress save cannot overwrite History records or reconciled paths, and History reconciliation never touches progress.
  - Items come only from the History record's outputs (`document_id`, role, day), so moves keep ticks without any progress rewrite.
  - One save per item at a time: the item is disabled until its save answers. A response updates only its own item, so out-of-order answers can't overwrite newer ticks.
  - Unavailable items stay checkable and counted.
  - Plans are identified by output folder plus completion time. The folder carries the plan name and any ` (2)` suffix.
- **Verified:** in the same throwaway venv (Python 3.12, PySide6 6.12.0, pypdf 7.0.0). Gemini and lualatex were stubbed; publication and organizer moves were real.
  - **`python -m unittest tests.test_study_progress -v`, 11 tests passing:**
    - two days × Notes / Sample questions / Checklist start at 0/6;
    - two ticks give `2/6` with days `1/3` and `1/3`, also after a fresh load, and unticking one gives 1;
    - a same-name plan (`Revision/Week 5 (2)`) starts at 0 while the first keeps its tick;
    - a record from before progress existed loads with no file and no warning;
    - a forced write failure raises "…shows the last saved value", and the file is byte-identical;
    - 18 concurrent saves on six items leave all six saved;
    - a real organizer move remaps every path to `Archive/Week 5/Day 0…`, all available, with the tick kept;
    - a deleted checklist shows `missing` but still counts, `1/6`;
    - a duplicate `document_id` and a non-plan output give two warnings, are counted once, and stray entries are ignored;
    - a corrupt file is left as is with a warning naming it; the next save keeps it as `*.unreadable-*.json`;
    - a progress save leaves the History file byte-identical, and History reconciliation leaves the progress file byte-identical;
    - workshops are separate.
  - **Other tests:** all 91 non-LaTeX tests pass.
  - **Offscreen Qt check, 14/14:**
    - the real Progress mode lists the two same-name plans newest first and leaves the Summary out;
    - each plan shows `Day 1 · 0/3`, `Day 2 · 0/3` and six checkboxes;
    - an item is disabled while its save runs; two ticks give `2/6`, `Day 1 · 1/3`, `Day 2 · 1/3`, and the other plan stays at 0/6;
    - a reload (as after a restart) restores 2/6;
    - a forced write failure puts the box back and keeps 2/6 with the error shown;
    - with a 0.6 s delayed save, a second click on the pending item is refused, switching plans keeps the other plan at 0/6, and the result matches disk;
    - switching to workshop B during a delayed save shows only B's plan at 0/6, while A's save still lands in A;
    - a real `handle_drop` move of `Week 5` to `Archive` reloads with the new paths. Open document launches `Archive/Week 5/Day 01/notes.pdf`, with completion unchanged and zero Gemini calls;
    - after deleting that PDF it shows as unavailable, still ticked and counted (`4/6`), and Open document is off.

    The P3-M4 (16/16), P3-M3 (11/11) and P3-M1/M2 (18/18) checks still pass. These were one-off scripts and are not in the repository.
- **Not verified (environment):** no real Gemini or lualatex generation ran. Three of the six `tests.test_latex_pipeline` tests still fail on the MiKTeX `lualatex.fmt` rebuild (error 1816 "Not enough quota"), as recorded under P3-M2 and P3-M4. The packaged exe was not rebuilt or run; that is P3-M6.
- **Limitations:**
  - Progress has no reset or clear-all button.
  - Deleting a plan from History isn't possible, so its progress stays.
  - Completion is a manual marker only, as specified.
