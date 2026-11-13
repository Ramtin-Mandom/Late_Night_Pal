# Late Night Pal

A desktop study sidekick that turns study PDFs into locally compiled study PDFs using Codex (default) or the Gemini API. **Current state (M3):** open a workshop (a local study folder), select PDFs across its subfolders, and generate any of eight study outputs into the folder you're viewing. Each Generate starts with one request to the selected provider, and every PDF is compiled locally with LaTeX into a study guide in the style of a tutor's midterm review: numbered section bars, worked examples with boxed answers, a few colour-coded callouts (Rule, Definition, Theorem, Watch for this), a Your turn / Check exercise at the end of each section, and light page citations such as [Lec/lec18.pdf, p. 3]. Sample questions come as a practice test (multiple choice and written response) with an answer key. Nothing existing is ever overwritten.

| Output type | Task | Parameters | Result in the current folder |
| --- | --- | --- | --- |
| Study plan | Make schedule | Days, Folder name (default `Study Schedule`) | `Study Schedule/schedule.pdf`, `file-guide.pdf`, `checklist.pdf` |
| Study plan | Make daily study plan | Days, Folder name (default `Daily Study Plan`) | `Daily Study Plan/Day 01/…` through `Day NN/`, each with `notes.pdf`, `sample-questions.pdf`, `checklist.pdf` |
| Single file | Checklist, Notes, Summary, Answer key, One-page cheat sheet, Sample questions | Language style: Technical, Standard or Simple | `checklist.pdf`, `notes.pdf`, `summary.pdf`, `answer-key.pdf`, `cheat-sheet.pdf` (exactly one page), `sample-questions.pdf` |

If a name is taken, the new output gets a suffix: `summary (2).pdf` or `Study Schedule (2)/`. Days can be any positive whole number; the app never shortens a plan.

**Inputs:** PDF, PPTX, DOCX, TXT and Markdown. Codex uses locally extracted text from the selected files and pages. Scanned or handwritten PDF pages (little or no text) are drawn as page images. Codex `gpt-6-luna` transcribes them to Markdown with LaTeX math, and `gpt-6.1-terra` writes the study documents from that text. Transcriptions are saved in `%LOCALAPPDATA%\late_night_workshop\transcriptions\`, so the next Generate on the same lecture skips that step. For diagrams inside text PDFs, choose **Settings → Generation method → Gemini API**. With Gemini and **Efficient** off, PDFs are sent to Gemini as they are, while PPTX and DOCX are converted to text locally (the status line says so). TXT and MD always go as text. With **Efficient** on, every file is converted to text locally first, keeping page and slide numbers. That can be cheaper, but diagrams, equations, tables and formatting may be lost. Conversions are cached in `%LOCALAPPDATA%\late_night_workshop\conversions\`. In Gemini mode, if a PDF looks scanned (little or no text), the app asks whether to **Process original** (send that file as is) or **Cancel** (nothing is sent).

## Prerequisites (Windows)

- Python 3.11+
- [MiKTeX](https://miktex.org/download) with `lualatex` on PATH. If compiling fails with `lualatex.fmt` errors, rebuild the format once from a normal terminal: `miktex formats build lualatex --engine luahbtex` (the app compiles in a restricted process that can't start MiKTeX's own format builder or package installer; approve any MiKTeX package-install prompt it shows). The app checks for it before making any API call. The selected provider writes each PDF's body in LaTeX using the packages in `rendering.ALLOWED_PACKAGES`; install them beforehand (`siunitx` and `mhchem` are not in a basic MiKTeX; the command is at the end of `latex-packages.txt`), because the compiler runs restricted and cannot reliably install packages on the fly.
- For Codex, use the Codex CLI bundled with Codex desktop on Windows, or install the [Codex CLI](https://developers.openai.com/codex/cli/) on PATH. Sign in using `codex login` with your ChatGPT account. Check access with `codex login status`.
- For Gemini API, use a key from [Google AI Studio](https://aistudio.google.com/app/apikey)

## Setup

From the repository root in PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -e ".[build]"
```

For Gemini only, put the key in `.env` at the repository root (git ignores this file):

```text
GEMINI_API_KEY=your-key-here
# optional; default is gemini-3.8-flash
# GEMINI_MODEL=gemini-3.8-flash
```

A `GEMINI_API_KEY` environment variable works too.

## Run

```powershell
.venv\Scripts\python -m late_night_workshop
```

Demo flow:

