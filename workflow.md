# Application workflow

Current state: M3. Open a workshop, select PDFs across folders, choose one of eight tasks, and generate into the current folder. Component names match `architecture.md`.

Running example: workshop `Biology Workshop/` containing `Lectures/topic.pdf` (photosynthesis), `Readings/topic.pdf` (plate tectonics), and `Revision/` with an existing `summary.pdf`.

## 1. Open a workshop

1. **Desktop UI** start page: "Welcome to Late Night Pal", **Recent Workshops** (full paths from `workshops.load_recents()`), **Open Workshop**, **Create Workshop**.
2. **Open Workshop** opens a folder dialog. **Create Workshop** asks for a parent folder and a name. Clicking a recent workshop opens it. If its folder is gone, a dialog offers **Open another folder...** or **Remove from list**.
3. **Workshop** `open_workshop()` resolves the root and records it in `%LOCALAPPDATA%\late_night_workshop\recents.json`.

## 2. Select inputs across folders

1. Click `[folder] Lectures`, then `topic.pdf` → `toggle_selection()`. The row turns blue and **Selected Inputs** shows `Lectures/topic.pdf`.
2. **Up**, `[folder] Readings`, `topic.pdf` → Selected Inputs lists both relative paths.
3. The selection survives navigation and task changes. Clicking a selected file again deselects it. Non-PDF files are greyed out.
4. **Up**, `[folder] Revision`: this is the destination captured at Generate.

## 3. Choose a task and parameters

- **Output type → Single file**: Task is Checklist, Notes, **Summary** (default), Answer key, One-page cheat sheet or Sample questions, plus **Language style** (Technical / **Standard** / Simple).
- **Output type → Study plan**: Task is Make schedule or Make daily study plan, plus **Days** (1–30, default 2) and **Folder name** (the placeholder shows the default, `Study Schedule` or `Daily Study Plan`).
- **Generate** → `ui.build_request()` snapshot → `tasks.validate_parameters()`. A bad folder name such as `bad/name` shows an error in the status line, and no job starts.

## 4. Generate (example: Make daily study plan, Days = 2)

A `Worker` runs `generation.generate(request)` on a `QThread`; Generate is disabled until it ends.

1. **Registry** `validate_parameters()` and **Workshop** `validate_paths()`.
2. **Renderer** `check_runtime()` and **Publisher** `check_destination()`. Missing LaTeX stops here, before any Gemini call.
3. **Inputs** `prepare_inputs()` → two original-PDF source records.
4. **Registry** `resolve_task()` → the prompt is `daily-study-plan.md` (with `{days}` = 2), plus `styles/standard.md` and `format.md`. The schema requires exactly 6 documents.
5. **Gemini client** `generate_content()` → **one** request containing both labelled PDFs. Observed: 405 s.
6. **Validation** `validate_bundle()` → requires exactly (day 1..2) × (notes, sample-questions, checklist), different notes on each day, and an allocation covering days 1–2 that uses both sources. Any failure rejects the whole bundle, so nothing is rendered or published.
7. **Renderer** `render_bundle()` → 6 compilations in a temp folder. Observed: 13.6 s in total, about 2 s each.
8. **Publisher** `publish()` → builds `.lnp-staging-*` in `Revision/`, then renames it to `Daily Study Plan/` (or `Daily Study Plan (2)/` if that exists) with `Day 01/` and `Day 02/`. Observed: under 0.1 s.
9. **Desktop UI** shows `Saved 6 PDFs in …\Daily Study Plan:` with the relative list and opens `Day 01/notes.pdf`. **Open output folder** opens `Daily Study Plan/`.

Other layouts:
- **Make schedule** writes `Study Schedule/{schedule,file-guide,checklist}.pdf`. Validation requires a `Day N` heading for every day and a file guide that names every source. Observed: Gemini 290 s, render 7.9 s.
- **Single file** tasks write `<task>.pdf` (`summary (2).pdf` etc. on collision).
- **Answer key** keeps source labels such as `2(b)` and marks unclear questions `FLAGGED:`.
- **One-page cheat sheet** compiles at 8.5 pt, then 7.5 pt. If it's still over one page, generation sends one condensation request, re-renders once, and otherwise fails with `page_limit_exceeded` and publishes nothing.

Failures show `Error: <message>` and leave the selection and parameters unchanged.

## Timing (live, 2 one-page PDFs, 2026-11-07)

| Action | Gemini | LaTeX render | Publish | Total |
| --- | --- | --- | --- | --- |
| Make schedule (3 PDFs) | 290.3 s | 7.9 s | <0.1 s | 298 s |
| Make daily study plan, 2 days (6 PDFs) | 405.1 s | 13.6 s | <0.1 s | 419 s |

The Gemini request dominates. Local compilation is about 2–3 s per PDF.

## Headless

`python -m late_night_workshop --summarize <file.pdf>` runs a Standard Summary through the same `generate()`, using the PDF's folder as both workshop and destination. It writes `summary.pdf` there, or `summary (2).pdf` and so on if that name is taken.
