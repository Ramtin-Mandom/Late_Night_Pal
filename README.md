# Late Night Pal

A desktop study sidekick that turns study PDFs into locally compiled study PDFs using Gemini. **Current state (M3):** open a workshop (a local study folder), select PDFs across its subfolders, and generate any of eight study outputs into the folder you're viewing. Each Generate sends one Gemini request, and every PDF is compiled locally with LaTeX. Nothing existing is ever overwritten.

| Output type | Task | Parameters | Result in the current folder |
| --- | --- | --- | --- |
| Study plan | Make schedule | Days, Folder name (default `Study Schedule`) | `Study Schedule/schedule.pdf`, `file-guide.pdf`, `checklist.pdf` |
| Study plan | Make daily study plan | Days, Folder name (default `Daily Study Plan`) | `Daily Study Plan/Day 01/…` through `Day NN/`, each with `notes.pdf`, `sample-questions.pdf`, `checklist.pdf` |
| Single file | Checklist, Notes, Summary, Answer key, One-page cheat sheet, Sample questions | Language style: Technical, Standard or Simple | `checklist.pdf`, `notes.pdf`, `summary.pdf`, `answer-key.pdf`, `cheat-sheet.pdf` (exactly one page), `sample-questions.pdf` |

If a name is taken, the new output gets a suffix: `summary (2).pdf` or `Study Schedule (2)/`. Days can be any positive whole number; the app never shortens a plan.

**Inputs:** PDF, PPTX, DOCX, TXT and Markdown. With **Efficient** off, PDFs are sent to Gemini as they are, while PPTX and DOCX are converted to text locally (the status line says so). TXT and MD always go as text. With **Efficient** on, every file is converted to text locally first, keeping page and slide numbers. That can be cheaper, but diagrams, equations, tables and formatting may be lost. Conversions are cached in `%LOCALAPPDATA%\late_night_workshop\conversions\`. If a PDF looks scanned (little or no text), the app asks whether to **Process original** (send that file as is) or **Cancel** (nothing is sent).

## Prerequisites (Windows)

- Python 3.11+
- [MiKTeX](https://miktex.org/download) with `lualatex` on PATH. The app checks for it before making any API call. Gemini writes each PDF's body in LaTeX using the packages in `rendering.ALLOWED_PACKAGES`; install them beforehand (`siunitx` and `mhchem` are not in a basic MiKTeX; the command is at the end of `latex-packages.txt`), because the compiler runs restricted and cannot reliably install packages on the fly.
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey)

## Setup

From the repository root in PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -e ".[build]"
```

Put the key in `.env` at the repository root (git ignores this file):

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
2. Click a folder to open it, and use **Up** to go back. Click a PDF, PPTX, DOCX, TXT or MD file to select it: it turns blue and appears under **Selected Inputs** with its workshop-relative path. Click it again to deselect. The selection stays as you move between folders. Ctrl+click toggles a row without opening it, and Shift+click adds a range.
   To organize by hand, drag files or folders onto a folder row, onto **Up**, or onto the "Drop here…" box to **move** them (dragging a selected row moves the whole selection), and drag rows from **Recent downloads** onto a folder to **copy** them in. Names that are taken get ` (2)`; nothing is overwritten, and the status line says what happened ("Moved 3 files to Lectures.").
3. Go to the folder where the result should go. Optionally tick **Efficient**. Choose an **Output type** and **Task**, then set the Language style (Single file) or Days and an optional Folder name (Study plan). Changing tasks keeps your selection.
4. Click **Generate**. All selected files go to Gemini in one request, and the outputs from the table above are saved in the current folder. The first PDF opens automatically, and **Open document** / **Open output folder** reopen it.