1. On the start screen, click **Open Workshop** (or **Create Workshop**) and choose a folder. Recent Workshops are remembered in `%LOCALAPPDATA%\late_night_workshop\recents.json`.
2. Double-click a folder to open it (a single click selects it), and use **Up** to go back. Click a PDF, PPTX, DOCX, TXT or MD file to select it: it turns blue and appears under **Selected Inputs** with its workshop-relative path. Click it again to deselect. Double-click a PDF to read it in Chrome (or the default PDF viewer if Chrome isn't installed); this doesn't change the selection. The selection stays as you move between folders. Ctrl+click toggles a row without opening it, and Shift+click adds a range: click `lecture 18`, then Shift+click `lecture 22` to add 18 to 22. Files are listed like File Explorer (`lecture 2` before `lecture 18`), and picking files doesn't redraw or scroll the list.
   To find a file anywhere in the workshop, type part of its name in the search field above the list (for the demo workshop, `lecture`). Results show workshop-relative paths, so two files with the same name are told apart. Click to select a result, double-click to open a PDF or folder, or use **Show in folder**. Search doesn't change **Save to**; clear the box to go back to the folder you were in, with your selection kept.
   To use only part of a PDF, type pages into its **Pages** box under **Selected Inputs**, such as `1, 3-5, 8`, and press Enter. The note shows the page count and the cleaned-up selection (`Pages 1, 3-5, 8 (5 of 12)`), or what's wrong in red. Leave it empty for All pages. Only those pages are sent, and the provider is told their original page numbers.
   To organize by hand, drag files or folders onto a folder row, onto **Up**, or onto the "Drop here…" box to **move** them (dragging a selected row moves the whole selection), and drag rows from **Recent downloads** onto a folder to **copy** them in. Names that are taken get ` (2)`; nothing is overwritten, and the status line says what happened ("Moved 3 files to Lectures."). The ▼ button under the file list hides the drop area, Recent downloads and Name tags so the list gets the whole column; ▲ brings them back (remembered across restarts).
3. Go to the folder where the result should go. Optionally tick **Efficient**. Choose an **Output type** and **Task**, then set the Language style (Single file) or Days and an optional Folder name (Study plan). Changing tasks keeps your selection. To write your own instructions, pick a task and then **Use my prompt** (last in the list): Generate asks for your text and still produces that task's PDFs.
4. Click **Generate**. All selected files go to the provider selected under **Settings → Generation method** in one request, and the outputs from the table above are saved in the current folder without opening them. Use **Open document** / **Open output folder** when you want to view the results.
5. Click **History** (next to Organize and Make me) to see this workshop's earlier generations, newest first: task, time, inputs with their page choices, settings and the saved PDFs. Select one and use **Open document** or **Open output folder**; files that were moved or deleted are marked unavailable. History is stored in `%LOCALAPPDATA%\late_night_workshop\history\` (one file per workshop, paths relative to it; no API key or document text). If saving History fails, the PDFs are still saved and the status says so: click **Retry saving history** to try again without regenerating. An unreadable history file is kept for recovery and named in a warning.
   **Reuse settings** puts a History entry's inputs, page choices, task, settings, Efficient and Save to folder back into **Make me** so you can generate again (nothing runs until you click **Generate**). If something changed since, such as a deleted input, a file with new contents, pages that no longer exist or a missing Save to folder, the note at the top of Make me names it and Generate stays off until you fix it or choose an option such as **Accept current file** or **Save to current folder**.
   Moving or renaming files with Organize, drag and drop or name tags updates History, so its Open buttons follow the move. If that update can't be saved, use **Retry saving history**: it only rewrites History and never moves files again.
6. Click **Progress** to track a daily study plan: choose the plan (shown by its output folder and the time it was made), then tick Notes, Sample questions and Checklist for each day as you finish them. Each day shows its count, the plan shows its total (`2/6 items complete` for two of six), and every tick is saved straight away and kept after restarting (stored in `%LOCALAPPDATA%\late_night_workshop\progress\`, separate from History). Select an item and click **Open document** to reopen its PDF; opening never ticks it. Plans with the same name, and plans made again with Reuse settings, keep separate progress. Moved PDFs keep their ticks; deleted ones show as unavailable but still count.

If something fails, the status line says which stage failed, what to do next, and that nothing was saved. Your selection and settings stay, so you can just click **Generate** again. LaTeX logs for compile failures are saved in `%LOCALAPPDATA%\late_night_workshop\logs\`.

`Sample_pdf\` works as a ready-made workshop. Expect the Gemini request to take most of the time: with two one-page PDFs, Make schedule took about 5 minutes and a two-day daily plan about 7, while local LaTeX took about 2–3 s per PDF. `workflow.md` has the full breakdown.

Headless checks:

```powershell
.venv\Scripts\python -m late_night_workshop --check                          # resources + LaTeX, no API call
.venv\Scripts\python -m late_night_workshop --summarize Sample_pdf\Note_1.pdf  # one real API call -> Sample_pdf\summary.pdf
```

## Windows handoff build

**Verified on:** Windows 10 Home 22H2 (10.0.19045, 64-bit), with MiKTeX `lualatex` on PATH, on 2026-11-07. The ZIP was extracted to a fresh folder with spaces in its name, outside the checkout, and launched from an unrelated folder without the dev venv. The packaged exe was operated through Windows UI Automation: native Create/Open Workshop dialogs, Recents, then Summary of `Lectures\photosynthesis-lecture.pdf`. It wrote `Revision\summary.pdf` in 218 s (almost all of it Gemini), opened it in the default PDF viewer, and Open output folder opened Explorer on `Revision`.

**Phase 3 packaged walkthrough (P3-M6, 2026-11-09):** same PC, Python 3.12.10 build venv (PySide6 6.12.0, pypdf 7.0.0, google-genai 3.0.0, PyInstaller 6.22.3), MiKTeX 25.12, `gemini-3.8-flash`. The ZIP was extracted to `%TEMP%\LNP P3M6 Packaged Test\` and the exe launched from `C:\Windows` with `LOCALAPPDATA` pointed at a disposable folder (MiKTeX still found its own setup; History and progress stayed separate from real data). `--check` passed: every resource, `svg icons: ok`, lualatex found and `frozen build: True`. The real packaged UI was driven with Windows UI Automation and real mouse input. Search told `Lectures/Week 1/stats-notes.pdf` and `Readings/stats-notes.pdf` apart, and a double-click opened the right one in Chrome. Pages `1, 3-4` showed `Pages 1, 3-4 (3 of 35)`. A two-day plan generated with real Gemini and LaTeX in 55 s (about 37 s Gemini, about 3 s per PDF). History showed the settings, pages and six outputs, and Open document worked. Two ticks gave `2/6` (`1/3`, `1/3`) and survived a full restart. Reuse settings and Generate gave a separate plan, `Daily Study Plan (2)`, at `0/6` (46 s). After a Wrap move, History and Progress opened the moved files and kept `2/6`. An All pages Summary of an 81-page PDF took 85 s. Details are in `PHASE_3_PROJECT_MAP_AND_MILESTONES.md` (P3-M6).

**Phase 2 packaged walkthrough (P2-M7, 2026-11-07):** same PC, Chrome 156.0.8078.80. The rebuilt ZIP was extracted to `%TEMP%\LNP M7 Packaged Test\` (spaces, outside the checkout). `--check` run from `C:\Windows` reported every resource including `assets/recent-downloads-bin.svg`, `svg icons: ok` and `frozen build: True`. The exe was then driven through Windows UI Automation and real mouse input, with `LOCALAPPDATA` pointed at a disposable folder, so recents, tags and cut records stayed apart from the real ones and Chrome data came from a disposable profile made by `tests/chrome_download_probe.py`. Results:
- **Startup and navigation:** the workshop opened from Recents, and folders opened by name.
- **Recent downloads:** the bin icon rendered, and the startup count showed (1). The real download saved to a custom folder was listed with its completion time. Copy to current folder copied it in and kept the original.
- **Super Wrap:** `Calculus/Cal_1/assignment/{1,2}.pdf` and `Calculus/Cal_1/Note_1.pdf`, with the selection following the moved files.
- **Wrap and Rip:** Wrap gave `Batch/Calculus`; Rip moved `Calculus` back up and removed `Batch`.
- **Windows clipboard:** Copy appeared as a file drop list with drop effect 1, and Paste made `scan1 (2).txt`. An Explorer-style cut (`Preferred DropEffect` 2) moved an outside file in, and the clipboard was cleared afterwards.
- **Delete:** the file left disk and appeared in the Recycle Bin.
- **Name tags:** a real mouse drag renamed `scan2.txt` to `assignment_1.txt`. After closing and relaunching, the chip was restored and the next drop gave `assignment_2.txt`.
- **Make me:** Summary of `photosynthesis-lecture.pdf` wrote `summary.pdf` in 239 s, with a temporary `.env` next to the exe that was removed afterwards.

Build with one command from the repository root (about 2 minutes), or double-click `build.cmd`:

```powershell
.\build.cmd
```

It creates `.venv` if it's missing, installs the dependencies, runs `packaging\build_release.py`, then runs the new exe with `--check` from `C:\Windows`; the build fails if that check fails. A Late Night Pal still open from `dist\` locks the files, so the build stops and names it: close it, or run `.\build.cmd --close` to have the build close it first (like clicking X). The manual equivalent is `.venv\Scripts\python -m pip install -e ".[build]"` and then `.venv\Scripts\python packaging\build_release.py`.

- **Share:** `dist\LateNightPal-win64.zip` (about 75 MB).
- **After extracting, launch:** `Late Night Pal\Late Night Pal.exe`. No Python installation is needed.
- The ZIP contains `Late Night Pal.exe`, `_internal\` (Qt with its SVG plugins, Python, and the bundled prompts, templates and `assets\recent-downloads-bin.svg`), `Demo\Biology Demo Workshop\`, `Demo\Example output\M6 Daily Study Plan (pre-fix)\`, `.env.example` and `READ ME FIRST.txt`.
- The build script refuses to zip `.env` files, logs, caches, `recents.json`, or any file containing the developer's key. It also keeps every path inside the ZIP under 150 characters, because Windows limits full paths to 260.

**On the receiving PC:**

1. Install [MiKTeX](https://miktex.org/download) and make sure `lualatex` is on PATH. Compile something once so MiKTeX finishes installing its packages and fonts before the demo.
2. Extract the ZIP anywhere. A short path such as `C:\Demo` is safest.
3. Set up the signed-in Codex CLI, or select **Settings → Generation method → Gemini API** and provide its key at runtime: copy `.env.example` to `.env` next to `Late Night Pal.exe` and fill in `GEMINI_API_KEY`, or set the `GEMINI_API_KEY` environment variable. A `.env` in the current working directory also works. The key is never bundled.
4. Optional preflight from PowerShell in the extracted folder: `& ".\Late Night Pal.exe" --check`. It lists the 17 bundled resources (prompts, templates and their shared style, the LaTeX read guard and the bin icon), `svg icons: ok` (Qt can draw the icon), `lualatex`, whether a key was found (never the key itself), and `frozen build: True`. `--extract <file>` prints what local conversion produces for a PDF, PPTX, DOCX, TXT or MD file.

The executable is windowed. Command-line modes print to the PowerShell window they were started from.

## Demo sequence (rehearsed 2026-11-07)

The demo workshop is `Demo\Biology Demo Workshop\` in the ZIP, or `demo\Biology Demo Workshop\` in the repository:

- `Lectures\photosynthesis-lecture.pdf` is a text PDF about photosynthesis.
- `Labs\osmosis-lab-scan.pdf` is an image-only scanned osmosis lab. Its unique fact is that potato strips in **0.8 M sucrose lost 14% of their mass**, and the cells are isotonic with about 0.4 M sucrose.
- `Revision\` is empty, ready for output.

**Before each run, copy `Biology Demo Workshop` to a fresh place** (for example your Desktop) and open that copy. The original stays clean, and every run starts with an empty `Revision\`.

1. Launch `Late Night Pal.exe` (or `.venv\Scripts\python -m late_night_workshop` from the repository). Click **Open Workshop** and choose your fresh copy. Later you can reopen it from **Recent Workshops**.
2. Click `[folder] Lectures` → `photosynthesis-lecture.pdf`, **Up**, `[folder] Labs` → `osmosis-lab-scan.pdf`, **Up**, `[folder] Revision`. **Selected Inputs** shows both relative paths.
3. Select **Settings → Generation method → Gemini API** for this scanned-PDF demo. Choose **Output type: Study plan**, **Task: Make daily study plan**, **Days: 2**, leave **Folder name** empty, and tick **Efficient**. Click **Generate**.
4. A dialog says `Labs/osmosis-lab-scan.pdf (page 1) has little or no extractable text…`. Click **Process original**.
5. While Gemini works (about 2 minutes in the rehearsal; earlier runs took up to 7), open the labelled example `Example output\M6 Daily Study Plan (pre-fix)\Day 01\notes.pdf`. It was built from the scan and states the 0.8 M → −14% result, and its subtitle reads `From Labs/osmosis-lab-scan.pdf`. It is the M6 rehearsal output from **before the answer-label fix**, so its *Answers* sections lack `Q1`/`Q2` labels; fresh runs label them.
6. When the status shows `Saved 6 PDFs in …\Revision\Daily Study Plan`, the PDFs stay in that folder without opening. Use **Open document** to view the first PDF or **Open output folder** to show `Day 01\` and `Day 02\`, each with `notes.pdf`, `sample-questions.pdf` and `checklist.pdf`.

**Quick single-file demo** (verified from the packaged build): on a fresh copy, select only `Lectures\photosynthesis-lecture.pdf`, open `Revision`, choose **Single file → Summary**, then **Generate**. The result is `Revision\summary.pdf`.
