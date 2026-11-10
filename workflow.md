# Application workflow

The proposed Phase 3 workflow and acceptance walkthrough are in [PHASE_3_PROJECT_MAP_AND_MILESTONES.md](PHASE_3_PROJECT_MAP_AND_MILESTONES.md). P3-M1 (workshop name search), P3-M2 (PDF page selection), P3-M3 (generation history) and P3-M4 (Reuse settings, History after organizer moves) are implemented; study progress is pending.

Current state: M7. The same flow runs from the packaged `Late Night Pal.exe` (README "Windows handoff build"). It was rehearsed with a fresh copy of `demo/Biology Demo Workshop`; see the README demo sequence. Open a workshop, select PDF, PPTX, DOCX, TXT or MD files across folders, choose one of eight tasks, optionally turn on Efficient, and generate into the current folder. Component names match `architecture.md`.

Running example: workshop `Biology Workshop/` containing `Lectures/topic.pdf` (photosynthesis), `Readings/topic.pdf` (plate tectonics), and `Revision/` with an existing `summary.pdf`.

## 1. Open a workshop

1. **Desktop UI** start page: "Welcome to Late Night Pal", **Recent Workshops** (full paths from `workshops.load_recents()`), **Open Workshop**, **Create Workshop**.
2. **Open Workshop** opens a folder dialog. **Create Workshop** asks for a parent folder and a name. Clicking a recent workshop opens it. If its folder is gone, a dialog offers **Open another folder...** or **Remove from list**.
3. **Workshop** `open_workshop()` resolves the root and records it in `%LOCALAPPDATA%\late_night_workshop\recents.json`.

## 2. Select inputs across folders

1. Double-click the folder-icon row `Lectures` to open it (a single click selects the folder), then tick `topic.pdf` (or click its name) → `toggle_selection()`. The row turns blue and **Selected Inputs** shows `Lectures/topic.pdf` with a **Remove** button. Double-clicking `topic.pdf` instead opens it in Chrome (`ui.open_pdf`) and leaves the selection as it was.
2. **Up**, the `Readings` folder, `topic.pdf` → Selected Inputs lists both relative paths.
3. The selection survives navigation, mode and task changes. Ticking a folder's checkbox selects the folder without opening it. Any file type can be selected (types Make me can't use are greyed). **Remove** deselects an entry from any view, even one deleted on disk; it never deletes the file. **Ctrl+click** a row toggles it (a folder too, without opening it); **Shift+click** adds every row from the last clicked one to this one. A plain click never clears other selections.
4. **Up**, the `Revision` folder: this is the destination captured at Generate.

**Pages (P3-M2).** Each selected PDF in **Selected Inputs** (picked in the browser or from search) has a **Pages** field showing `All pages`, with a note such as `All 5 pages`. Type `3-4, 1, 4` and press Enter or Tab → `Pages 1, 3-4 (3 of 5)`. Numbers are the PDF's physical pages from 1. `9`, `4-2`, `0` or `x` make the note red with the file's name and turn Generate off; clearing the field means All pages again. The setting stays across navigation and search, follows the PDF through an Organize move, and is dropped when the PDF is deselected. Generate captures it. Efficient off sends a temporary PDF with only those pages, labelled with the mapping to the original page numbers. Efficient on sends only those pages' text, with markers such as `[Lectures/topic.pdf - page 3]`. Only the chosen pages count for the scan check, and **Process original** sends the same subset. The temporary PDF is deleted when the job ends, however it ends.

**Make me eligibility.** If the selection holds a folder, an unsupported type, an unreadable file or a missing entry, it is shown in red, the note above Generate names it and why, and Generate stays off. Remove those entries: other selections, task, Days, Folder name, style and Efficient are unchanged. Generation still rechecks files-only at its boundary.