If something fails, the status line says which stage failed, what to do next, and that nothing was saved. Your selection and settings stay, so you can just click **Generate** again. LaTeX logs for compile failures are saved in `%LOCALAPPDATA%\late_night_workshop\logs\`.

`Sample_pdf\` works as a ready-made workshop. Expect the Gemini request to take most of the time: with two one-page PDFs, Make schedule took about 5 minutes and a two-day daily plan about 7, while local LaTeX took about 2–3 s per PDF. `workflow.md` has the full breakdown.

Headless checks:

```powershell
.venv\Scripts\python -m late_night_workshop --check                          # resources + LaTeX, no API call
.venv\Scripts\python -m late_night_workshop --summarize Sample_pdf\Note_1.pdf  # one real API call -> Sample_pdf\summary.pdf
```

## Windows handoff build

**Verified on:** Windows 10 Home 22H2 (10.0.19045, 64-bit), with MiKTeX `lualatex` on PATH, on 2026-11-07. The ZIP was extracted to a fresh folder with spaces in its name, outside the checkout, and launched from an unrelated folder without the dev venv. The packaged exe was operated through Windows UI Automation: native Create/Open Workshop dialogs, Recents, then Summary of `Lectures\photosynthesis-lecture.pdf`. It wrote `Revision\summary.pdf` in 218 s (almost all of it Gemini), opened it in the default PDF viewer, and Open output folder opened Explorer on `Revision`.

**Phase 2 packaged walkthrough (P2-M7, 2026-11-07):** same PC, Chrome 156.0.8078.80. The rebuilt ZIP was extracted to `%TEMP%\LNP M7 Packaged Test\` (spaces, outside the checkout). `--check` run from `C:\Windows` reported every resource including `assets/recent-downloads-bin.svg`, `svg icons: ok` and `frozen build: True`. The exe was then driven through Windows UI Automation and real mouse input, with `LOCALAPPDATA` pointed at a disposable folder, so recents, tags and cut records stayed apart from the real ones and Chrome data came from a disposable profile made by `tests/chrome_download_probe.py`. Results:
- **Startup and navigation:** the workshop opened from Recents, and folders opened by name.
- **Recent downloads:** the bin icon rendered, and the startup count showed (1). The real download saved to a custom folder was listed with its completion time. Copy to current folder copied it in and kept the original.
- **Super Wrap:** `Calculus/Cal_1/assignment/{1,2}.pdf` and `Calculus/Cal_1/Note_1.pdf`, with the selection following the moved files.
- **Wrap and Rip:** Wrap gave `Batch/Calculus`; Rip moved `Calculus` back up and removed `Batch`.
- **Windows clipboard:** Copy appeared as a file drop list with drop effect 1, and Paste made `scan1 (2).txt`. An Explorer-style cut (`Preferred DropEffect` 2) moved an outside file in, and the clipboard was cleared afterwards.
- **Delete:** the file left disk and appeared in the Recycle Bin.
- **Name tags:** a real mouse drag renamed `scan2.txt` to `assignment_1.txt`. After closing and relaunching, the chip was restored and the next drop gave `assignment_2.txt`.
- **Make me:** Summary of `photosynthesis-lecture.pdf` wrote `summary.pdf` in 239 s, with a temporary `.env` next to the exe that was removed afterwards.

Build from the repository root (about 1½ minutes):

```powershell
.venv\Scripts\python -m pip install -e ".[build]"
.venv\Scripts\python packaging\build_release.py
```

- **Share:** `dist\LateNightPal-win64.zip` (about 75 MB).
- **After extracting, launch:** `Late Night Pal\Late Night Pal.exe`. No Python installation is needed.
- The ZIP contains `Late Night Pal.exe`, `_internal\` (Qt with its SVG plugins, Python, and the bundled prompts, templates and `assets\recent-downloads-bin.svg`), `Demo\Biology Demo Workshop\`, `Demo\Example output\M6 Daily Study Plan (pre-fix)\`, `.env.example` and `READ ME FIRST.txt`.
- The build script refuses to zip `.env` files, logs, caches, `recents.json`, or any file containing the developer's key. It also keeps every path inside the ZIP under 150 characters, because Windows limits full paths to 260.

**On the receiving PC:**

1. Install [MiKTeX](https://miktex.org/download) and make sure `lualatex` is on PATH. Compile something once so MiKTeX finishes installing its packages and fonts before the demo.
2. Extract the ZIP anywhere. A short path such as `C:\Demo` is safest.
3. Provide the Gemini key at runtime: copy `.env.example` to `.env` next to `Late Night Pal.exe` and fill in `GEMINI_API_KEY`, or set the `GEMINI_API_KEY` environment variable. A `.env` in the current working directory also works. The key is never bundled.
4. Optional preflight from PowerShell in the extracted folder: `& ".\Late Night Pal.exe" --check`. It lists the 16 bundled resources (prompts, templates, the LaTeX read guard and the bin icon), `svg icons: ok` (Qt can draw the icon), `lualatex`, whether a key was found (never the key itself), and `frozen build: True`. `--extract <file>` prints what local conversion produces for a PDF, PPTX, DOCX, TXT or MD file.

The executable is windowed. Command-line modes print to the PowerShell window they were started from.

## Demo sequence (rehearsed 2026-11-07)

The demo workshop is `Demo\Biology Demo Workshop\` in the ZIP, or `demo\Biology Demo Workshop\` in the repository:

- `Lectures\photosynthesis-lecture.pdf` is a text PDF about photosynthesis.
- `Labs\osmosis-lab-scan.pdf` is an image-only scanned osmosis lab. Its unique fact is that potato strips in **0.8 M sucrose lost 14% of their mass**, and the cells are isotonic with about 0.4 M sucrose.
- `Revision\` is empty, ready for output.

**Before each run, copy `Biology Demo Workshop` to a fresh place** (for example your Desktop) and open that copy. The original stays clean, and every run starts with an empty `Revision\`.

1. Launch `Late Night Pal.exe` (or `.venv\Scripts\python -m late_night_workshop` from the repository). Click **Open Workshop** and choose your fresh copy. Later you can reopen it from **Recent Workshops**.
2. Click `[folder] Lectures` → `photosynthesis-lecture.pdf`, **Up**, `[folder] Labs` → `osmosis-lab-scan.pdf`, **Up**, `[folder] Revision`. **Selected Inputs** shows both relative paths.
3. Choose **Output type: Study plan**, **Task: Make daily study plan**, **Days: 2**, leave **Folder name** empty, and tick **Efficient**. Click **Generate**.
4. A dialog says `Labs/osmosis-lab-scan.pdf (page 1) has little or no extractable text…`. Click **Process original**.
5. While Gemini works (about 2 minutes in the rehearsal; earlier runs took up to 7), open the labelled example `Example output\M6 Daily Study Plan (pre-fix)\Day 01\notes.pdf`. It was built from the scan and states the 0.8 M → −14% result, and its subtitle reads `From Labs/osmosis-lab-scan.pdf`. It is the M6 rehearsal output from **before the answer-label fix**, so its *Answers* sections lack `Q1`/`Q2` labels; fresh runs label them.
6. When the status shows `Saved 6 PDFs in …\Revision\Daily Study Plan`, `Day 01\notes.pdf` opens automatically. Use **Open output folder** to show `Day 01\` and `Day 02\`, each with `notes.pdf`, `sample-questions.pdf` and `checklist.pdf`.

**Quick single-file demo** (verified from the packaged build): on a fresh copy, select only `Lectures\photosynthesis-lecture.pdf`, open `Revision`, choose **Single file → Summary**, then **Generate**. The result is `Revision\summary.pdf`.
