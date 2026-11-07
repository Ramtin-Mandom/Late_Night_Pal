# Application workflow

Current state: M7. The same flow runs from the packaged `Late Night Pal.exe` (README "Windows handoff build"). It was rehearsed with a fresh copy of `demo/Biology Demo Workshop`; see the README demo sequence. Open a workshop, select PDF, PPTX, DOCX, TXT or MD files across folders, choose one of eight tasks, optionally turn on Efficient, and generate into the current folder. Component names match `architecture.md`.

Running example: workshop `Biology Workshop/` containing `Lectures/topic.pdf` (photosynthesis), `Readings/topic.pdf` (plate tectonics), and `Revision/` with an existing `summary.pdf`.

## 1. Open a workshop

1. **Desktop UI** start page: "Welcome to Late Night Pal", **Recent Workshops** (full paths from `workshops.load_recents()`), **Open Workshop**, **Create Workshop**.
2. **Open Workshop** opens a folder dialog. **Create Workshop** asks for a parent folder and a name. Clicking a recent workshop opens it. If its folder is gone, a dialog offers **Open another folder...** or **Remove from list**.
3. **Workshop** `open_workshop()` resolves the root and records it in `%LOCALAPPDATA%\late_night_workshop\recents.json`.

## 2. Select inputs across folders

1. Click the name `[folder] Lectures` to open it, then tick `topic.pdf` (or click its name) → `toggle_selection()`. The row turns blue and **Selected Inputs** shows `Lectures/topic.pdf` with a **Remove** button.
2. **Up**, `[folder] Readings`, `topic.pdf` → Selected Inputs lists both relative paths.
3. The selection survives navigation, mode and task changes. Ticking a folder's checkbox selects the folder without opening it. Any file type can be selected (types Make me can't use are greyed). **Remove** deselects an entry from any view, even one deleted on disk; it never deletes the file.
4. **Up**, `[folder] Revision`: this is the destination captured at Generate.

**Make me eligibility.** If the selection holds a folder, an unsupported type, an unreadable file or a missing entry, it is shown in red, the note above Generate names it and why, and Generate stays off. Remove those entries: other selections, task, Days, Folder name, style and Efficient are unchanged. Generation still rechecks files-only at its boundary.

**Refresh** (beside Up) rescans the folder and drops selected entries that no longer exist, naming them in the status. Ordinary redraws never drop selections. **Organize** shows the six actions disabled until P2-M3; they will snapshot root, current folder and selection at click with `organizing.capture_request()`, as Generate does with `build_request()`.

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
4. **Registry** `resolve_task()` → the prompt is `daily-study-plan.md` (with `{days}` = 2), plus `styles/standard.md` and `format.md`. The schema requires exactly 6 documents.
5. **Gemini client** `generate_content()` → **one** request containing both labelled PDFs. Observed: 405 s.
6. **Validation** `validate_bundle()` → requires exactly (day 1..2) × (notes, sample-questions, checklist), different notes on each day, and an allocation covering days 1–2 that uses both sources. Any failure rejects the whole bundle, so nothing is rendered or published.
7. **Renderer** `render_bundle()` → 6 compilations in a temp folder. Observed: 13.6 s in total, about 2 s each.
   Daily PDFs' subtitles name that day's sources from the allocation (`Day 01 · From Lectures/topic.pdf · <date>`).
8. **Publisher** `publish()` → builds `.lnp-staging-*` in `Revision/`, then renames it to `Daily Study Plan/` (or `Daily Study Plan (2)/` if that exists) with `Day 01/` and `Day 02/`. Observed: under 0.1 s.
9. **Desktop UI** shows `Saved 6 PDFs in …\Daily Study Plan:` with the relative list and opens `Day 01/notes.pdf`. **Open output folder** opens `Daily Study Plan/`.

Other layouts:
- **Make schedule** writes `Study Schedule/{schedule,file-guide,checklist}.pdf`. Validation requires a `Day N` heading for every day and a file guide that names every source. Observed: Gemini 290 s, render 7.9 s.
- **Single file** tasks write `<task>.pdf` (`summary (2).pdf` etc. on collision).
- **Answer key** keeps source labels such as `2(b)` and marks unclear questions `FLAGGED:`.
- **One-page cheat sheet** compiles at 8.5 pt, then 7.5 pt. If it's still over one page, generation sends one condensation request, re-renders once, and otherwise fails with `page_limit_exceeded` and publishes nothing.

### Failures and retry (M5)

Nothing is published until every document has validated and compiled, and the temp folder and any staging folder are always removed. The selection, task, Days, Folder name, style and Efficient setting stay as they were, and Generate is enabled again.

- **Malformed response** (for example, day 2's checklist missing): the status shows `Gemini: Gemini's response was unusable (missing checklist for day 2); asking Gemini once to fix it...`. If the repair is also incomplete, it ends with `Checking the request or Gemini's response failed: … (also after one repair attempt)`, then `Nothing was saved…` and `Click Generate to try again…`. That's two Gemini calls in total; no compile runs, and nothing is written.
- **LaTeX failure partway** (document 5 of 6): the status counts through `Rendering: Compiling PDF 5/6: Day 02/sample-questions.pdf`, then shows `Local PDF compilation failed: Couldn't compile Day 02/sample-questions.pdf (document 5 of 6).` and the LaTeX log path in `%LOCALAPPDATA%\late_night_workshop\logs\`. There is one Gemini call and no repair call. The four PDFs that had already compiled were only in the temp folder, so nothing appears in `Revision/`.
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