**Search (P3-M1).** Type `topic` in the search field above the browser. After a short pause the browser lists every matching file and folder name in the workshop by relative path: `Lectures/topic.pdf`, `Readings/topic.pdf` (`search.search()` on a worker thread; a slower, older search never replaces newer results). Click a result to select it (the same shared selection), double-click a PDF to open it in Chrome or a folder to open it, or **Show in folder** to jump to its folder. The **Save to** folder does not change while results are shown; only navigating does. Clear the box (✕) to return to the current folder with the selection intact. Hidden entries and links are not listed; a folder that can't be read is named in an "incomplete" note.

**Refresh** (beside Up) rescans the folder and drops selected entries that no longer exist, naming them in the status, and reruns an active search. Ordinary redraws never drop selections. ## Organize (P2-M3; use a disposable workshop)

Each button snapshots root, current folder and selection at the click (`organizing.capture_request()`, like Generate's `build_request()`), validates the whole plan, then runs it off the UI thread. The status lists every item as done, FAILED (with the reason) or not attempted; nothing is overwritten.

1. Select `Lectures/a.pdf` and `Labs/b.pdf`, open `Coursework`, **Wrap**, name `Batch` → `Coursework/Batch/a.pdf` and `b.pdf`; the selection follows them.
2. Select `Batch`, **Rip** ("Move each selected folder's contents up one level.") → `Coursework/a.pdf`, `Coursework/b.pdf`, and `Batch` is removed. It does not restore `Lectures`/`Labs`. Rip is refused, with the clashing names, if a child would collide with an existing entry.
3. Select `a.pdf`, **Copy** (file references only; also pasteable in File Explorer), then **Paste** in the same folder → `a (2).pdf`. Pasting a folder into itself or below itself is refused.
4. Select `a (2).pdf`, **Delete**, confirm → it goes to the Recycle Bin. If the drive has no Recycle Bin, nothing is deleted.
5. Cut files in File Explorer, then **Paste** here and confirm. If an item fails, the status shows which moved, which failed and which were not attempted; the rest stay where they were. Paste the same cut again to finish: moved items are skipped. Network (UNC) sources are refused for cut; copy them instead.

6. Select `Cal_1_assignment_1.pdf`, `Cal_1_Note_1.pdf`, `Cal_1_assignment_2.pdf` (and optionally `Cal_2_assignment_1.pdf` or a folder), open the destination folder, **Super Wrap**, name `Calculus`. The confirmation lists every source → destination. The result is `Calculus/Cal_1/assignment/1.pdf` and `2.pdf`, `Calculus/Cal_1/Note_1.pdf`, and singletons and folders directly in `Calculus` with their names unchanged. A name clash anywhere in the new tree, or a name Windows forbids, refuses the whole run before anything moves.

## Drag and drop (move and copy)

Same engine as the buttons (`organizing.plan_drop` → `plan_action` → `OrganizeWorker` → `execute_plan` → `reconcile` → refresh). No dialog; the status line reports the result.

1. In the root, select `a.pdf`, Shift+click `c.txt` (selects `a.pdf`, `b.pdf`, `c.txt`), then drag any of them a few pixels: the drag shows "-> Move 3 files". Hover `[folder] Lectures`: it turns amber. Drop → status "Moved 3 files to Lectures."; the rows leave the root and the selection follows them.
2. Drag an **unselected** row: only that row moves. Drag onto **Up** to move it to the parent folder, or onto the dashed "Drop here…" box (or empty space in the list) for the folder you're viewing.
3. Hovering the file's own folder, the dragged folder itself or a folder inside it shows the forbidden cursor; a drop there does nothing. If a name is taken the moved entry becomes `a (2).pdf`; nothing is overwritten.
4. Open **Recent downloads**, drag a row (or a ticked row, which carries every ticked row) onto `[folder] Labs` → "+ Copy: hw1.pdf", then "Copied 1 download to Labs." The original stays where Chrome saved it; Chrome's history is not touched. A download deleted since the list loaded is refused ("Copy not done: … is no longer available.") and the list reloads.
5. Press Esc during a drag → "Drag cancelled. Nothing was changed." While a move or copy runs, new drags are refused until it finishes.

## Recent downloads bin (P2-M6)

**Recent downloads** (above Name tags; its label shows how many) lists files Chrome finished downloading in the last hour by Chrome's completion time, including ones saved outside Downloads or finished before the app started. Rows show filename · folder · time. Cancelled, unfinished and since-deleted downloads are left out. The list refreshes when the workshop opens, when you open the bin, on Refresh and after a copy; it never polls. Tick entries, open the destination folder, and press **Copy to current folder**, then confirm: the files are copied there with Paste's naming (`notes (2).pdf` if the name is taken), and the originals stay. If Chrome's history can't be read, the bin says why and stays empty.

## Name tags (P2-M5)

Below the browser, type `assignment` and press **+**: a chip appears for the **current folder** only (at most six; duplicates in any case and invalid names are refused). Drag the chip onto a file in the browser: the file becomes `assignment_1.pdf` (extension kept), the next drop `assignment_2…`, in drop order. The chip stays. Dropping on a folder or empty space renames nothing and uses no number; a failed rename gives its number back. Numbers already used by a file called `assignment_N` (any extension) are skipped, and nothing is overwritten. Removing a chip and adding it again continues the numbering. Tags and counters persist across restarts, follow folders moved by Wrap, Super Wrap, Rip or a cut Paste (including tagged folders inside them), and are cleared for folders Delete really removed. A recreated empty folder starts at 1.

## 3. Choose a task and parameters

- **Output type → Single file**: Task is Checklist, Notes, **Summary** (default), Answer key, One-page cheat sheet or Sample questions, plus **Language style** (Technical / **Standard** / Simple).
- **Output type → Study plan**: Task is Make schedule or Make daily study plan, plus **Days** (any positive whole number, default 2) and **Folder name** (the placeholder shows the default, `Study Schedule` or `Daily Study Plan`).
- **Efficient** (both output types, default off), with the note directly below it: "Converts files to text before sending them to Gemini. This can be much cheaper for some files, but diagrams, equations, tables, and formatting may be lost."
- **Generate** → `ui.build_request()` snapshot (including `efficient`) → `tasks.validate_parameters()`. A bad folder name such as `bad/name` shows an error in the status line, and no job starts.

## 4. Generate (example: Make daily study plan, Days = 2)

A `Worker` runs `generation.generate(request)` on a `QThread`; Generate is disabled until it ends.

1. **Registry** `validate_parameters()` and **Workshop** `validate_paths()`.
2. **Renderer** `check_runtime()` and **Publisher** `check_destination()`. Missing LaTeX stops here, before any Gemini call.
3. **Inputs** `prepare_inputs()` → two original-PDF source records (Efficient off). See section 5 for Efficient and scans.
4. **Registry** `resolve_task()` → the prompt is `daily-study-plan.md` (with `{days}` = 2), plus `styles/standard.md` and `format.md` (LaTeX body rules with the allowed packages). The schema requires exactly 6 documents, each `{role, day, title, latex_code}`.
5. **Gemini client** `generate_content()` → **one** request containing both labelled PDFs. Observed: 405 s.
6. **Validation** `validate_bundle()` → requires exactly (day 1..2) × (notes, sample-questions, checklist), a `latex_code` on each, different notes on each day, and an allocation covering days 1–2 that uses both sources. A failure here rejects the whole bundle (one bundle repair). Then `document_problems()` checks each body for forbidden LaTeX (preamble, file, Lua and catcode commands).
7. **Renderer** `render_bundle()` → each body is wrapped in the Python preamble (allowlisted packages, title, subtitle, read guard) and compiled by lualatex in a restricted process in a temp folder (no key in its environment; on Windows a job object). Every document is compiled even if one fails.
   Daily PDFs' subtitles name that day's sources from the allocation (`Day 01 · From Lectures/topic.pdf · <date>`).
8. **Publisher** `publish()` → builds `.lnp-staging-*` in `Revision/`, then renames it to `Daily Study Plan/` (or `Daily Study Plan (2)/` if that exists) with `Day 01/` and `Day 02/`. Observed: under 0.1 s.
9. **Desktop UI** shows `Saved 6 PDFs in …\Daily Study Plan:` with the relative list. PDFs stay in the output folder without opening. **Open document** opens the first PDF on request; **Open output folder** opens `Daily Study Plan/`. The worker then adds the result to History (`record_history()`, after publication only) and the status ends with `Added to History.`
10. **History** (third mode button) lists this workshop's successful generations newest first: `Make daily study plan · 2026-11-09 17:48`, the inputs with any `(pages 1, 3-4)`, style/days, Efficient, Save to, and `6 PDFs in Revision/Daily Study Plan`. Pick an entry to see its outputs (`Day 01/notes.pdf · notes, day 1`); **Open document** / **Open output folder** open the recorded final paths after rechecking them. A moved or deleted output shows `(unavailable: moved or deleted)` and can't be opened. Another workshop's history never appears here. If History can't be saved (for example the file is locked), the status still lists the saved PDFs, says History was not updated and shows **Retry saving history**, which saves the same entry once without contacting Gemini. A failed or cancelled job adds nothing.
11. **Reuse settings** (History, P3-M4) checks the chosen entry against the files as they are now (off the UI thread), then switches to Make me with its inputs, Pages, task and settings, Efficient and Save to restored. Nothing is generated until **Generate**. Problems are named and keep Generate off until you choose: a missing input stays in Selected Inputs as `[missing]` until you remove it; a file whose contents changed needs **Accept current file** (its pages are re-checked against the current page count); an unavailable Save to folder needs **Save to current folder**; an input now outside the workshop or behind a link needs **Leave it out**; bad pages use the normal red Pages note. The History entry itself is never edited.
12. **History after Organize.** Moving `Revision/Daily Study Plan` to `Archive` (drag, Wrap, Rip, Super Wrap, cut-Paste or a tag rename) updates the entry: `6 PDFs in Archive/Daily Study Plan`, and Open document / Open output folder use the new paths. Moved inputs keep their page choices and fingerprints. Only completed moves count; copies keep the entry pointing at the original, and deletions just show as unavailable. If the History file can't be updated, the status says the files were changed and History wasn't, and **Retry saving history** repeats only the History update.

Other layouts:
- **Make schedule** writes `Study Schedule/{schedule,file-guide,checklist}.pdf`. Validation requires a `Day N` heading for every day and a file guide that names every source. Observed: Gemini 290 s, render 7.9 s.
- **Single file** tasks write `<task>.pdf` (`summary (2).pdf` etc. on collision).
- **Answer key** keeps source labels such as `2(b)` and marks unclear questions `FLAGGED:`.
- **One-page cheat sheet**: Gemini lays out the page (columns, type size). The page count of the compiled PDF is checked; if it is over one page, that document gets its one repair ("The compiled PDF has 2 pages…"), and if the repaired one is still too long the job fails with `page_limit_exceeded` and publishes nothing.

### Failures and retry (M5)

Nothing is published until every document has validated and compiled, and the temp folder and any staging folder are always removed. The selection, task, Days, Folder name, style and Efficient setting stay as they were, and Generate is enabled again.

- **Malformed response** (for example, day 2's checklist missing): the status shows `Gemini: Gemini's response was unusable (missing checklist for day 2); asking Gemini once to fix it...`. If the repair is also incomplete, it ends with `Checking the request or Gemini's response failed: … (also after one repair attempt)`, then `Nothing was saved…` and `Click Generate to try again…`. That's two Gemini calls in total; no compile runs, and nothing is written.
- **A document fails** (for example Day 02/sample-questions.pdf has an unclosed environment, uses a forbidden command, or the cheat sheet runs to two pages): the other documents still compile, then the status shows `Gemini: Couldn't compile Day 02/sample-questions.pdf; asking Gemini once to fix that document...`. Only that document's `latex_code` and the LaTeX error lines are sent, with no sources; documents that passed are not regenerated. If the repaired body passes, all six PDFs are published together. If it fails again, the job ends with `Local PDF compilation failed: Couldn't compile Day 02/sample-questions.pdf (also after one repair attempt).` and the LaTeX log path in `%LOCALAPPDATA%\late_night_workshop\logs\`. The PDFs that had compiled were only in the temp folder, so nothing appears in `Revision/`.
- **Retry** from the same window: the full bundle lands in the next free folder, for example `Daily Study Plan (2)/` with all six PDFs, while an existing `Daily Study Plan/` stays byte-for-byte unchanged.
- **Network error:** one automatic retry, shown as `Network problem while generating; retrying once...`. Quota, auth and size-limit errors aren't retried; they show what to fix (for example `Wait a minute, then click Generate again.`).

## 5. Efficient, mixed formats and scans

Example selection: `Lectures/topic.pdf` (2 text pages), `Readings/topic.pdf`, `Slides/deck.pptx` (2 slides).

- **Efficient off:** both PDFs go as originals (`Source 1: Lectures/topic.pdf` + document item, `Source 2: Readings/topic.pdf` + document item). Gemini isn't configured to take PPTX originals, so `deck.pptx` goes as attributed text, and the status line says `Slides/deck.pptx was converted to text locally …`.
- **Efficient on:** `converters.convert()` extracts each file (cached in `%LOCALAPPDATA%\late_night_workshop\conversions\`, keyed by content hash and converter version). The request carries one text item per file: `Source 1: Lectures/topic.pdf (text extracted locally …)`, `[Lectures/topic.pdf - page 1] …`, `[Lectures/topic.pdf - page 2] …`, `[end of Lectures/topic.pdf]`, then `Readings/topic.pdf`, then `[Slides/deck.pptx - slide N]`. The two `topic.pdf` files stay distinct by source ID.
- **Scan:** with Efficient on, `Scans/scan.pdf` (image only) extracts to nearly no text, so preparation returns a `needs_original` decision for page 1. The worker emits `decision_needed` and waits; the UI thread shows "`Scans/scan.pdf` (page 1) has little or no extractable text…" with **Process original** / **Cancel**.
  - **Process original:** preparation reruns with `original_overrides={"Scans/scan.pdf"}`. Only that file is sent as a document item; `Lectures/topic.pdf` stays text, in the same single request.
  - **Cancel:** `generate()` returns `cancelled` before any API call, so nothing is written. The status reads "Cancelled. Nothing was sent to Gemini or saved.", the selection stays, and Generate is enabled again.
- **Unusable files** fail before Gemini with the file named: a corrupt DOCX (`Could not read text from broken.docx`), or an empty PPTX or an image with no supported original (`… Export it as a text-based PDF, DOCX or TXT …`).

## Timing (live, 2 one-page PDFs, 2026-11-07)

| Action | Gemini | LaTeX render | Publish | Total |
| --- | --- | --- | --- | --- |
| Make schedule (3 PDFs) | 290.3 s | 7.9 s | <0.1 s | 298 s |
| Make daily study plan, 2 days (6 PDFs) | 405.1 s | 13.6 s | <0.1 s | 419 s |
| M6 rehearsal: daily plan, 2 days, Efficient on, text PDF + scan sent as original | ≈101 s | ≈13.4 s | <0.1 s | 116 s |

The Gemini request dominates, and its latency varies a lot between runs. Local compilation is about 2–3 s per PDF.

## Headless

`python -m late_night_workshop --summarize <file>` runs a Standard Summary (Efficient off) through the same `generate()`, using the PDF's folder as both workshop and destination. It writes `summary.pdf` there, or `summary (2).pdf` and so on if that name is taken.
