# Application workflow

Current state: M2. Open a workshop, select PDFs across folders, and generate one combined Summary into the current folder. Component names match `architecture.md`.

Running example: workshop `Biology Workshop/` containing `Lectures/topic.pdf` (photosynthesis), `Readings/topic.pdf` (plate tectonics), and `Revision/` with an existing `summary.pdf`.

## 1. Open a workshop

1. **Desktop UI** start page: "Welcome to Late Night Pal", **Recent Workshops** (full paths from `workshops.load_recents()`), **Open Workshop**, **Create Workshop**.
2. **Open Workshop** opens a folder dialog. **Create Workshop** asks for a parent folder and a name, then calls `create_workshop()`. Clicking a recent workshop opens it. If its folder is gone, a dialog offers **Open another folder...** or **Remove from list**.
3. **Workshop** `open_workshop()` resolves the root, adds it to recents (`%LOCALAPPDATA%\late_night_workshop\recents.json`), and the UI shows the root folder.

## 2. Select inputs across folders

1. Click `[folder] Lectures` and the browser enters that folder (`browse()`). Click `topic.pdf` → `toggle_selection()`. The row turns blue and **Selected Inputs** lists `Lectures/topic.pdf`.
2. **Up**, then `[folder] Readings` → `topic.pdf`. Selected Inputs now lists `Lectures/topic.pdf` and `Readings/topic.pdf`, so same-named files can be told apart.
3. Navigating anywhere keeps the selection (it is stored as resolved paths, not per view). Clicking a selected file again deselects it. Non-PDF files are greyed and can't be selected yet.
4. **Up**, then `[folder] Revision`: this becomes the current folder, i.e. the destination.

## 3. Generate

1. **Generate** → `ui.build_request()` snapshots `{workshop_root, destination: .../Revision, selected_paths: [Lectures/topic.pdf, Readings/topic.pdf], task_id: "summary", efficient: False}`. Generate is disabled while the job runs; a second click is ignored.
2. A `Worker` runs `generation.generate(request)` on a `QThread`; stage messages appear in the status text:
   1. **Workshop** `validate_paths()` rechecks containment and readability.
   2. **Renderer** `check_runtime()` and **Publisher** `check_destination()`. Missing LaTeX stops here with `missing_latex`; no Gemini call.
   3. **Inputs** `prepare_inputs()` → two original-PDF source records with IDs `Lectures/topic.pdf` and `Readings/topic.pdf` and sha256 fingerprints.
   4. **Registry** `resolve_task()` → the Summary prompt with a source index.
   5. **Gemini client** `generate_content()` → **one** request: `Source 1: Lectures/topic.pdf`, PDF, `Source 2: Readings/topic.pdf`, PDF, prompt.
   6. **Validation** `validate_bundle()` → one `summary` document. Malformed JSON → `invalid_response`.
   7. **Renderer** `render_bundle()` compiles in a temp folder, with subtitle `From Lectures/topic.pdf, Readings/topic.pdf · <date>`.
   8. **Publisher** `publish()` → `summary.pdf` exists, so it creates `Revision/summary (2).pdf` exclusively. The existing file is untouched.
3. Success: the status shows `Saved: <full path>`, the PDF opens, and **Open document** / **Open output folder** become active. Failure: `Error: <message>`, no new file in `Revision/`, and the selection and task stay as they were.

## Headless

`python -m late_night_workshop --summarize <file.pdf>` runs the same `generate()` with the PDF's folder as both workshop and destination, writing `summary.pdf` (or `summary (2).pdf` and so on) there.
